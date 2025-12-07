#!/usr/bin/env python3
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")

from gi.repository import Gtk, Gdk, GObject, cairo
import numpy as np


class WaveformWidget(Gtk.DrawingArea):
    def __init__(self):
        super().__init__()

        # Set initial size
        self.set_size_request(800, 300)

        # Initialize variables
        self.audio_data = None
        self.sample_rate = None
        self.loop_start = None
        self.loop_end = None
        self.zoom_level = 1.0
        self.pan_offset = 0
        self.dragging_marker = None
        self.is_playing = False
        self.loop_playback = False

        # Colors
        self.bg_color = (0.1, 0.1, 0.1)
        self.wave_color = (0.2, 0.6, 1.0)
        self.loop_start_color = (0.2, 0.8, 0.2)
        self.loop_end_color = (0.8, 0.2, 0.2)
        self.loop_region_color = (0.9, 0.9, 0.2, 0.2)
        self.playback_color = (0.2, 0.8, 0.2, 0.3)
        self.grid_color = (0.3, 0.3, 0.3)
        self.text_color = (0.9, 0.9, 0.9)

        # Mouse tracking
        self.last_x = None
        self.pan_start_x = None

        # Set events
        self.set_focusable(True)
        self.set_can_focus(True)

        # Add controllers for events
        self.motion_controller = Gtk.EventControllerMotion()
        self.motion_controller.connect("motion", self.on_motion)
        self.add_controller(self.motion_controller)

        self.click_controller = Gtk.GestureClick()
        self.click_controller.connect("pressed", self.on_button_press)
        self.click_controller.connect("released", self.on_button_release)
        self.add_controller(self.click_controller)

        self.scroll_controller = Gtk.EventControllerScroll()
        self.scroll_controller.set_flags(Gtk.EventControllerScrollFlags.BOTH_AXES)
        self.scroll_controller.connect("scroll", self.on_scroll)
        self.add_controller(self.scroll_controller)

        # Set draw function
        self.set_draw_func(self.on_draw)

    def set_audio_data(self, audio_data, sample_rate):
        self.audio_data = audio_data
        self.sample_rate = sample_rate
        self.queue_draw()

    def set_loop_points(self, loop_start, loop_end):
        self.loop_start = loop_start
        self.loop_end = loop_end
        self.queue_draw()

    def set_zoom(self, zoom_level):
        self.zoom_level = zoom_level
        self.queue_draw()

    def set_pan(self, pan_offset):
        self.pan_offset = pan_offset
        self.queue_draw()

    def set_playback_state(self, is_playing, loop_playback=False):
        self.is_playing = is_playing
        self.loop_playback = loop_playback
        self.queue_draw()

    def on_draw(self, widget, cr, width, height):
        # Clear background
        cr.set_source_rgb(*self.bg_color)
        cr.rectangle(0, 0, width, height)
        cr.fill()

        # Draw grid
        self.draw_grid(cr, width, height)

        # Draw waveform if data is available
        if self.audio_data is not None:
            self.draw_waveform(cr, width, height)

            # Draw loop markers if loop mode is enabled
            if self.loop_start is not None and self.loop_end is not None:
                self.draw_loop_markers(cr, width, height)

                # Draw loop region
                self.draw_loop_region(cr, width, height)

                # Draw playback indicator if playing
                if self.is_playing and self.loop_playback:
                    self.draw_playback_region(cr, width, height)

        # Draw title
        self.draw_title(cr, width, height)

        return True

    def draw_grid(self, cr, width, height):
        # Set grid color
        cr.set_source_rgba(*self.grid_color)
        cr.set_line_width(0.5)

        # Draw horizontal center line
        cr.move_to(0, height / 2)
        cr.line_to(width, height / 2)
        cr.stroke()

        # Draw vertical lines at regular intervals
        # Calculate visible range in samples
        total_samples = len(self.audio_data) if self.audio_data is not None else 0
        if total_samples > 0:
            visible_samples = int(total_samples / self.zoom_level)
            start_sample = int(self.pan_offset * total_samples)

            # Draw grid lines every 10% of visible range
            grid_interval = visible_samples / 10
            for i in range(11):
                sample_pos = start_sample + i * grid_interval
                x_pos = (i / 10) * width
                cr.move_to(x_pos, 0)
                cr.line_to(x_pos, height)
                cr.stroke()

    def draw_waveform(self, cr, width, height):
        if self.audio_data is None:
            return

        # Calculate visible range
        total_samples = len(self.audio_data)
        visible_samples = int(total_samples / self.zoom_level)
        start_sample = int(self.pan_offset * total_samples)
        end_sample = min(start_sample + visible_samples, total_samples)

        if start_sample >= total_samples:
            return

        # Get the visible portion of the audio data
        visible_data = self.audio_data[start_sample:end_sample]

        # If we have more samples than pixels, we need to downsample
        if len(visible_data) > width:
            # Calculate downsample factor
            factor = len(visible_data) / width

            # Create arrays for min and max values
            mins = np.zeros(width, dtype=np.float32)
            maxs = np.zeros(width, dtype=np.float32)

            # Calculate min and max for each pixel column
            for i in range(width):
                start_idx = int(i * factor)
                end_idx = int((i + 1) * factor)
                if end_idx > len(visible_data):
                    end_idx = len(visible_data)

                if start_idx < end_idx:
                    mins[i] = np.min(visible_data[start_idx:end_idx])
                    maxs[i] = np.max(visible_data[start_idx:end_idx])

            # Draw the waveform
            cr.set_source_rgb(*self.wave_color)
            cr.set_line_width(1)

            # Draw max values
            for i in range(width):
                x = i
                y = height / 2 - (maxs[i] * height / 2)
                if i == 0:
                    cr.move_to(x, y)
                else:
                    cr.line_to(x, y)

            # Draw min values in reverse
            for i in range(width - 1, -1, -1):
                x = i
                y = height / 2 - (mins[i] * height / 2)
                cr.line_to(x, y)

            cr.close_path()
            cr.stroke()
        else:
            # We have fewer samples than pixels, draw each sample
            cr.set_source_rgb(*self.wave_color)
            cr.set_line_width(1)

            # Calculate x scale
            x_scale = width / len(visible_data)

            # Draw the waveform
            for i in range(len(visible_data)):
                x = i * x_scale
                y = height / 2 - (visible_data[i] * height / 2)
                if i == 0:
                    cr.move_to(x, y)
                else:
                    cr.line_to(x, y)

            cr.stroke()

    def draw_loop_markers(self, cr, width, height):
        # Calculate visible range
        total_samples = len(self.audio_data)
        visible_samples = int(total_samples / self.zoom_level)
        start_sample = int(self.pan_offset * total_samples)
        end_sample = min(start_sample + visible_samples, total_samples)

        # Draw loop start marker
        if self.loop_start >= start_sample and self.loop_start <= end_sample:
            x = (self.loop_start - start_sample) / visible_samples * width

            # Draw line
            cr.set_source_rgb(*self.loop_start_color)
            cr.set_line_width(2)
            cr.move_to(x, 0)
            cr.line_to(x, height)
            cr.stroke()

            # Draw label
            cr.set_source_rgb(*self.text_color)
            cr.select_font_face("Sans", cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
            cr.set_font_size(12)
            cr.move_to(x + 5, 15)
            cr.show_text("Loop Start")

        # Draw loop end marker
        if self.loop_end >= start_sample and self.loop_end <= end_sample:
            x = (self.loop_end - start_sample) / visible_samples * width

            # Draw line
            cr.set_source_rgb(*self.loop_end_color)
            cr.set_line_width(2)
            cr.move_to(x, 0)
            cr.line_to(x, height)
            cr.stroke()

            # Draw label
            cr.set_source_rgb(*self.text_color)
            cr.select_font_face("Sans", cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
            cr.set_font_size(12)
            cr.move_to(x + 5, 30)
            cr.show_text("Loop End")

    def draw_loop_region(self, cr, width, height):
        # Calculate visible range
        total_samples = len(self.audio_data)
        visible_samples = int(total_samples / self.zoom_level)
        start_sample = int(self.pan_offset * total_samples)
        end_sample = min(start_sample + visible_samples, total_samples)

        # Calculate loop region in pixels
        loop_start_px = (self.loop_start - start_sample) / visible_samples * width
        loop_end_px = (self.loop_end - start_sample) / visible_samples * width

        # Clip to visible range
        loop_start_px = max(0, min(width, loop_start_px))
        loop_end_px = max(0, min(width, loop_end_px))

        # Draw loop region
        if loop_end_px > loop_start_px:
            cr.set_source_rgba(*self.loop_region_color)
            cr.rectangle(loop_start_px, 0, loop_end_px - loop_start_px, height)
            cr.fill()

    def draw_playback_region(self, cr, width, height):
        # Calculate visible range
        total_samples = len(self.audio_data)
        visible_samples = int(total_samples / self.zoom_level)
        start_sample = int(self.pan_offset * total_samples)
        end_sample = min(start_sample + visible_samples, total_samples)

        # Calculate loop region in pixels
        loop_start_px = (self.loop_start - start_sample) / visible_samples * width
        loop_end_px = (self.loop_end - start_sample) / visible_samples * width

        # Clip to visible range
        loop_start_px = max(0, min(width, loop_start_px))
        loop_end_px = max(0, min(width, loop_end_px))

        # Draw playback region
        if loop_end_px > loop_start_px:
            cr.set_source_rgba(*self.playback_color)
            cr.rectangle(loop_start_px, 0, loop_end_px - loop_start_px, height)
            cr.fill()

    def draw_title(self, cr, width, height):
        # Set text properties
        cr.set_source_rgb(*self.text_color)
        cr.select_font_face("Sans", cairo.FontSlant.NORMAL, cairo.FontWeight.BOLD)
        cr.set_font_size(14)

        # Draw title
        title = f"Waveform Preview (Zoom: {self.zoom_level:.1f}x)"
        text_extents = cr.text_extents(title)
        x = (width - text_extents.width) / 2
        y = height - 10
        cr.move_to(x, y)
        cr.show_text(title)

    def on_motion(self, controller, x, y):
        if self.audio_data is None:
            return True

        # Calculate sample position
        total_samples = len(self.audio_data)
        visible_samples = int(total_samples / self.zoom_level)
        start_sample = int(self.pan_offset * total_samples)

        sample_pos = start_sample + (x / self.get_width()) * visible_samples

        if self.dragging_marker == "start":
            self.loop_start = int(
                np.clip(
                    sample_pos,
                    0,
                    self.loop_end - 1 if self.loop_end else total_samples - 1,
                )
            )
            self.queue_draw()
            # Emit signal to update spin button
            self.emit("loop-start-changed", self.loop_start)
        elif self.dragging_marker == "end":
            self.loop_end = int(
                np.clip(
                    sample_pos,
                    self.loop_start + 1 if self.loop_start else 0,
                    total_samples - 1,
                )
            )
            self.queue_draw()
            # Emit signal to update spin button
            self.emit("loop-end-changed", self.loop_end)
        elif self.dragging_marker == "pan":
            if self.pan_start_x is not None:
                # Calculate pan delta
                dx = (self.pan_start_x - x) / self.get_width()
                self.pan_offset = np.clip(
                    self.pan_offset + dx, 0, 1 - (1 / self.zoom_level)
                )
                self.pan_start_x = x
                self.queue_draw()

        return True

    def on_button_press(self, gesture, n_press, x, y):
        if self.audio_data is None:
            return True

        # Calculate sample position
        total_samples = len(self.audio_data)
        visible_samples = int(total_samples / self.zoom_level)
        start_sample = int(self.pan_offset * total_samples)

        sample_pos = start_sample + (x / self.get_width()) * visible_samples

        # Check if clicking near a marker - use pixel-based threshold for more stable detection
        marker_threshold = 10  # pixels

        # Calculate marker positions in pixels
        if (
            self.loop_start is not None
            and self.loop_start >= start_sample
            and self.loop_start <= start_sample + visible_samples
        ):
            loop_start_px = (
                (self.loop_start - start_sample) / visible_samples * self.get_width()
            )
            if abs(x - loop_start_px) < marker_threshold:
                self.dragging_marker = "start"
                return True

        if (
            self.loop_end is not None
            and self.loop_end >= start_sample
            and self.loop_end <= start_sample + visible_samples
        ):
            loop_end_px = (
                (self.loop_end - start_sample) / visible_samples * self.get_width()
            )
            if abs(x - loop_end_px) < marker_threshold:
                self.dragging_marker = "end"
                return True

        # Start panning
        self.dragging_marker = "pan"
        self.pan_start_x = x

        return True

    def on_button_release(self, gesture, n_press, x, y):
        self.dragging_marker = None
        self.pan_start_x = None
        return True

    def on_scroll(self, controller, dx, dy):
        if self.audio_data is None:
            return True

        is_shift = controller.get_current_event_state() & Gdk.ModifierType.SHIFT_MASK

        if is_shift and dx != 0:
            # Horizontal panning with Shift key
            if self.zoom_level > 1:
                # dx is the horizontal scroll delta. Positive is right.
                pan_delta = dx * 0.01  # Adjust sensitivity
                self.pan_offset = np.clip(
                    self.pan_offset + pan_delta, 0, 1 - (1 / self.zoom_level)
                )
                self.queue_draw()
                self.emit("pan-changed", self.pan_offset)
        elif dy != 0:
            # Vertical scroll for zooming
            if dy < 0:
                self.zoom_level = min(self.zoom_level * 1.2, 100)
            elif dy > 0:
                self.zoom_level = max(self.zoom_level / 1.2, 1)

            # Keep pan offset within bounds after zoom
            self.pan_offset = np.clip(
                self.pan_offset, 0, 1 - (1 / self.zoom_level)
            )
            self.queue_draw()
            self.emit("zoom-changed", self.zoom_level)
            self.emit("pan-changed", self.pan_offset)

        return True


# Register custom signals
GObject.signal_new(
    "loop-start-changed",
    WaveformWidget,
    GObject.SignalFlags.RUN_LAST,
    GObject.TYPE_NONE,
    (GObject.TYPE_INT,),
)
GObject.signal_new(
    "loop-end-changed",
    WaveformWidget,
    GObject.SignalFlags.RUN_LAST,
    GObject.TYPE_NONE,
    (GObject.TYPE_INT,),
)
GObject.signal_new(
    "zoom-changed",
    WaveformWidget,
    GObject.SignalFlags.RUN_LAST,
    GObject.TYPE_NONE,
    (GObject.TYPE_FLOAT,),
)
GObject.signal_new(
    "pan-changed",
    WaveformWidget,
    GObject.SignalFlags.RUN_LAST,
    GObject.TYPE_NONE,
    (GObject.TYPE_FLOAT,),
)
