import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")

from gi.repository import Gtk, Adw, Gdk, GLib
import numpy as np
import soundfile as sf
import os
from pathlib import Path
import threading
import sounddevice as sd
import re

from sfz_generator.widgets.waveform_widget import WaveformWidget


class SFZGenerator(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_title("SFZ Generator")
        self.set_default_size(1200, 800)

        self.sfz_file = None
        # Initialize variables
        self.audio_data = None
        self.sample_rate = None
        self.audio_file_path = None
        self.loop_start = None
        self.loop_end = None
        self.zoom_level = 1.0
        self.pan_offset = 0
        self.is_playing = False
        self.playback_thread = None
        self.stop_playback = False
        self.current_sfz_path = None

        # Create main box
        self.main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.set_content(self.main_box)

        # Add EventControllerKey
        self.key_controller = Gtk.EventControllerKey.new()
        self.key_controller.connect("key-pressed", self.on_key_press)
        self.add_controller(self.key_controller)
        # Create header bar
        self.header_bar = Adw.HeaderBar()
        self.main_box.append(self.header_bar)

        # Add open file buttons
        self.open_button = Gtk.Button(label="Open Audio")
        self.open_button.connect("clicked", self.on_open_file)
        self.header_bar.pack_start(self.open_button)

        self.load_sfz_button = Gtk.Button(label="Load SFZ")
        self.load_sfz_button.connect("clicked", self.on_load_sfz)
        self.header_bar.pack_start(self.load_sfz_button)

        self.save_sfz_button = Gtk.Button(label="Save SFZ")
        self.save_sfz_button.connect("clicked", self.on_save_sfz)
        self.header_bar.pack_start(self.save_sfz_button)

        # Add download button
        self.download_button = Gtk.Button(label="Download SFZ")
        self.download_button.set_sensitive(False)
        self.download_button.connect("clicked", self.on_download_sfz)
        self.header_bar.pack_end(self.download_button)

        # Create main content area
        self.content_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.content_box.set_margin_top(10)
        self.content_box.set_margin_bottom(10)
        self.content_box.set_margin_start(10)
        self.content_box.set_margin_end(10)
        self.main_box.append(self.content_box)

        # Left panel - Controls
        self.left_panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.left_panel.set_size_request(350, -1)
        self.content_box.append(self.left_panel)

        # Create controls
        self.create_controls()

        # Right panel - Waveform and SFZ output
        self.right_panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.content_box.append(self.right_panel)

        # Create waveform display
        self.create_waveform_display()

        # Create SFZ output area
        self.create_sfz_output()

        # Update SFZ output initially
        self.update_sfz_output()

    def on_key_press(self, controller, keyval, keycode, state):
        """Toggles play when SPACE is pressed."""
        if keyval == Gdk.KEY_space:
            if self.is_playing:
                self.on_stop_clicked(None)
            else:
                self.on_play_clicked(None)
            return True  # Event has been handled
        return False  # Event has not been handled

    def create_controls(self):
        # File info group
        file_group = Adw.PreferencesGroup()
        file_group.set_title("File Information")
        self.left_panel.append(file_group)

        self.file_label = Gtk.Label(label="No file loaded")
        self.file_label.set_halign(Gtk.Align.START)
        file_row = Adw.ActionRow()
        file_row.set_title("Audio File")
        file_row.add_suffix(self.file_label)
        file_group.add(file_row)

        self.sfz_label = Gtk.Label(label="No SFZ loaded")
        self.sfz_label.set_halign(Gtk.Align.START)
        sfz_row = Adw.ActionRow()
        sfz_row.set_title("SFZ File")
        sfz_row.add_suffix(self.sfz_label)
        file_group.add(sfz_row)

        # Playback controls
        playback_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        playback_box.set_margin_top(5)
        playback_box.set_margin_bottom(5)

        self.play_button = Gtk.Button(label="▶ Play")
        self.play_button.set_sensitive(False)
        self.play_button.connect("clicked", self.on_play_clicked)
        playback_box.append(self.play_button)

        self.stop_button = Gtk.Button(label="■ Stop")
        self.stop_button.set_sensitive(False)
        self.stop_button.connect("clicked", self.on_stop_clicked)
        playback_box.append(self.stop_button)

        self.loop_playback_check = Gtk.CheckButton(label="Loop Playback")
        self.loop_playback_check.set_sensitive(False)
        playback_box.append(self.loop_playback_check)

        file_group.add(Gtk.Separator())
        playback_row = Adw.ActionRow()
        playback_row.set_child(playback_box)
        file_group.add(playback_row)

        # Loop mode group
        loop_group = Adw.PreferencesGroup()
        loop_group.set_title("Loop Settings")
        self.left_panel.append(loop_group)

        # Loop mode dropdown - use StringList for GTK4
        self.loop_strings = Gtk.StringList.new(
            ["no_loop", "one_shot", "loop_sustain", "loop_continuous"]
        )

        self.loop_mode = Gtk.DropDown(model=self.loop_strings)
        self.loop_mode.set_selected(0)
        self.loop_mode.connect("notify::selected", self.on_loop_mode_changed)

        loop_row = Adw.ActionRow()
        loop_row.set_title("Loop Mode")
        loop_row.add_suffix(self.loop_mode)
        loop_group.add(loop_row)

        # Loop markers (initially insensitive)
        self.loop_start_spin = Gtk.SpinButton.new_with_range(0, 100, 1)
        self.loop_start_spin.set_sensitive(False)
        self.loop_start_spin.connect("value-changed", self.on_loop_marker_changed)

        loop_start_row = Adw.ActionRow()
        loop_start_row.set_title("Loop Start (samples)")
        loop_start_row.add_suffix(self.loop_start_spin)
        loop_group.add(loop_start_row)

        self.loop_end_spin = Gtk.SpinButton.new_with_range(0, 100, 1)
        self.loop_end_spin.set_sensitive(False)
        self.loop_end_spin.connect("value-changed", self.on_loop_marker_changed)

        loop_end_row = Adw.ActionRow()
        loop_end_row.set_title("Loop End (samples)")
        loop_end_row.add_suffix(self.loop_end_spin)
        loop_group.add(loop_end_row)

        # ADSR group
        adsr_group = Adw.PreferencesGroup()
        adsr_group.set_title("Envelope (ADSR)")
        self.left_panel.append(adsr_group)

        # Attack
        self.attack_switch = Gtk.Switch()
        self.attack_switch.set_active(False)
        self.attack_switch.connect("notify::active", self.update_sfz_output)

        self.attack_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0, 5, 0.01
        )
        self.attack_scale.set_value(0.01)
        self.attack_scale.set_sensitive(False)
        self.attack_scale.set_draw_value(True)
        self.attack_scale.set_value_pos(Gtk.PositionType.RIGHT)
        self.attack_scale.connect("value-changed", self.update_sfz_output)

        attack_row = Adw.ActionRow()
        attack_row.set_title("Attack")
        attack_row.add_suffix(self.attack_switch)
        attack_row.add_suffix(self.attack_scale)
        adsr_group.add(attack_row)

        self.attack_switch.connect(
            "notify::active",
            lambda s, p: self.attack_scale.set_sensitive(s.get_active()),
        )

        # Sustain
        self.sustain_switch = Gtk.Switch()
        self.sustain_switch.set_active(False)
        self.sustain_switch.connect("notify::active", self.update_sfz_output)

        self.sustain_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0, 1, 0.01
        )
        self.sustain_scale.set_value(0.7)
        self.sustain_scale.set_sensitive(False)
        self.sustain_scale.set_draw_value(True)
        self.sustain_scale.set_value_pos(Gtk.PositionType.RIGHT)
        self.sustain_scale.connect("value-changed", self.update_sfz_output)

        sustain_row = Adw.ActionRow()
        sustain_row.set_title("Sustain")
        sustain_row.add_suffix(self.sustain_switch)
        sustain_row.add_suffix(self.sustain_scale)
        adsr_group.add(sustain_row)

        self.sustain_switch.connect(
            "notify::active",
            lambda s, p: self.sustain_scale.set_sensitive(s.get_active()),
        )

        # Release
        self.release_switch = Gtk.Switch()
        self.release_switch.set_active(False)
        self.release_switch.connect("notify::active", self.update_sfz_output)

        self.release_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0, 10, 0.01
        )
        self.release_scale.set_value(0.1)
        self.release_scale.set_sensitive(False)
        self.release_scale.set_draw_value(True)
        self.release_scale.set_value_pos(Gtk.PositionType.RIGHT)
        self.release_scale.connect("value-changed", self.update_sfz_output)

        release_row = Adw.ActionRow()
        release_row.set_title("Release")
        release_row.add_suffix(self.release_switch)
        release_row.add_suffix(self.release_scale)
        adsr_group.add(release_row)

        self.release_switch.connect(
            "notify::active",
            lambda s, p: self.release_scale.set_sensitive(s.get_active()),
        )

        # Pitch group
        pitch_group = Adw.PreferencesGroup()
        pitch_group.set_title("Pitch Settings")
        self.left_panel.append(pitch_group)

        # Pitch keycenter
        self.pitch_keycenter = Gtk.SpinButton.new_with_range(0, 127, 1)
        self.pitch_keycenter.set_value(60)  # Middle C
        self.pitch_keycenter.connect("value-changed", self.update_sfz_output)

        pitch_row = Adw.ActionRow()
        pitch_row.set_title("Pitch Keycenter (MIDI note)")
        pitch_row.add_suffix(self.pitch_keycenter)
        pitch_group.add(pitch_row)

    def create_waveform_display(self):
        # Create waveform frame
        waveform_frame = Gtk.Frame()
        waveform_frame.set_label("Waveform")

        waveform_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        waveform_frame.set_child(waveform_box)

        # Add zoom controls
        zoom_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        zoom_box.set_margin_top(5)
        zoom_box.set_margin_bottom(5)
        zoom_box.set_margin_start(5)
        zoom_box.set_margin_end(5)

        zoom_in_btn = Gtk.Button(label="Zoom In")
        zoom_in_btn.connect("clicked", self.on_zoom_in)
        zoom_box.append(zoom_in_btn)

        zoom_out_btn = Gtk.Button(label="Zoom Out")
        zoom_out_btn.connect("clicked", self.on_zoom_out)
        zoom_box.append(zoom_out_btn)

        reset_btn = Gtk.Button(label="Reset View")
        reset_btn.connect("clicked", self.on_reset_view)
        zoom_box.append(reset_btn)

        waveform_box.append(zoom_box)

        # Create custom waveform widget
        self.waveform_widget = WaveformWidget()
        waveform_box.append(self.waveform_widget)

        # Connect signals
        self.waveform_widget.connect("loop-start-changed", self.on_loop_start_changed)
        self.waveform_widget.connect("loop-end-changed", self.on_loop_end_changed)
        self.waveform_widget.connect("zoom-changed", self.on_zoom_changed)
        self.waveform_widget.connect("pan-changed", self.on_pan_changed)

        self.right_panel.append(waveform_frame)

    def create_sfz_output(self):
        # Create SFZ output frame
        sfz_frame = Gtk.Frame()
        sfz_frame.set_label("SFZ Output")

        # Create scrolled window for text view
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_min_content_height(200)

        # Create text view
        self.sfz_buffer = Gtk.TextBuffer()
        self.sfz_view = Gtk.TextView(buffer=self.sfz_buffer)
        self.sfz_view.set_editable(False)
        self.sfz_view.set_monospace(True)

        scrolled.set_child(self.sfz_view)
        sfz_frame.set_child(scrolled)

        self.right_panel.append(sfz_frame)

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
                        if not sfz_path.endswith(".sfz"):
                            sfz_path += ".sfz"
                        self.sfz_file = sfz_path
                        self.save_sfz_file(sfz_path)
                dialog.destroy()

            dialog.connect("response", on_response)
            dialog.show()
        else:
            self.save_sfz_file(self.sfz_file)

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
        try:
            self.current_sfz_path = sfz_path
            self.sfz_label.set_text(os.path.basename(sfz_path))

            # Read SFZ file
            with open(sfz_path, "r") as f:
                content = f.read()

            # Parse SFZ content
            sfz_data = self.parse_sfz_content(content, os.path.dirname(sfz_path))

            # Update GUI controls
            self.update_controls_from_sfz(sfz_data)

            # Load audio file if specified
            if "sample" in sfz_data:
                audio_path = sfz_data["sample"]
                if os.path.isabs(audio_path):
                    self.audio_file_path = audio_path
                else:
                    # Relative path - combine with SFZ directory
                    self.audio_file_path = os.path.join(
                        os.path.dirname(sfz_path), audio_path
                    )

                if os.path.exists(self.audio_file_path):
                    self.load_audio_file()
                else:
                    # Show warning if audio file not found
                    dialog = Adw.MessageDialog.new(self, "Warning", "Audio file not found")
                    dialog.set_body(f"The referenced audio file '{audio_path}' was not found at:\n{self.audio_file_path}\n\nYou can load it manually using 'Open Audio'.")
                    dialog.add_response("ok", "OK")
                    dialog.set_modal(True)
                    dialog.present()

            self.download_button.set_sensitive(True)

        except Exception as e:
            dialog = Adw.MessageDialog.new(self, "Error", "Failed to load SFZ file")
            dialog.set_body(f"Error: {str(e)}")
            dialog.add_response("ok", "OK")
            dialog.set_modal(True)
            dialog.present()

    def parse_sfz_content(self, content, sfz_dir):
        # Initialize data dictionary
        sfz_data = {}

        # Remove comments and split into lines
        lines = []
        for line in content.split("\n"):
            # Remove comments
            line = re.sub(r"//.*$", "", line)
            line = re.sub(r"#.*$", "", line)
            line = line.strip()
            if line:
                lines.append(line)

        # Parse opcodes
        current_section = None
        for line in lines:
            line = line.strip()

            # Check for section headers
            if line.startswith("<") and line.endswith(">"):
                current_section = line[1:-1]
                continue

            # Parse opcode=value pairs
            if "=" in line:
                opcode, value = line.split("=", 1)
                opcode = opcode.strip().lower()
                value = value.strip()

                # Store only the first region's opcodes
                if current_section == "region":
                    sfz_data[opcode] = value

        return sfz_data

    def update_controls_from_sfz(self, sfz_data):
        # Block signals to prevent unwanted updates
        self.loop_mode.handler_block_by_func(self.on_loop_mode_changed)
        self.loop_start_spin.handler_block_by_func(self.on_loop_marker_changed)
        self.loop_end_spin.handler_block_by_func(self.on_loop_marker_changed)
        self.pitch_keycenter.handler_block_by_func(self.update_sfz_output)

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

            # Loop points
            if "loop_start" in sfz_data:
                self.loop_start = int(sfz_data["loop_start"])
                self.loop_start_spin.set_value(self.loop_start)

            if "loop_end" in sfz_data:
                self.loop_end = int(sfz_data["loop_end"])
                self.loop_end_spin.set_value(self.loop_end)

            # ADSR
            if "ampeg_attack" in sfz_data:
                self.attack_switch.set_active(True)
                self.attack_scale.set_value(float(sfz_data["ampeg_attack"]))
            else:
                self.attack_switch.set_active(False)

            if "ampeg_sustain" in sfz_data:
                self.sustain_switch.set_active(True)
                self.sustain_scale.set_value(float(sfz_data["ampeg_sustain"]))
            else:
                self.sustain_switch.set_active(False)

            if "ampeg_release" in sfz_data:
                self.release_switch.set_active(True)
                self.release_scale.set_value(float(sfz_data["ampeg_release"]))
            else:
                self.release_switch.set_active(False)

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

        # Update SFZ output
        self.update_sfz_output()

    def load_audio_file(self):
        try:
            self.audio_data, self.sample_rate = sf.read(self.audio_file_path)

            # Convert to mono if stereo
            if len(self.audio_data.shape) > 1:
                self.audio_data = np.mean(self.audio_data, axis=1)

            # Normalize to 16-bit integer range for playback
            self.audio_data_int16 = (self.audio_data * 32767).astype(np.int16)

            self.file_label.set_text(os.path.basename(self.audio_file_path))

            # Update waveform widget
            self.waveform_widget.set_audio_data(self.audio_data, self.sample_rate)

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

        except Exception as e:
            dialog = Adw.MessageDialog.new(self, "Error", "Failed to load audio file")
            dialog.set_body(f"Error: {str(e)}")
            dialog.add_response("ok", "OK")
            dialog.set_modal(True)
            dialog.present()

    def on_play_clicked(self, button):
        if not self.is_playing:
            self.is_playing = True
            self.stop_playback = False
            self.play_button.set_sensitive(False)
            self.stop_button.set_sensitive(True)

            # Update waveform widget
            self.waveform_widget.set_playback_state(
                True, self.loop_playback_check.get_active()
            )

            # Start playback in a separate thread
            self.playback_thread = threading.Thread(target=self.play_audio)
            self.playback_thread.daemon = True
            self.playback_thread.start()

    def on_stop_clicked(self, button):
        self.stop_playback = True
        self.is_playing = False
        self.play_button.set_sensitive(True)
        self.stop_button.set_sensitive(False)

        # Update waveform widget
        self.waveform_widget.set_playback_state(False)

    def play_audio(self):
        if self.audio_data_int16 is None:
            return

        audio_data = self.audio_data_int16
        channels = 1 if audio_data.ndim == 1 else audio_data.shape[1]
        frames_per_chunk = max(self.sample_rate // 20, 1024)

        def as_frames(buffer):
            return buffer.reshape(-1, 1) if channels == 1 else buffer

        try:
            with sd.OutputStream( 
                samplerate=self.sample_rate, channels=channels, dtype=audio_data.dtype
            ) as stream:
                if (
                    self.loop_playback_check.get_active()
                    and self.loop_start is not None
                    and self.loop_end is not None
                    and self.loop_end > self.loop_start
                ):
                    loop_segment = audio_data[self.loop_start : self.loop_end]
                    if loop_segment.size == 0:
                        return
                    loop_frames = as_frames(loop_segment)
                    while not self.stop_playback:
                        stream.write(loop_frames)
                        if self.stop_playback:
                            stream.abort()
                            break
                else:
                    frames = as_frames(audio_data)
                    total_frames = frames.shape[0]
                    current_frame = 0
                    while current_frame < total_frames:
                        if self.stop_playback:
                            stream.abort()
                            break
                        chunk_end = min(current_frame + frames_per_chunk, total_frames)
                        stream.write(frames[current_frame:chunk_end])
                        current_frame = chunk_end
        except Exception as e:
            GLib.idle_add(self.show_playback_error, str(e))
        finally:
            GLib.idle_add(self.playback_finished)

    def playback_finished(self):
        self.is_playing = False
        self.play_button.set_sensitive(True)
        self.stop_button.set_sensitive(False)

        # Update waveform widget
        self.waveform_widget.set_playback_state(False)

    def show_playback_error(self, error_msg):
        dialog = Adw.MessageDialog.new(self, "Playback Error", "Failed to play audio")
        dialog.set_body(f"Error: {error_msg}")
        dialog.add_response("ok", "OK")
        dialog.set_modal(True)
        dialog.present()

    def on_zoom_in(self, button):
        if self.audio_data is not None:
            self.zoom_level = min(self.zoom_level * 2, 100)
            self.waveform_widget.set_zoom(self.zoom_level)

    def on_zoom_out(self, button):
        if self.audio_data is not None:
            self.zoom_level = max(self.zoom_level / 2, 1)
            self.waveform_widget.set_zoom(self.zoom_level)

    def on_reset_view(self, button):
        if self.audio_data is not None:
            self.zoom_level = 1.0
            self.pan_offset = 0
            self.waveform_widget.set_zoom(self.zoom_level)
            self.waveform_widget.set_pan(self.pan_offset)

    def on_zoom_changed(self, widget, zoom_level):
        self.zoom_level = zoom_level

    def on_pan_changed(self, widget, pan_offset):
        self.pan_offset = pan_offset

    def on_loop_start_changed(self, widget, loop_start):
        self.loop_start = loop_start
        self.loop_start_spin.set_value(loop_start)
        self.update_sfz_output()

    def on_loop_end_changed(self, widget, loop_end):
        self.loop_end = loop_end
        self.loop_end_spin.set_value(loop_end)
        self.update_sfz_output()

    def on_loop_mode_changed(self, dropdown, param):
        selected = self.loop_mode.get_selected()
        loop_mode = self.loop_strings.get_string(selected)

        # Enable/disable loop markers
        if loop_mode in ["loop_sustain", "loop_continuous"]:
            self.loop_start_spin.set_sensitive(True)
            self.loop_end_spin.set_sensitive(True)
        else:
            self.loop_start_spin.set_sensitive(False)
            self.loop_end_spin.set_sensitive(False)

        self.update_sfz_output()

    def on_loop_marker_changed(self, spin):
        self.loop_start = int(self.loop_start_spin.get_value())
        self.loop_end = int(self.loop_end_spin.get_value())
        self.waveform_widget.set_loop_points(self.loop_start, self.loop_end)
        self.update_sfz_output()

    def update_sfz_output(self, *args):
        if self.audio_file_path is None:
            self.sfz_buffer.set_text("// No audio file loaded")
            return

        # Generate SFZ content
        sfz_content = []
        sfz_content.append("<group>")
        sfz_content.append("")
        sfz_content.append("<region>")
        sfz_content.append(f"sample={os.path.basename(self.audio_file_path)}")

        sfz_content.append("lokey=0")
        sfz_content.append("hikey=127")

        # Add loop settings
        selected = self.loop_mode.get_selected()
        loop_mode = self.loop_strings.get_string(selected)

        if loop_mode == "no_loop":
            sfz_content.append("loop_mode=no_loop")
        elif loop_mode == "one_shot":
            sfz_content.append("loop_mode=one_shot")
        elif loop_mode == "loop_sustain":
            sfz_content.append("loop_mode=loop_sustain")
            sfz_content.append(f"loop_start={int(self.loop_start)}")
            sfz_content.append(f"loop_end={int(self.loop_end)}")
        elif loop_mode == "loop_continuous":
            sfz_content.append("loop_mode=loop_continuous")
            sfz_content.append(f"loop_start={int(self.loop_start)}")
            sfz_content.append(f"loop_end={int(self.loop_end)}")

        # Add ADSR
        if self.attack_switch.get_active():
            sfz_content.append(f"ampeg_attack={self.attack_scale.get_value():.3f}")
        if self.sustain_switch.get_active():
            sfz_content.append(f"ampeg_sustain={int(self.sustain_scale.get_value()*100)}")
        if self.release_switch.get_active():
            sfz_content.append(f"ampeg_release={self.release_scale.get_value():.3f}")

        # Add pitch keycenter
        sfz_content.append(f"pitch_keycenter={int(self.pitch_keycenter.get_value())}")

        # Set content
        self.sfz_buffer.set_text("\n".join(sfz_content))

    def on_download_sfz(self, button):
        if self.audio_file_path is None:
            return

        dialog = Gtk.FileChooserNative.new(
            "Save SFZ File",
            self,
            Gtk.FileChooserAction.SAVE,
            "_Save",
            "_Cancel",
        )

        # Set default filename
        if self.current_sfz_path:
            # Use the loaded SFZ filename as default
            dialog.set_current_name(os.path.basename(self.current_sfz_path))
        else:
            # Use audio filename as base
            base_name = Path(self.audio_file_path).stem
            dialog.set_current_name(f"{base_name}.sfz")
        
        dialog.set_current_folder(Gtk.File.new_for_path(os.path.dirname(self.current_sfz_path or self.audio_file_path)))


        # Add filter
        filter_sfz = Gtk.FileFilter()
        filter_sfz.set_name("SFZ files")
        filter_sfz.add_pattern("*.sfz")
        dialog.add_filter(filter_sfz)

        def on_save_response(dialog, response):
            if response == Gtk.ResponseType.ACCEPT:
                file = dialog.get_file()
                if file:
                    sfz_path = file.get_path()

                    # Get SFZ content
                    start_iter = self.sfz_buffer.get_start_iter()
                    end_iter = self.sfz_buffer.get_end_iter()
                    sfz_content = self.sfz_buffer.get_text(start_iter, end_iter, False)

                    # Save file
                    with open(sfz_path, "w") as f:
                        f.write(sfz_content)

            dialog.destroy()

        dialog.connect("response", on_save_response)
        dialog.show()
