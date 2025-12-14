import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk


class WaveformMixin:
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
        self.waveform_widget = self.WaveformWidget()
        waveform_box.append(self.waveform_widget)

        # Connect signals
        self.waveform_widget.connect("loop-start-changed", self.on_loop_start_changed)
        self.waveform_widget.connect("loop-end-changed", self.on_loop_end_changed)
        self.waveform_widget.connect("zoom-changed", self.on_zoom_changed)
        self.waveform_widget.connect("pan-changed", self.on_pan_changed)

        self.right_panel.append(waveform_frame)

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
