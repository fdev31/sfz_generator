import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")

from gi.repository import Gtk, Adw, Gdk, GLib, GObject, Gio
import numpy as np
import soundfile as sf
import os
from pathlib import Path
import threading
import sounddevice as sd
import re
import queue
import tempfile

from sfz_generator.audio.jack_client import JackClient
from sfz_generator.audio.player import play
from sfz_generator.audio.processing import load_audio
from sfz_generator.sfz.generator import generate_pitch_shifted_instrument, get_simple_sfz_content
from sfz_generator.sfz.parser import parse_sfz_file
from sfz_generator.widgets.envelope_widget import EnvelopeWidget
from sfz_generator.widgets.waveform_widget import WaveformWidget
from sfz_generator.widgets.piano_widget import PianoWidget
from sfz_generator.audio.preview import play_sfz_note


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
        self.playing_notes = {}
        self.selected_midi_port = None
        self.generated_instrument_path = None

        # JACK client
        self.jack_client = JackClient()
        self.connect("destroy", self.on_destroy)

        # Playback lock for sounddevice
        self.playback_lock = threading.Lock()

        # Note playback queue
        self.note_queue = queue.Queue()
        self.note_playback_thread = threading.Thread(target=self.note_playback_worker)
        self.note_playback_thread.daemon = True
        self.note_playback_thread.start()

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
            "Save the current configuration as an SFZ file"
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
        self.populate_midi_devices()

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

        # --- General Expander ---
        general_expander = Adw.ExpanderRow(title="General", expanded=True)
        main_group.add(general_expander)

        self.file_label = Gtk.Label(label="No file loaded")
        self.file_label.set_halign(Gtk.Align.START)
        file_row = Adw.ActionRow(title="Audio File")
        file_row.add_suffix(self.file_label)
        general_expander.add_row(file_row)

        self.sfz_label = Gtk.Label(label="No SFZ loaded")
        self.sfz_label.set_halign(Gtk.Align.START)
        sfz_row = Adw.ActionRow(title="SFZ File")
        sfz_row.add_suffix(self.sfz_label)
        general_expander.add_row(sfz_row)

        self.trigger_strings = Gtk.StringList.new(
            ["attack", "release", "first", "legato", "release_key"]
        )
        self.trigger_mode = Gtk.DropDown(model=self.trigger_strings, tooltip_text="Set the trigger mode for the sample")
        self.trigger_mode.set_selected(0) # Default to 'attack'
        self.trigger_mode.connect("notify::selected", self.on_trigger_mode_changed)
        trigger_row = Adw.ActionRow(title="Trigger Mode")
        trigger_row.add_suffix(self.trigger_mode)
        general_expander.add_row(trigger_row)

        self.pitch_keycenter = Gtk.SpinButton.new_with_range(0, 127, 1)
        self.pitch_keycenter.set_value(60)  # Middle C
        self.pitch_keycenter.set_tooltip_text("The MIDI note at which the sample plays back at its original pitch")
        self.pitch_keycenter.connect("value-changed", self.update_sfz_output)
        pitch_row = Adw.ActionRow(title="Pitch Keycenter")
        pitch_row.add_suffix(self.pitch_keycenter)
        general_expander.add_row(pitch_row)

        self.low_key_spin = Gtk.SpinButton.new_with_range(0, 127, 1)
        self.low_key_spin.set_value(24)  # C1
        self.low_key_spin.set_tooltip_text("The lowest MIDI note to generate a sample for")
        self.low_key_spin.set_sensitive(True)
        self.low_key_row = Adw.ActionRow(title="Low Key")
        self.low_key_row.add_suffix(self.low_key_spin)
        self.low_key_row.set_visible(True)
        general_expander.add_row(self.low_key_row)

        self.high_key_spin = Gtk.SpinButton.new_with_range(0, 127, 1)
        self.high_key_spin.set_value(84)  # C6
        self.high_key_spin.set_tooltip_text("The highest MIDI note to generate a sample for")
        self.high_key_spin.set_sensitive(True)
        self.high_key_row = Adw.ActionRow(title="High Key")
        self.high_key_row.add_suffix(self.high_key_spin)
        self.high_key_row.set_visible(True)
        general_expander.add_row(self.high_key_row)

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
        general_expander.add_row(playback_row)

        # --- MIDI Preview Expander ---
        midi_expander = Adw.ExpanderRow(title="MIDI Device", expanded=True)
        main_group.add(midi_expander)

        self.midi_device_combo = Gtk.ComboBoxText()
        self.midi_device_combo.set_tooltip_text("Select a MIDI device for preview")
        self.midi_device_combo.connect("changed", self.on_midi_device_changed)

        midi_device_row = Adw.ActionRow(title="")
        midi_device_row.add_suffix(self.midi_device_combo)
        midi_expander.add_row(midi_device_row)
        
        refresh_midi_button = Gtk.Button(icon_name="view-refresh-symbolic")
        refresh_midi_button.set_tooltip_text("Refresh MIDI device list")
        refresh_midi_button.connect("clicked", lambda w: self.populate_midi_devices())
        midi_device_row.add_prefix(refresh_midi_button)


        # --- Loop Settings Expander ---
        loop_expander = Adw.ExpanderRow(title="Loop / sustain", expanded=True)
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

        self.hold_spin_row = Adw.SpinRow.new_with_range(0, 1, 0.01)
        self.hold_spin_row.set_title("Hold (s)")
        self.hold_spin_row.set_value(0)
        self.hold_spin_row.get_adjustment().connect("value-changed", self.update_sfz_output)
        adsr_expander.add_row(self.hold_spin_row)

        self.release_spin_row = Adw.SpinRow.new_with_range(0, 1, 0.01)
        self.release_spin_row.set_title("Release (s)")
        self.release_spin_row.set_value(0)
        self.release_spin_row.get_adjustment().connect("value-changed", self.update_sfz_output)
        adsr_expander.add_row(self.release_spin_row)

        self.envelope_widget = EnvelopeWidget()
        adsr_expander.add_row(self.envelope_widget)

        # --- Pitch Settings Expander ---
        self.pitch_shift_check = Gtk.CheckButton(label="Enable")
        self.pitch_shift_check.set_tooltip_text("Generate a separate, pre-pitch-shifted audio file for each note")
        self.pitch_shift_check.set_active(False)
        self.pitch_shift_check.connect("toggled", self.on_pitch_shift_toggled)
        gen_row = Adw.ActionRow(title="Pitch shifting")
        gen_row.add_suffix(self.pitch_shift_check)
        main_group.add(gen_row)

        self.process_button = Gtk.Button(label="Process")
        self.process_button.connect("clicked", self.on_process_clicked)
        self.process_row = Adw.ActionRow(title="Generate Instrument")
        self.process_row.add_suffix(self.process_button)
        main_group.add(self.process_row)
        
        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_show_text(True)
        self.progress_row = Adw.ActionRow(title="Progress")
        self.progress_row.add_suffix(self.progress_bar)
        main_group.add(self.progress_row)

        # Initially hidden
        self.process_row.set_visible(False)
        self.progress_row.set_visible(False)

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

        # Create Piano preview
        piano_frame = Gtk.Frame()
        piano_frame.set_label("Piano Preview")
        self.piano_widget = PianoWidget()
        self.piano_widget.set_size_request(-1, 80)
        self.piano_widget.connect("note-on", self.on_piano_press)
        self.piano_widget.connect("note-off", self.on_piano_release)
        piano_frame.set_child(self.piano_widget)
        self.right_panel.append(piano_frame)


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

    def on_trigger_mode_changed(self, dropdown, param):
        self.update_sfz_output()

    def on_pitch_shift_toggled(self, button):
        is_active = button.get_active()
        self.process_row.set_visible(is_active)
        self.progress_row.set_visible(False)
        self.generated_instrument_path = None
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
                        parts.append(f"loop_crossfade={crossfade_value:.3f}")

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

        selected_trigger = self.trigger_strings.get_string(self.trigger_mode.get_selected())
        if selected_trigger != "attack":
            parts.append(f"trigger={selected_trigger}")

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

        sfz_path, num_successful, num_total = generate_pitch_shifted_instrument(
            output_dir,
            self.audio_file_path,
            int(self.pitch_keycenter.get_value()),
            int(self.low_key_spin.get_value()),
            int(self.high_key_spin.get_value()),
            self.sample_rate,
            self.get_extra_sfz_definitions(),
            progress_callback
        )

        GLib.idle_add(self.show_generation_complete_dialog, sfz_path, num_successful, num_total)
        if sfz_path:
            self.generated_instrument_path = sfz_path
            GLib.idle_add(self.update_sfz_output)

        GLib.idle_add(self.spinner.stop)
        GLib.idle_add(self.process_button.set_sensitive, True)
        GLib.idle_add(self.progress_row.set_visible, False)

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
        
        if self.generated_instrument_path:
            current_content = self.sfz_buffer.get_text(
                self.sfz_buffer.get_start_iter(), self.sfz_buffer.get_end_iter(), True
            )
            is_multisample = "<control>" in current_content

            content_lines = []
            if is_multisample:
                content_lines = current_content.split('\n')
            else:
                try:
                    with open(self.generated_instrument_path, 'r') as f:
                        content_lines = f.read().split('\n')
                except (FileNotFoundError, TypeError):
                    self.generated_instrument_path = None
                    self.update_sfz_output()
                    return

            try:
                global_start_index = content_lines.index('<global>') + 1
                group_start_index = content_lines.index('<group>')
                
                new_lines = content_lines[:global_start_index] + self.get_extra_sfz_definitions() + content_lines[group_start_index:]
                new_content = "\n".join(new_lines)
                
                self.sfz_buffer.set_text(new_content)
                
                with open(self.generated_instrument_path, 'w') as f:
                    f.write(new_content)
            except (ValueError, IndexError):
                self.generated_instrument_path = None
                self.update_sfz_output()
                return
        else:
            content = get_simple_sfz_content(
                self.audio_file_path,
                self.pitch_keycenter.get_value(),
                self.get_extra_sfz_definitions()
            )
            self.sfz_buffer.set_text(content)
        
        self.restart_preview()

    def note_playback_worker(self):
        while True:
            action, note = self.note_queue.get()
            if action == 'on':
                if note in self.playing_notes:
                    continue  # Note already playing

                stop_event = threading.Event()
                self.playing_notes[note] = stop_event
                
                def run_playback(note, stop_event):
                    GLib.idle_add(self.piano_widget.set_note_active, note)

                    sfz_content = self.sfz_buffer.get_text(
                        self.sfz_buffer.get_start_iter(),
                        self.sfz_buffer.get_end_iter(),
                        True,
                    )
                    
                    base_dir = None
                    if self.generated_instrument_path:
                        base_dir = os.path.dirname(self.generated_instrument_path)

                    play_sfz_note(sfz_content, base_dir, note, 4, self.playback_lock, stop_event)
                    
                    GLib.idle_add(self.piano_widget.set_note_inactive, note)
                    if note in self.playing_notes:
                        del self.playing_notes[note]

                thread = threading.Thread(target=run_playback, args=(note, stop_event))
                thread.daemon = True
                thread.start()

            elif action == 'off':
                if note in self.playing_notes:
                    self.playing_notes[note].set()

            self.note_queue.task_done()

    def on_piano_press(self, widget, note):
        self.note_queue.put(('on', note))

    def on_piano_release(self, widget, note):
        self.note_queue.put(('off', note))

    def populate_midi_devices(self):
        self.midi_device_combo.remove_all()
        self.midi_device_combo.append_text("None")
        self.midi_device_combo.set_active(0)
        ports = self.jack_client.get_midi_ports()
        for port in ports:
            self.midi_device_combo.append_text(port.name)

    def on_midi_device_changed(self, combo):
        text = combo.get_active_text()
        if text == "None":
            if self.selected_midi_port:
                self.jack_client.disconnect(self.selected_midi_port)
            self.selected_midi_port = None
            self.jack_client.stop_preview()
        else:
            self.selected_midi_port = text
            self.restart_preview()

    def restart_preview(self):
        if not self.selected_midi_port:
            return

        if self.generated_instrument_path:
            instrument_dir = os.path.dirname(self.generated_instrument_path)
            self.jack_client.start_preview(self.generated_instrument_path, cwd=instrument_dir)
            self.jack_client.connect(self.selected_midi_port)
        else:
            sfz_content = self.sfz_buffer.get_text(
                self.sfz_buffer.get_start_iter(),
                self.sfz_buffer.get_end_iter(),
                True,
            )
            
            with tempfile.NamedTemporaryFile(mode='w', suffix=".sfz", delete=False) as temp_sfz:
                temp_sfz.write(sfz_content)
                temp_sfz_path = temp_sfz.name

            self.jack_client.start_preview(temp_sfz_path)
            self.jack_client.connect(self.selected_midi_port)
            
            GLib.timeout_add(2000, os.unlink, temp_sfz_path)

    def on_destroy(self, *args):
        self.jack_client.close()
