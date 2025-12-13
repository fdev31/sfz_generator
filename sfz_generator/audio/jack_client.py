import os
import subprocess
import time

import jack

PREVIEW_CLIENT_NAME = "sfz_preview"


class JackClient:
    def __init__(self):
        self.client = None
        self.preview_process = None

    def get_midi_ports(self):
        if not self.is_jack_server_running():
            return []
        try:
            if not self.client:
                self.client = jack.Client("sfz_generator_client")
            return self.client.get_ports(is_midi=True, is_output=True)
        except jack.JackError:
            return []

    def start_preview(self, sfz_file):
        if self.preview_process:
            self.stop_preview()
        command = [
            "sfizz_jack",
            "--jack_autoconnect",
            "1",
            "--client_name",
            PREVIEW_CLIENT_NAME,
            sfz_file,
        ]
        self.preview_process = subprocess.Popen(command, stdin=subprocess.DEVNULL)
        # Wait a bit for sfizz to start and register its ports
        time.sleep(0.5)

    def stop_preview(self):
        if self.preview_process:
            pid = self.preview_process.pid
            self.preview_process.terminate()
            self.preview_process.kill()
            os.kill(pid, 9)
            self.preview_process.wait()
            self.preview_process = None

    def connect(self, midi_port):
        if not self.client:
            self.client = jack.Client("sfz_generator_client")
        try:
            preview_port = f"{PREVIEW_CLIENT_NAME}:input"
            self.client.connect(midi_port, preview_port)
        except jack.JackError as e:
            print(f"Failed to connect: {e}")

    def disconnect(self, midi_port):
        if not self.client:
            return
        try:
            preview_port = f"{PREVIEW_CLIENT_NAME}:input"
            self.client.disconnect(midi_port, preview_port)
        except jack.JackError as e:
            print(f"Failed to disconnect: {e}")

    def is_jack_server_running(self):
        try:
            jack.Client("ping")
            return True
        except jack.JackError:
            return False

    def close(self):
        self.stop_preview()
        if self.client:
            self.client.close()
