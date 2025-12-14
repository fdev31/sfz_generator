import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Adw
from pathlib import Path
import os

class FileIOMixin:
    def on_open_file(self, button):
        dialog = Gtk.FileChooserNative.new(
            "Open Audio File",
            self,
            Gtk.FileChooserAction.OPEN,
            "_Open",
            "_Cancel",
        )

        # Add audio file filters using new API
        filter_wav = Gtk.FileFilter()
        filter_wav.set_name("WAV files")
        filter_wav.add_pattern("*.wav")
        dialog.add_filter(filter_wav)

        filter_aiff = Gtk.FileFilter()
        filter_aiff.set_name("AIFF files")
        filter_aiff.add_pattern("*.aiff")
        filter_aiff.add_pattern("*.aif")
        dialog.add_filter(filter_aiff)

        filter_flac = Gtk.FileFilter()
        filter_flac.set_name("FLAC files")
        filter_flac.add_pattern("*.flac")
        dialog.add_filter(filter_flac)

        filter_all = Gtk.FileFilter()
        filter_all.set_name("All audio files")
        filter_all.add_pattern("*.wav")
        filter_all.add_pattern("*.aiff")
        filter_all.add_pattern("*.aif")
        filter_all.add_pattern("*.flac")
        dialog.add_filter(filter_all)

        def on_response(dialog, response):
            if response == Gtk.ResponseType.ACCEPT:
                file = dialog.get_file()
                if file:
                    self.audio_file_path = file.get_path()
                    self.load_audio_file()
            dialog.destroy()

        dialog.connect("response", on_response)
        dialog.show()

    def on_save_sfz(self, button):
        if self.sfz_file is None:
            dialog = Gtk.FileChooserNative.new(
                "Save SFZ File",
                self,
                Gtk.FileChooserAction.SAVE,
                "_Save",
                "_Cancel",
            )
            if self.audio_file_path:
                dialog.set_current_name(Path(self.audio_file_path).stem + ".sfz")

            filter_sfz = Gtk.FileFilter()
            filter_sfz.set_name("SFZ files")
            filter_sfz.add_pattern("*.sfz")
            dialog.add_filter(filter_sfz)

            dialog.connect("response", self.on_save_sfz_response)
            dialog.show()
        else:
            self.save_sfz_file(self.sfz_file)
            
    def on_save_sfz_response(self, dialog, response):
        if response == Gtk.ResponseType.ACCEPT:
            file = dialog.get_file()
            if file:
                sfz_path = file.get_path()
                if not sfz_path.endswith(".sfz"):
                    sfz_path += ".sfz"
                self.sfz_file = sfz_path
                self.save_sfz_file(sfz_path)
        dialog.destroy()

    def on_load_sfz(self, button):
        dialog = Gtk.FileChooserNative.new(
            "Load SFZ File",
            self,
            Gtk.FileChooserAction.OPEN,
            "_Load",
            "_Cancel",
        )

        # Add SFZ filter
        filter_sfz = Gtk.FileFilter()
        filter_sfz.set_name("SFZ files")
        filter_sfz.add_pattern("*.sfz")
        dialog.add_filter(filter_sfz)

        def on_response(dialog, response):
            if response == Gtk.ResponseType.ACCEPT:
                file = dialog.get_file()
                if file:
                    sfz_path = file.get_path()
                    self.sfz_file = sfz_path
                    self.loop_start = None
                    self.loop_end = None
                    self.parse_sfz_file(sfz_path)
            dialog.destroy()

        dialog.connect("response", on_response)
        dialog.show()

    def save_sfz_file(self, sfz_path):
        try:
            sfz_content = self.sfz_buffer.get_text(
                self.sfz_buffer.get_start_iter(),
                self.sfz_buffer.get_end_iter(),
                True,
            )

            with open(sfz_path, "w") as f:
                f.write(sfz_content)

            dialog = Adw.MessageDialog.new(self, "Success", "SFZ file saved")
            dialog.set_body(f"SFZ file saved successfully to:\n{sfz_path}")
            dialog.add_response("ok", "OK")
            dialog.set_modal(True)
            dialog.present()


        except Exception as e:
            dialog = Adw.MessageDialog.new(self, "Error", "Failed to save SFZ file")
            dialog.set_body(f"Error: {str(e)}")
            dialog.add_response("ok", "OK")
            dialog.set_modal(True)
            dialog.present()

    def parse_sfz_file(self, sfz_path):
        sfz_data, sample_path, error = self.parse_sfz_file_func(sfz_path)

        if error:
            dialog = Adw.MessageDialog.new(self, "Error", "Failed to load SFZ file")
            dialog.set_body(f"Error: {error}")
            dialog.add_response("ok", "OK")
            dialog.set_modal(True)
            dialog.present()
            return

        self.current_sfz_path = sfz_path
        self.sfz_label.set_text(os.path.basename(sfz_path))
        
        if sample_path:
            if os.path.exists(sample_path):
                self.audio_file_path = sample_path
                self.load_audio_file()
            else:
                dialog = Adw.MessageDialog.new(self, "Warning", "Audio file not found")
                dialog.set_body(f"The referenced audio file was not found at:\n{sample_path}\n\nYou can load it manually using 'Open Audio'.")
                dialog.add_response("ok", "OK")
                dialog.set_modal(True)
                dialog.present()
        
        self.update_controls_from_sfz(sfz_data)

    def update_controls_from_sfz(self, sfz_data):
        # Block signals to prevent unwanted updates
        self.loop_mode.handler_block_by_func(self.on_loop_mode_changed)
        self.loop_start_spin.handler_block_by_func(self.on_loop_marker_changed)
        self.loop_end_spin.handler_block_by_func(self.on_loop_marker_changed)
        self.pitch_keycenter.handler_block_by_func(self.update_sfz_output)
        self.loop_crossfade_spin_row.get_adjustment().handler_block_by_func(self.update_sfz_output)
        self.delay_spin_row.get_adjustment().handler_block_by_func(self.update_sfz_output)
        self.attack_spin_row.get_adjustment().handler_block_by_func(self.update_sfz_output)
        self.hold_spin_row.get_adjustment().handler_block_by_func(self.update_sfz_output)
        self.decay_spin_row.get_adjustment().handler_block_by_func(self.update_sfz_output)
        self.sustain_spin_row.get_adjustment().handler_block_by_func(self.update_sfz_output)
        self.release_spin_row.get_adjustment().handler_block_by_func(self.update_sfz_output)
        self.trigger_mode.handler_block_by_func(self.on_trigger_mode_changed)

        try:
            # Loop mode
            if "loop_mode" in sfz_data:
                loop_mode = sfz_data["loop_mode"]
                if loop_mode == "no_loop":
                    self.loop_mode.set_selected(0)
                elif loop_mode == "one_shot":
                    self.loop_mode.set_selected(1)
                elif loop_mode == "loop_sustain":
                    self.loop_mode.set_selected(2)
                elif loop_mode == "loop_continuous":
                    self.loop_mode.set_selected(3)

            # Trigger mode
            if "trigger" in sfz_data:
                trigger_value = sfz_data["trigger"]
                if trigger_value == "attack":
                    self.trigger_mode.set_selected(0)
                elif trigger_value == "release":
                    self.trigger_mode.set_selected(1)
                elif trigger_value == "first":
                    self.trigger_mode.set_selected(2)
                elif trigger_value == "legato":
                    self.trigger_mode.set_selected(3)
                elif trigger_value == "release_key":
                    self.trigger_mode.set_selected(4)

            # Loop points
            if "loop_start" in sfz_data:
                self.loop_start = int(sfz_data["loop_start"])
                self.loop_start_spin.set_value(self.loop_start)

            if "loop_end" in sfz_data:
                self.loop_end = int(sfz_data["loop_end"])
                self.loop_end_spin.set_value(self.loop_end)

            if self.loop_start is not None and self.loop_end is not None:
                self.waveform_widget.set_loop_points(self.loop_start, self.loop_end)

            if "loop_crossfade" in sfz_data:
                self.loop_crossfade_spin_row.set_value(float(sfz_data["loop_crossfade"]))

            # ADSR
            if "ampeg_delay" in sfz_data:
                self.delay_spin_row.set_value(float(sfz_data["ampeg_delay"]))

            if "ampeg_attack" in sfz_data:
                self.attack_spin_row.set_value(float(sfz_data["ampeg_attack"]))

            if "ampeg_hold" in sfz_data:
                self.hold_spin_row.set_value(float(sfz_data["ampeg_hold"]))

            if "ampeg_decay" in sfz_data:
                self.decay_spin_row.set_value(float(sfz_data["ampeg_decay"]))

            if "ampeg_sustain" in sfz_data:
                self.sustain_spin_row.set_value(float(sfz_data["ampeg_sustain"]))

            if "ampeg_release" in sfz_data:
                self.release_spin_row.set_value(float(sfz_data["ampeg_release"]))

            # Pitch keycenter
            if "pitch_keycenter" in sfz_data:
                self.pitch_keycenter.set_value(int(sfz_data["pitch_keycenter"]))

            # Update loop mode sensitivity
            self.on_loop_mode_changed(self.loop_mode, None)

        finally:
            # Unblock signals
            self.loop_mode.handler_unblock_by_func(self.on_loop_mode_changed)
            self.loop_start_spin.handler_unblock_by_func(self.on_loop_marker_changed)
            self.loop_end_spin.handler_unblock_by_func(self.on_loop_marker_changed)
            self.pitch_keycenter.handler_unblock_by_func(self.update_sfz_output)
            self.loop_crossfade_spin_row.get_adjustment().handler_unblock_by_func(self.update_sfz_output)
            self.delay_spin_row.get_adjustment().handler_unblock_by_func(self.update_sfz_output)
            self.attack_spin_row.get_adjustment().handler_unblock_by_func(self.update_sfz_output)
            self.hold_spin_row.get_adjustment().handler_unblock_by_func(self.update_sfz_output)
            self.decay_spin_row.get_adjustment().handler_unblock_by_func(self.update_sfz_output)
            self.sustain_spin_row.get_adjustment().handler_unblock_by_func(self.update_sfz_output)
            self.release_spin_row.get_adjustment().handler_unblock_by_func(self.update_sfz_output)
            self.trigger_mode.handler_unblock_by_func(self.on_trigger_mode_changed)


        # Update SFZ output
        self.update_sfz_output()

    def load_audio_file(self):
        audio_data, audio_data_int16, sample_rate, error = self.load_audio_func(self.audio_file_path)

        if error:
            dialog = Adw.MessageDialog.new(self, "Error", "Failed to load audio file")
            dialog.set_body(f"Error: {error}")
            dialog.add_response("ok", "OK")
            dialog.set_modal(True)
            dialog.present()
            return

        self.audio_data = audio_data
        self.audio_data_int16 = audio_data_int16
        self.sample_rate = sample_rate

        self.file_label.set_text(os.path.basename(self.audio_file_path))

        # Update waveform widget
        self.waveform_widget.set_audio_data(self.audio_data, self.sample_rate)
        if self.zero_crossing_check.get_active():
            self.waveform_widget.set_snap_to_zero_crossing(True)

        # Update loop marker ranges
        max_samples = len(self.audio_data) - 1
        self.loop_start_spin.set_range(0, max_samples)
        self.loop_end_spin.set_range(0, max_samples)

        # Set default loop points if not set
        if self.loop_start is None:
            self.loop_start = len(self.audio_data) // 4
            self.loop_start_spin.set_value(self.loop_start)
        if self.loop_end is None:
            self.loop_end = len(self.audio_data) // 2
            self.loop_end_spin.set_value(self.loop_end)

        # Update waveform widget with loop points
        self.waveform_widget.set_loop_points(self.loop_start, self.loop_end)

        # Enable playback controls
        self.play_button.set_sensitive(True)
        self.loop_playback_check.set_sensitive(True)

        self.update_sfz_output()
