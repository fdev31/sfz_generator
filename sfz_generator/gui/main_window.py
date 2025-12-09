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

from sfz_generator.audio.player import play
from sfz_generator.audio.processing import load_audio
from sfz_generator.sfz.generator import generate_pitch_shifted_instrument, get_simple_sfz_content
from sfz_generator.sfz.parser import parse_sfz_file
from sfz_generator.widgets.envelope_widget import EnvelopeWidget
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
        self.stop_playback_event = threading.Event()
        self.current_sfz_path = None

        # Main layout
        self.toolbar_view = Adw.ToolbarView()
        self.set_content(self.toolbar_view)

        self.header_bar = Adw.HeaderBar()
        self.toolbar_view.add_top_bar(self.header_bar)

        # Add EventControllerKey
        self.key_controller = Gtk.EventControllerKey.new()
        self.key_controller.connect("key-pressed", self.on_key_press)
        self.add_controller(self.key_controller)

        # Add flap toggle button to header
        self.flap_toggle = Gtk.ToggleButton()
        self.flap_toggle.set_icon_name("sidebar-show-symbolic")
        self.flap_toggle.set_active(True)
        self.flap_toggle.set_tooltip_text("Show/Hide Controls Panel")
        self.flap_toggle.set_valign(Gtk.Align.CENTER)
        self.header_bar.pack_start(self.flap_toggle)

        # Add open file buttons
        self.open_button = Gtk.Button(label="Open Audio")
        self.open_button.set_tooltip_text("Open an audio file (WAV, AIFF, FLAC)")
        self.open_button.connect("clicked", self.on_open_file)
        self.header_bar.pack_start(self.open_button)

        self.load_sfz_button = Gtk.Button(label="Load SFZ")
        self.load_sfz_button.set_tooltip_text("Load an existing SFZ file to edit")
        self.load_sfz_button.connect("clicked", self.on_load_sfz)
        self.header_bar.pack_start(self.load_sfz_button)

        self.save_sfz_button = Gtk.Button(label="Save SFZ")
        self.save_sfz_button.set_tooltip_text(
            "Save the current configuration as an SFZ file or instrument"
        )
        self.save_sfz_button.connect("clicked", self.on_save_sfz)
        self.header_bar.pack_end(self.save_sfz_button)

        self.spinner = Gtk.Spinner()
        self.header_bar.pack_end(self.spinner)

        # Create main content area using Adw.Flap
        self.flap = Adw.Flap()
        self.toolbar_view.set_content(self.flap)

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
        main_group = Adw.PreferencesGroup()
        self.left_panel.append(main_group)

        # --- File Information Expander ---
        file_expander = Adw.ExpanderRow(title="File Information", expanded=True)
        main_group.add(file_expander)

        self.file_label = Gtk.Label(label="No file loaded")
        self.file_label.set_halign(Gtk.Align.START)
        file_row = Adw.ActionRow(title="Audio File")
        file_row.add_suffix(self.file_label)
        file_expander.add_row(file_row)

        self.sfz_label = Gtk.Label(label="No SFZ loaded")
        self.sfz_label.set_halign(Gtk.Align.START)
        sfz_row = Adw.ActionRow(title="SFZ File")
        sfz_row.add_suffix(self.sfz_label)
        file_expander.add_row(sfz_row)

        # Playback controls
        playback_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        playback_box.set_margin_top(5)
        playback_box.set_margin_bottom(5)

        self.play_button = Gtk.Button(label="▶ Play")
        self.play_button.set_tooltip_text("Play the audio (Spacebar)")
        self.play_button.set_sensitive(False)
        self.play_button.connect("clicked", self.on_play_clicked)
        playback_box.append(self.play_button)

        self.stop_button = Gtk.Button(label="■ Stop")
        self.stop_button.set_tooltip_text("Stop playback (Spacebar)")
        self.stop_button.set_sensitive(False)
        self.stop_button.connect("clicked", self.on_stop_clicked)
        playback_box.append(self.stop_button)

        self.loop_playback_check = Gtk.CheckButton(label="Loop Playback")
        self.loop_playback_check.set_tooltip_text("Toggle looped playback of the selected loop region")
        self.loop_playback_check.set_sensitive(False)
        playback_box.append(self.loop_playback_check)

        playback_row = Adw.ActionRow()
        playback_row.set_child(playback_box)
        file_expander.add_row(playback_row)

        # --- Loop Settings Expander ---
        loop_expander = Adw.ExpanderRow(title="Loop Settings", expanded=True)
        loop_expander.set_expanded(False)
        main_group.add(loop_expander)

        self.zero_crossing_check = Gtk.CheckButton(label="Snap to Zero-Crossing")
        self.zero_crossing_check.set_tooltip_text("Snap loop points to the nearest zero-crossing to prevent clicks")
        self.zero_crossing_check.set_active(True)
        self.zero_crossing_check.connect("toggled", self.on_zero_crossing_toggled)
        
        zero_crossing_row = Adw.ActionRow(title="Snapping")
        zero_crossing_row.add_suffix(self.zero_crossing_check)
        loop_expander.add_row(zero_crossing_row)

        self.loop_strings = Gtk.StringList.new(
            ["no_loop", "one_shot", "loop_sustain", "loop_continuous"]
        )
        self.loop_mode = Gtk.DropDown(model=self.loop_strings, tooltip_text="Set the loop mode for the sample")
        self.loop_mode.set_selected(0)
        self.loop_mode.connect("notify::selected", self.on_loop_mode_changed)
        loop_row = Adw.ActionRow(title="Loop Mode")
        loop_row.add_suffix(self.loop_mode)
        loop_expander.add_row(loop_row)

        self.loop_start_spin = Gtk.SpinButton.new_with_range(0, 100, 1)
        self.loop_start_spin.set_tooltip_text("Set the start point of the loop in samples")
        self.loop_start_spin.set_sensitive(False)
        self.loop_start_spin.connect("value-changed", self.on_loop_marker_changed)
        loop_start_row = Adw.ActionRow(title="Loop Start (samples)")
        loop_start_row.add_suffix(self.loop_start_spin)
        loop_expander.add_row(loop_start_row)

        self.loop_end_spin = Gtk.SpinButton.new_with_range(0, 100, 1)
        self.loop_end_spin.set_tooltip_text("Set the end point of the loop in samples")
        self.loop_end_spin.set_sensitive(False)
        self.loop_end_spin.connect("value-changed", self.on_loop_marker_changed)
        loop_end_row = Adw.ActionRow(title="Loop End (samples)")
        loop_end_row.add_suffix(self.loop_end_spin)
        loop_expander.add_row(loop_end_row)

        self.loop_crossfade_spin_row = Adw.SpinRow.new_with_range(0, 1, 0.01)
        self.loop_crossfade_spin_row.set_title("Loop Crossfade (s)")
        self.loop_crossfade_spin_row.set_value(0)
        self.loop_crossfade_spin_row.get_adjustment().connect("value-changed", self.update_sfz_output)
        loop_expander.add_row(self.loop_crossfade_spin_row)

        # --- Envelope Expander ---
        adsr_expander = Adw.ExpanderRow(title="Envelope (ADSR)", expanded=True)
        adsr_expander.set_expanded(False)
        main_group.add(adsr_expander)

        self.delay_spin_row = Adw.SpinRow.new_with_range(0, 1, 0.01)
        self.delay_spin_row.set_title("Delay (s)")
        self.delay_spin_row.set_value(0)
        self.delay_spin_row.get_adjustment().connect("value-changed", self.update_sfz_output)
        adsr_expander.add_row(self.delay_spin_row)
        
        self.attack_spin_row = Adw.SpinRow.new_with_range(0, 1, 0.01)
        self.attack_spin_row.set_title("Attack (s)")
        self.attack_spin_row.set_value(0)
        self.attack_spin_row.get_adjustment().connect("value-changed", self.update_sfz_output)
        adsr_expander.add_row(self.attack_spin_row)

        self.hold_spin_row = Adw.SpinRow.new_with_range(0, 1, 0.01)
        self.hold_spin_row.set_title("Hold (s)")
        self.hold_spin_row.set_value(0)
        self.hold_spin_row.get_adjustment().connect("value-changed", self.update_sfz_output)
        adsr_expander.add_row(self.hold_spin_row)

        self.decay_spin_row = Adw.SpinRow.new_with_range(0, 1, 0.01)
        self.decay_spin_row.set_title("Decay (s)")
        self.decay_spin_row.set_value(0)
        self.decay_spin_row.get_adjustment().connect("value-changed", self.update_sfz_output)
        adsr_expander.add_row(self.decay_spin_row)

        self.sustain_spin_row = Adw.SpinRow.new_with_range(0, 100, 1)
        self.sustain_spin_row.set_title("Sustain (%)")
        self.sustain_spin_row.set_value(100)
        self.sustain_spin_row.get_adjustment().connect("value-changed", self.update_sfz_output)
        adsr_expander.add_row(self.sustain_spin_row)

        self.release_spin_row = Adw.SpinRow.new_with_range(0, 1, 0.01)
        self.release_spin_row.set_title("Release (s)")
        self.release_spin_row.set_value(0)
        self.release_spin_row.get_adjustment().connect("value-changed", self.update_sfz_output)
        adsr_expander.add_row(self.release_spin_row)

        self.envelope_widget = EnvelopeWidget()
        adsr_expander.add_row(self.envelope_widget)

        # --- Pitch Settings Expander ---
        pitch_expander = Adw.ExpanderRow(title="Pitch Settings")
        pitch_expander.set_expanded(False)
        main_group.add(pitch_expander)

        self.pitch_keycenter = Gtk.SpinButton.new_with_range(0, 127, 1)
        self.pitch_keycenter.set_value(60)  # Middle C
        self.pitch_keycenter.set_tooltip_text("The MIDI note at which the sample plays back at its original pitch")
        self.pitch_keycenter.connect("value-changed", self.update_sfz_output)
        pitch_row = Adw.ActionRow(title="Pitch Keycenter")
        pitch_row.add_suffix(self.pitch_keycenter)
        pitch_expander.add_row(pitch_row)

        self.pitch_shift_check = Gtk.CheckButton(label="Enable Pitch-shifting")
        self.pitch_shift_check.set_tooltip_text("Generate a separate, pre-pitch-shifted audio file for each note")
        self.pitch_shift_check.set_active(False)
        self.pitch_shift_check.connect("toggled", self.on_pitch_shift_toggled)
        gen_row = Adw.ActionRow(title="Advanced Generation")
        gen_row.add_suffix(self.pitch_shift_check)
        pitch_expander.add_row(gen_row)

        self.low_key_spin = Gtk.SpinButton.new_with_range(0, 127, 1)
        self.low_key_spin.set_value(24) # C1
        self.low_key_spin.set_tooltip_text("The lowest MIDI note to generate a sample for")
        self.low_key_spin.set_sensitive(False)
        self.low_key_row = Adw.ActionRow(title="Low Key")
        self.low_key_row.add_suffix(self.low_key_spin)
        self.low_key_row.set_visible(False)
        pitch_expander.add_row(self.low_key_row)

        self.high_key_spin = Gtk.SpinButton.new_with_range(0, 127, 1)
        self.high_key_spin.set_value(84) # C6
        self.high_key_spin.set_tooltip_text("The highest MIDI note to generate a sample for")
        self.high_key_spin.set_sensitive(False)
        self.high_key_row = Adw.ActionRow(title="High Key")
        self.high_key_row.add_suffix(self.high_key_spin)
        self.high_key_row.set_visible(False)
        pitch_expander.add_row(self.high_key_row)


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
        sfz_frame.set_vexpand(True)

        # Create scrolled window for text view
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_min_content_height(200)
        scrolled.set_vexpand(True)

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
        sfz_data, sample_path, error = parse_sfz_file(sfz_path)

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


        # Update SFZ output
        self.update_sfz_output()

    def load_audio_file(self):
        audio_data, audio_data_int16, sample_rate, error = load_audio(self.audio_file_path)

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
            self.playback_thread = threading.Thread(target=play, args=args)
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
        is_looping = loop_mode in ["loop_sustain", "loop_continuous"]
        self.loop_start_spin.set_sensitive(is_looping)
        self.loop_end_spin.set_sensitive(is_looping)
        self.loop_crossfade_spin_row.set_sensitive(is_looping)

        self.update_sfz_output()

    def on_loop_marker_changed(self, spin):
        loop_start = int(self.loop_start_spin.get_value())
        loop_end = int(self.loop_end_spin.get_value())

        if self.zero_crossing_check.get_active() and self.waveform_widget.zero_crossings is not None and self.waveform_widget.zero_crossings.size > 0:
            if spin == self.loop_start_spin:
                nearest_idx = np.argmin(np.abs(self.waveform_widget.zero_crossings - loop_start))
                loop_start = self.waveform_widget.zero_crossings[nearest_idx]
                self.loop_start_spin.set_value(loop_start) 
            elif spin == self.loop_end_spin:
                nearest_idx = np.argmin(np.abs(self.waveform_widget.zero_crossings - loop_end))
                loop_end = self.waveform_widget.zero_crossings[nearest_idx]
                self.loop_end_spin.set_value(loop_end)
        
        self.loop_start = loop_start
        self.loop_end = loop_end
        self.waveform_widget.set_loop_points(self.loop_start, self.loop_end)
        self.update_sfz_output()

    def on_zero_crossing_toggled(self, button):
        is_active = button.get_active()
        self.waveform_widget.set_snap_to_zero_crossing(is_active)

    def on_pitch_shift_toggled(self, button):
        is_active = button.get_active()
        self.low_key_spin.set_sensitive(is_active)
        self.high_key_spin.set_sensitive(is_active)
        self.low_key_row.set_visible(is_active)
        self.high_key_row.set_visible(is_active)
        self.update_sfz_output()

    def get_extra_sfz_definitions(self) -> list[str]:
        parts = []
        selected = self.loop_mode.get_selected()
        loop_mode = self.loop_strings.get_string(selected)

        if loop_mode != "no_loop":
            parts.append(f"loop_mode={loop_mode}")
            if loop_mode in ["loop_sustain", "loop_continuous"]:
                if self.loop_start is not None:
                    parts.append(f"loop_start={int(self.loop_start)}")
                if self.loop_end is not None:
                    parts.append(f"loop_end={int(self.loop_end)}")
                if self.sample_rate:
                    crossfade_value = self.loop_crossfade_spin_row.get_value()
                    if crossfade_value > 0:
                        parts.append(f"loop_crossfade={crossfade_value}")

        if self.delay_spin_row.get_value() > 0:
            parts.append(f"ampeg_delay={self.delay_spin_row.get_value():.3f}")
        if self.attack_spin_row.get_value() > 0:
            parts.append(f"ampeg_attack={self.attack_spin_row.get_value():.3f}")
        if self.hold_spin_row.get_value() > 0:
            parts.append(f"ampeg_hold={self.hold_spin_row.get_value():.3f}")
        if self.decay_spin_row.get_value() > 0:
            parts.append(f"ampeg_decay={self.decay_spin_row.get_value():.3f}")
        if self.sustain_spin_row.get_value() < 100:
            parts.append(f"ampeg_sustain={int(self.sustain_spin_row.get_value())}")
        if self.release_spin_row.get_value() > 0:
            parts.append(f"ampeg_release={self.release_spin_row.get_value():.3f}")

        if parts:
            return parts
        return []

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

    def generate_pitch_shifted_sfz(self, output_dir):
        GLib.idle_add(self.spinner.start)
        GLib.idle_add(self.save_sfz_button.set_sensitive, False)

        def thread_func():
            sfz_path, num_successful, num_total = generate_pitch_shifted_instrument(
                output_dir,
                self.audio_file_path,
                int(self.pitch_keycenter.get_value()),
                int(self.low_key_spin.get_value()),
                int(self.high_key_spin.get_value()),
                self.sample_rate,
                self.get_extra_sfz_definitions()
            )

            GLib.idle_add(self.show_generation_complete_dialog, sfz_path, num_successful, num_total)
            GLib.idle_add(self.spinner.stop)
            GLib.idle_add(self.save_sfz_button.set_sensitive, True)

        thread = threading.Thread(target=thread_func)
        thread.daemon = True
        thread.start()

    def update_envelope_preview(self):
        if not hasattr(self, "envelope_widget"):
            return

        adsr_params = {
            "delay": self.delay_spin_row.get_value(),
            "attack": self.attack_spin_row.get_value(),
            "hold": self.hold_spin_row.get_value(),
            "decay": self.decay_spin_row.get_value(),
            "sustain": self.sustain_spin_row.get_value() / 100.0,
            "release": self.release_spin_row.get_value(),
        }
        self.envelope_widget.set_adsr_values(**adsr_params)

    def update_sfz_output(self, *args):
        self.update_envelope_preview()
        if self.pitch_shift_check.get_active():
            self.sfz_buffer.set_text(
                "// Pitch-shifting is enabled.\n"
                "// The final SFZ file will be generated on save, containing multiple samples.\n"
                "// ADSR and loop settings will be applied to all samples."
            )
            return
            
        content = get_simple_sfz_content(
            self.audio_file_path,
            self.pitch_keycenter.get_value(),
            self.get_extra_sfz_definitions()
        )
        self.sfz_buffer.set_text(content)


