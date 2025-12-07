import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")

from gi.repository import Gtk, Adw, Gdk, GLib, GObject
import numpy as np
import soundfile as sf
import os
from pathlib import Path
import threading
import sounddevice as sd
import re

from sfz_generator.widgets.waveform_widget import WaveformWidget
import librosa
from concurrent.futures import ThreadPoolExecutor, as_completed

NOTES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

def midi_to_name(midi):
    octave = (midi // 12) - 1
    note = NOTES[midi % 12]
    return f"{note}{octave}"

def process_midi_note(args):
    """Generate pitch-shifted sample for a single MIDI note using librosa."""
    inp, out_dir, midi, root, sr = args
    
    semitones = midi - root
    note_name = midi_to_name(midi)
    out_wav = f"{note_name}.wav"
    out_path = os.path.join(out_dir, out_wav)

    try:
        y, loaded_sr = librosa.load(inp, sr=sr)
        
        # Pitch shift
        y_shifted = librosa.effects.pitch_shift(y, sr=loaded_sr, n_steps=float(semitones))
        
        sf.write(out_path, y_shifted, loaded_sr)
        return (midi, note_name, True, None)
    except Exception as e:
        return (midi, note_name, False, str(e))


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

        # Add flap toggle button to header
        self.flap_toggle = Gtk.ToggleButton.new()
        self.flap_toggle.set_icon_name("sidebar-show-symbolic")
        self.flap_toggle.set_active(True)
        self.header_bar.pack_start(self.flap_toggle)

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

        self.spinner = Gtk.Spinner()
        self.header_bar.pack_end(self.spinner)

        # Create main content area using Adw.Flap
        self.flap = Adw.Flap()
        self.main_box.append(self.flap)

        # Bind toggle button to flap state
        self.flap_toggle.bind_property("active", self.flap, "reveal-flap", GObject.BindingFlags.BIDIRECTIONAL)
        
        # Left panel - Controls - becomes the flap
        self.left_panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.left_panel.set_size_request(350, -1)
        self.left_panel.set_margin_top(10)
        self.left_panel.set_margin_bottom(10)
        self.left_panel.set_margin_start(10)
        self.left_panel.set_margin_end(10)

        scrolled_flap = Gtk.ScrolledWindow()
        scrolled_flap.set_child(self.left_panel)
        scrolled_flap.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.flap.set_flap(scrolled_flap)

        # Create controls
        self.create_controls()

        # Right panel - Waveform and SFZ output - becomes the content
        self.right_panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.right_panel.set_margin_top(10)
        self.right_panel.set_margin_bottom(10)
        self.right_panel.set_margin_start(10)
        self.right_panel.set_margin_end(10)
        self.flap.set_content(self.right_panel)

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

        gen_group = Adw.PreferencesGroup()
        gen_group.set_title("Generation Settings")
        self.left_panel.append(gen_group)

        self.pitch_shift_check = Gtk.CheckButton(label="Enable Pitch-shifting")
        self.pitch_shift_check.set_tooltip_text("Generates a separate, pre-pitch-shifted audio file for each note.")
        self.pitch_shift_check.set_active(False)
        self.pitch_shift_check.connect("toggled", self.on_pitch_shift_toggled)

        gen_row = Adw.ActionRow()
        gen_row.set_title("Advanced Generation")
        gen_row.add_suffix(self.pitch_shift_check)
        gen_group.add(gen_row)

        # Low Key
        self.low_key_spin = Gtk.SpinButton.new_with_range(0, 127, 1)
        self.low_key_spin.set_value(24) # C1
        self.low_key_spin.set_sensitive(False)

        self.low_key_row = Adw.ActionRow()
        self.low_key_row.set_title("Low Key")
        self.low_key_row.add_suffix(self.low_key_spin)
        self.low_key_row.set_visible(False)
        gen_group.add(self.low_key_row)


        # High Key
        self.high_key_spin = Gtk.SpinButton.new_with_range(0, 127, 1)
        self.high_key_spin.set_value(84) # C6
        self.high_key_spin.set_sensitive(False)

        self.high_key_row = Adw.ActionRow()
        self.high_key_row.set_title("High Key")
        self.high_key_row.add_suffix(self.high_key_spin)
        self.high_key_row.set_visible(False)
        gen_group.add(self.high_key_row)

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
        if self.pitch_shift_check.get_active():
            if not self.audio_file_path:
                dialog = Adw.MessageDialog.new(self, "No Audio File", "Please open an audio file first.")
                dialog.add_response("ok", "OK")
                dialog.set_modal(True)
                dialog.present()
                return

            # Choose a directory to save the instrument
            dialog = Gtk.FileChooserNative.new(
                "Save Instrument Folder",
                self,
                Gtk.FileChooserAction.SELECT_FOLDER,
                "_Save",
                "_Cancel",
            )
            dialog.set_current_name(Path(self.audio_file_path).stem)


            def on_response(dialog, response):
                if response == Gtk.ResponseType.ACCEPT:
                    folder = dialog.get_file()
                    if folder:
                        output_dir = folder.get_path()
                        # Run generation in background
                        thread = threading.Thread(target=self.generate_pitch_shifted_sfz, args=(output_dir,))
                        thread.daemon = True
                        thread.start()
                dialog.destroy()

            dialog.connect("response", on_response)
            dialog.show()
        else:
            # Simple mode: save single SFZ file
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

    def on_pitch_shift_toggled(self, button):
        is_active = button.get_active()
        self.low_key_spin.set_sensitive(is_active)
        self.high_key_spin.set_sensitive(is_active)
        self.low_key_row.set_visible(is_active)
        self.high_key_row.set_visible(is_active)
        self.update_sfz_output()

    def get_extra_sfz_definitions(self):
        parts = []
        selected = self.loop_mode.get_selected()
        loop_mode = self.loop_strings.get_string(selected)

        if loop_mode != "no_loop":
            parts.append(f"loop_mode={loop_mode}")
            if loop_mode in ["loop_sustain", "loop_continuous"]:
                parts.append(f"loop_start={int(self.loop_start)}")
                parts.append(f"loop_end={int(self.loop_end)}")

        if self.attack_switch.get_active():
            parts.append(f"ampeg_attack={self.attack_scale.get_value():.3f}")
        if self.sustain_switch.get_active():
            parts.append(f"ampeg_sustain={self.sustain_scale.get_value():.3f}")
        if self.release_switch.get_active():
            parts.append(f"ampeg_release={self.release_scale.get_value():.3f}")
            
        if parts:
            return " " + " ".join(parts)
        return ""

    def show_generation_complete_dialog(self, sfz_path, num_successful, num_total):
        if num_successful == 0:
            dialog = Adw.MessageDialog.new(self, "Generation Failed", "No samples were generated successfully.")
            dialog.add_response("ok", "OK")
        else:
            dialog = Adw.MessageDialog.new(self, "Generation Complete", f"Successfully generated {num_successful}/{num_total} samples.")
            dialog.set_body(f"Instrument saved to:\n{os.path.dirname(sfz_path)}")
            dialog.add_response("ok", "OK")
        
        dialog.set_modal(True)
        dialog.present()

    def generate_pitch_shifted_sfz(self, output_dir):
        GLib.idle_add(self.spinner.start)
        GLib.idle_add(self.save_sfz_button.set_sensitive, False)
        
        try:
            inp = self.audio_file_path
            root = int(self.pitch_keycenter.get_value())
            low = int(self.low_key_spin.get_value())
            high = int(self.high_key_spin.get_value())
            sr = self.sample_rate
            
            samples_dir_name = "samples"
            samples_dir_path = os.path.join(output_dir, samples_dir_name)
            os.makedirs(samples_dir_path, exist_ok=True)

            tasks = [(inp, samples_dir_path, midi, root, sr) for midi in range(low, high + 1)]
            
            results = []
            num_total = len(tasks)
            with ThreadPoolExecutor(max_workers=os.cpu_count()) as executor:
                futures = {executor.submit(process_midi_note, task): task for task in tasks}
                
                for future in as_completed(futures):
                    midi, note_name, success, error = future.result()
                    if not success:
                        print(f"Failed to generate {note_name}: {error}")
                    results.append((midi, note_name, success))

            successful_notes = [(midi, note_name) for midi, note_name, success in sorted(results) if success]
            
            if not successful_notes:
                GLib.idle_add(self.show_generation_complete_dialog, None, 0, num_total)
                return

            sfz_lines = ["<group>"]
            extra_definitions = self.get_extra_sfz_definitions()

            for midi, note_name in successful_notes:
                out_wav = f"{note_name}.wav"
                sample_path = os.path.join(samples_dir_name, out_wav)
                sfz_lines.append(
                    f"<region> sample={sample_path} key={midi} pitch_keycenter={midi}{extra_definitions}"
                )
            
            sfz_content = "\n".join(sfz_lines) + "\n"
            
            sfz_path = os.path.join(output_dir, "instrument.sfz")
            with open(sfz_path, "w") as f:
                f.write(sfz_content)
            
            GLib.idle_add(self.show_generation_complete_dialog, sfz_path, len(successful_notes), num_total)

        except Exception as e:
            print(f"Error during pitch-shifted generation: {e}")
        finally:
            GLib.idle_add(self.spinner.stop)
            GLib.idle_add(self.save_sfz_button.set_sensitive, True)

    def update_sfz_output(self, *args):
        if self.pitch_shift_check.get_active():
            self.sfz_buffer.set_text(
                "// Pitch-shifting is enabled.\n"
                "// The final SFZ file will be generated on save, containing multiple samples.\n"
                "// ADSR and loop settings will be applied to all samples."
            )
            return

        if self.audio_file_path is None:
            self.sfz_buffer.set_text("// No audio file loaded")
            return

        # Generate SFZ content for simple mode
        sfz_content = []
        sfz_content.append("<group>")
        sfz_content.append("<region>")
        sfz_content.append(f"sample={os.path.basename(self.audio_file_path)}")
        sfz_content.append(f"pitch_keycenter={int(self.pitch_keycenter.get_value())}")
        
        extra_defs = self.get_extra_sfz_definitions()
        if extra_defs:
            sfz_content.append(extra_defs)

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
        
        if self.current_sfz_path or self.audio_file_path:
            default_folder_path = os.path.dirname(self.current_sfz_path or self.audio_file_path)
            dialog.set_current_folder(Gtk.File.new_for_path(default_folder_path))


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
