from gi.repository import Adw, Gtk, GLib, Gio
import os
from pathlib import Path
import threading


class ProcessingMixin:
    def show_generation_complete_dialog(self, sfz_path, num_successful, num_total):
        if num_successful == 0:
            dialog = Adw.MessageDialog.new(self, "Generation Failed", "No samples were generated successfully.")
            dialog.add_response("ok", "OK")
        else:
            dialog = Adw.MessageDialog.new(self, "Generation Complete", f"Successfully generated {num_successful}/{num_total} samples.")
            if sfz_path:
                dialog.set_body(f"Instrument saved to:\n{os.path.dirname(sfz_path)}")
            dialog.add_response("ok", "OK")

        dialog.set_modal(True)
        dialog.present()

    def on_process_clicked(self, button):
        if not self.audio_file_path:
            dialog = Adw.MessageDialog.new(self, "No Audio File", "Please open an audio file first.")
            dialog.add_response("ok", "OK")
            dialog.set_modal(True)
            dialog.present()
            return

        file_dialog = Gtk.FileDialog.new()
        file_dialog.set_title("Save Instrument Folder")
        if self.audio_file_path:
            initial_folder = Gio.File.new_for_path(os.path.dirname(self.audio_file_path))
            file_dialog.set_initial_folder(initial_folder)
            file_dialog.set_initial_name(Path(self.audio_file_path).stem)

        file_dialog.select_folder(self, None, self._on_folder_selected_for_processing)

    def _on_folder_selected_for_processing(self, dialog, result):
        try:
            folder = dialog.select_folder_finish(result)
            if folder:
                output_dir = folder.get_path()
                thread = threading.Thread(target=self.generate_pitch_shifted_sfz, args=(output_dir,))
                thread.daemon = True
                thread.start()
        except Exception as e:
            print(f"Error selecting folder for processing: {e}")

    def _update_progress(self, current, total):
        fraction = current / total if total > 0 else 0
        self.progress_bar.set_fraction(fraction)
        self.progress_bar.set_text(f"{current} / {total}")

    def generate_pitch_shifted_sfz(self, output_dir):
        GLib.idle_add(self.spinner.start)
        GLib.idle_add(self.process_button.set_sensitive, False)
        GLib.idle_add(self.progress_row.set_visible, True)
        GLib.idle_add(self._update_progress, 0, 1)

        def progress_callback(current, total):
            GLib.idle_add(self._update_progress, current, total)

        sfz_path, num_successful, num_total = self.generate_pitch_shifted_instrument_func(
            output_dir,
            self.audio_file_path,
            int(self.pitch_keycenter.get_value()),
            int(self.low_key_spin.get_value()),
            int(self.high_key_spin.get_value()),
            self.sample_rate,
            self.get_extra_sfz_definitions(),
            progress_callback,
        )

        GLib.idle_add(self.show_generation_complete_dialog, sfz_path, num_successful, num_total)
        if sfz_path:
            self.generated_instrument_path = sfz_path
            GLib.idle_add(self.update_sfz_output)

        GLib.idle_add(self.spinner.stop)
        GLib.idle_add(self.process_button.set_sensitive, True)
        GLib.idle_add(self.progress_row.set_visible, False)
