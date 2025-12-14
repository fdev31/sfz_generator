import atexit
import queue
import subprocess
import threading
import time

import jack

PREVIEW_CLIENT_NAME = "sfz_preview"


class JackClient:
    def __init__(self):
        self.client = None
        self.command_queue = queue.Queue()
        self._closed = False
        self._close_lock = threading.Lock()
        self.worker_thread = threading.Thread(target=self._worker, daemon=True)
        self.worker_thread.start()
        atexit.register(self.close)

    def _worker(self):
        preview_process = None
        worker_client = None

        def _get_worker_client():
            nonlocal worker_client
            if worker_client is None:
                # Use a different name for the client in the worker thread
                worker_client = jack.Client("sfz_generator_worker_client")
            return worker_client

        def _stop_process_gracefully(proc):
            if not proc or proc.poll() is not None:
                return None

            try:
                proc.stdin.write(b"quit\n")
                proc.stdin.flush()
                proc.wait(timeout=1.0)
                return None  # Success
            except (subprocess.TimeoutExpired, BrokenPipeError, OSError):
                pass  # Didn't quit gracefully, proceed to kill

            if proc.poll() is None:
                try:
                    proc.terminate()  # SIGTERM
                    proc.wait(timeout=1.0)
                    return None
                except (subprocess.TimeoutExpired, OSError):
                    pass  # Didn't terminate, proceed to force kill

            if proc.poll() is None:
                try:
                    proc.kill()  # SIGKILL
                    proc.wait()
                except OSError:
                    pass  # Already dead
            return None

        while True:
            try:
                command_tuple = self.command_queue.get()
                cmd, *args = command_tuple

                if cmd == "start":
                    preview_process = _stop_process_gracefully(preview_process)

                    sfz_file, cwd = args[0]
                    command = [
                        "sfizz_jack",
                        "--jack_autoconnect",
                        "1",
                        "--client_name",
                        PREVIEW_CLIENT_NAME,
                        sfz_file,
                    ]
                    preview_process = subprocess.Popen(
                        command,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        cwd=cwd,
                    )
                    # Wait a bit for sfizz to start and register its ports
                    time.sleep(0.5)

                elif cmd == "stop":
                    preview_process = _stop_process_gracefully(preview_process)

                elif cmd == "connect":
                    midi_port = args[0]
                    client = _get_worker_client()
                    try:
                        preview_port = f"{PREVIEW_CLIENT_NAME}:input"
                        client.connect(midi_port, preview_port)
                    except jack.JackError as e:
                        print(f"Failed to connect: {e}")

                elif cmd == "disconnect":
                    midi_port = args[0]
                    if worker_client is None:
                        continue  # No client, so can't be connected.
                    try:
                        preview_port = f"{PREVIEW_CLIENT_NAME}:input"
                        worker_client.disconnect(midi_port, preview_port)
                    except jack.JackError as e:
                        print(f"Failed to disconnect: {e}")

                elif cmd == "shutdown":
                    preview_process = _stop_process_gracefully(preview_process)
                    if worker_client:
                        worker_client.close()
                    break
            except Exception as e:
                print(f"Error in JackClient worker thread: {e}")
                # Ensure shutdown command still exits the loop
                if "cmd" in locals() and cmd == "shutdown":
                    if worker_client:
                        worker_client.close()
                    break

    def get_midi_ports(self):
        if not self.is_jack_server_running():
            return []
        try:
            if not self.client:
                self.client = jack.Client("sfz_generator_client")
            return self.client.get_ports(is_midi=True, is_output=True)
        except jack.JackError:
            return []

    def start_preview(self, sfz_file, cwd=None):
        self.command_queue.queue.clear()
        self.command_queue.put(("start", (sfz_file, cwd)))

    def stop_preview(self):
        self.command_queue.put(("stop",))

    def connect(self, midi_port):
        self.command_queue.put(("connect", midi_port))

    def disconnect(self, midi_port):
        self.command_queue.put(("disconnect", midi_port))

    def is_jack_server_running(self):
        try:
            jack.Client("ping")
            return True
        except jack.JackError:
            return False

    def close(self):
        with self._close_lock:
            if self._closed:
                return
            self._closed = True

        self.command_queue.put(("shutdown",))
        try:
            # Add a timeout to join to avoid hanging on exit
            self.worker_thread.join(timeout=3.0)
        except Exception as e:
            print(f"Error joining worker thread: {e}")

        if self.client:
            try:
                self.client.close()
            except Exception as e:
                print(f"Error closing jack client: {e}")
