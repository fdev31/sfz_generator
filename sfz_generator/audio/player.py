import sounddevice as sd
from gi.repository import GLib


def play(audio_data, sample_rate, loop, loop_start, loop_end, stop_event, error_callback, finished_callback):
    """Plays audio data using sounddevice."""

    if audio_data is None:
        GLib.idle_add(finished_callback)
        return

    channels = 1 if audio_data.ndim == 1 else audio_data.shape[1]
    frames_per_chunk = max(sample_rate // 20, 1024)

    def as_frames(buffer):
        return buffer.reshape(-1, 1) if channels == 1 else buffer

    try:
        with sd.OutputStream(samplerate=sample_rate, channels=channels, dtype=audio_data.dtype) as stream:
            if loop and loop_start is not None and loop_end is not None and loop_end > loop_start:
                loop_segment = audio_data[loop_start:loop_end]
                if loop_segment.size == 0:
                    GLib.idle_add(finished_callback)
                    return
                loop_frames = as_frames(loop_segment)
                while not stop_event.is_set():
                    stream.write(loop_frames)
            else:
                frames = as_frames(audio_data)
                total_frames = frames.shape[0]
                current_frame = 0
                while current_frame < total_frames and not stop_event.is_set():
                    chunk_end = min(current_frame + frames_per_chunk, total_frames)
                    stream.write(frames[current_frame:chunk_end])
                    current_frame = chunk_end
            if stop_event.is_set():
                stream.abort()

    except Exception as e:
        GLib.idle_add(error_callback, str(e))
    finally:
        GLib.idle_add(finished_callback)
