import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")

from gi.repository import Gtk, Adw, Gdk, GLib, GObject
import threading
import queue
import os

from sfz_generator.audio.jack_client import JackClient
from sfz_generator.audio.player import play as play_func
from sfz_generator.audio.processing import load_audio as load_audio_func
from sfz_generator.sfz.generator import generate_pitch_shifted_instrument as generate_pitch_shifted_instrument_func, get_simple_sfz_content
from sfz_generator.sfz.parser import parse_sfz_file as parse_sfz_file_func
from sfz_generator.widgets.envelope_widget import EnvelopeWidget
from sfz_generator.widgets.waveform_widget import WaveformWidget
from sfz_generator.widgets.piano_widget import PianoWidget
from sfz_generator.audio.preview import play_sfz_note as play_sfz_note_func

from .mixins.controls import ControlsMixin
from .mixins.file_io import FileIOMixin
from .mixins.midi import MidiMixin
from .mixins.playback import PlaybackMixin
from .mixins.processing import ProcessingMixin
from .mixins.sfz_output import SfzOutputMixin
from .mixins.waveform import WaveformMixin


class SFZGenerator(
    Adw.ApplicationWindow, ControlsMixin, FileIOMixin, MidiMixin, PlaybackMixin, ProcessingMixin, SfzOutputMixin, WaveformMixin
):
    # To make them available to mixins
    WaveformWidget = WaveformWidget
    PianoWidget = PianoWidget
    EnvelopeWidget = EnvelopeWidget
    play_func = play_func
    load_audio_func = load_audio_func
    parse_sfz_file_func = parse_sfz_file_func
    play_sfz_note_func = play_sfz_note_func
    generate_pitch_shifted_instrument_func = generate_pitch_shifted_instrument_func

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
        self.save_sfz_button.set_tooltip_text("Save the current configuration as an SFZ file")
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
            current_content = self.sfz_buffer.get_text(self.sfz_buffer.get_start_iter(), self.sfz_buffer.get_end_iter(), True)
            is_multisample = "<control>" in current_content

            content_lines = []
            if is_multisample:
                content_lines = current_content.split("\n")
            else:
                try:
                    with open(self.generated_instrument_path, "r") as f:
                        content_lines = f.read().split("\n")
                except (FileNotFoundError, TypeError):
                    self.generated_instrument_path = None
                    self.update_sfz_output()
                    return

            try:
                global_start_index = content_lines.index("<global>") + 1
                group_start_index = content_lines.index("<group>")

                new_lines = content_lines[:global_start_index] + self.get_extra_sfz_definitions() + content_lines[group_start_index:]
                new_content = "\n".join(new_lines)

                self.sfz_buffer.set_text(new_content)

                # Also update the sfz file on disk
                if os.path.exists(self.generated_instrument_path):
                    with open(self.generated_instrument_path, "w") as f:
                        f.write(new_content)
            except (ValueError, IndexError):
                self.generated_instrument_path = None
                self.update_sfz_output()
                return
        else:
            content = get_simple_sfz_content(self.audio_file_path, self.pitch_keycenter.get_value(), self.get_extra_sfz_definitions())
            self.sfz_buffer.set_text(content)

        self.restart_preview()

    def on_destroy(self, *args):
        self.jack_client.close()
