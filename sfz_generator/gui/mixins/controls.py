import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Adw
import numpy as np


class ControlsMixin:
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
        midi_expander.add_action(refresh_midi_button)


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

        self.envelope_widget = self.EnvelopeWidget()
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
