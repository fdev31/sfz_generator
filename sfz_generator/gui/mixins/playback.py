import threading
import os
import tempfile
from gi.repository import GLib, Adw


class PlaybackMixin:
    def on_play_clicked(self, button):
        if not self.is_playing:
            self.is_playing = True
            self.stop_playback_event.clear()
            self.play_button.set_sensitive(False)
            self.stop_button.set_sensitive(True)

            self.waveform_widget.set_playback_state(True, self.loop_playback_check.get_active())

            args = (
                self.audio_data_int16,
                self.sample_rate,
                self.loop_playback_check.get_active(),
                self.loop_start,
                self.loop_end,
                self.stop_playback_event,
                self.show_playback_error,
                self.playback_finished,
            )
            self.playback_thread = threading.Thread(target=self.play_func, args=args)
            self.playback_thread.daemon = True
            self.playback_thread.start()

    def on_stop_clicked(self, button):
        if self.is_playing:
            self.stop_playback_event.set()
        self.is_playing = False
        self.play_button.set_sensitive(True)
        self.stop_button.set_sensitive(False)

        # Update waveform widget
        self.waveform_widget.set_playback_state(False)

    def playback_finished(self):
        self.is_playing = False
        GLib.idle_add(self.play_button.set_sensitive, True)
        GLib.idle_add(self.stop_button.set_sensitive, False)

        # Update waveform widget
        GLib.idle_add(self.waveform_widget.set_playback_state, False)

    def show_playback_error(self, error_msg):
        dialog = Adw.MessageDialog.new(self, "Playback Error", "Failed to play audio")
        dialog.set_body(f"Error: {error_msg}")
        dialog.add_response("ok", "OK")
        dialog.set_modal(True)
        dialog.present()

    def note_playback_worker(self):
        while True:
            action, note = self.note_queue.get()
            if action == "on":
                if note in self.playing_notes:
                    continue  # Note already playing

                stop_event = threading.Event()
                self.playing_notes[note] = stop_event

                def run_playback(note, stop_event):
                    GLib.idle_add(self.piano_widget.set_note_active, note)

                    sfz_content_or_path = self.sfz_buffer.get_text(
                        self.sfz_buffer.get_start_iter(),
                        self.sfz_buffer.get_end_iter(),
                        True,
                    )

                    base_dir = None
                    temp_sfz_path = None

                    try:
                        if self.generated_instrument_path:
                            # For generated instruments, relative paths need a file location.
                            with tempfile.NamedTemporaryFile(mode="w", suffix=".sfz", delete=False) as temp_sfz:
                                temp_sfz.write(sfz_content_or_path)
                                temp_sfz_path = temp_sfz.name
                            sfz_content_or_path = temp_sfz_path
                            base_dir = os.path.dirname(self.generated_instrument_path)

                        self.play_sfz_note_func(sfz_content_or_path, base_dir, note, 4, self.playback_lock, stop_event)

                    finally:
                        if temp_sfz_path and os.path.exists(temp_sfz_path):
                            os.unlink(temp_sfz_path)

                        GLib.idle_add(self.piano_widget.set_note_inactive, note)
                        if note in self.playing_notes:
                            del self.playing_notes[note]

                thread = threading.Thread(target=run_playback, args=(note, stop_event))
                thread.daemon = True
                thread.start()

            elif action == "off":
                if note in self.playing_notes:
                    self.playing_notes[note].set()

            self.note_queue.task_done()
