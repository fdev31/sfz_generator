import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk


class EnvelopeWidget(Gtk.DrawingArea):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_draw_func(self.on_draw)
        self.adsr_values = {
            "delay": 0.0,
            "attack": 0.0,
            "hold": 0.0,
            "decay": 0.0,
            "sustain": 1.0,
            "release": 0.0,
        }
        self.set_content_height(100)

    def set_adsr_values(self, **kwargs):
        for key, value in kwargs.items():
            if key in self.adsr_values:
                self.adsr_values[key] = value
        self.queue_draw()

    def on_draw(self, area, cr, width, height):
        # Background
        cr.set_source_rgba(0.1, 0.1, 0.1, 1.0)  # Dark background
        cr.paint()

        # Drawing settings
        cr.set_source_rgba(0.3, 0.8, 0.3, 1.0)  # Green line
        cr.set_line_width(2)

        # Get ADSR values
        vals = self.adsr_values
        delay = vals["delay"]
        attack = vals["attack"]
        hold = vals["hold"]
        decay = vals["decay"]
        sustain = vals["sustain"]
        release = vals["release"]

        # Total time for scaling
        sustain_viz_time = 0.4  # A fixed proportion of width for sustain visualization
        total_time = delay + attack + hold + decay + sustain_viz_time + release
        if total_time == 0:
            total_time = 1.0

        # Coordinates
        x_padding = 5
        y_padding = 5

        drawable_width = width - 2 * x_padding
        drawable_height = height - 2 * y_padding

        def time_to_x(t):
            return x_padding + (t / total_time) * drawable_width

        def amp_to_y(a):
            return y_padding + (1 - a) * drawable_height

        # --- Draw Envelope Shape ---
        cr.move_to(time_to_x(0), amp_to_y(0))

        # Delay phase
        p1_x = time_to_x(delay)
        cr.line_to(p1_x, amp_to_y(0))

        # Attack phase
        p2_x = time_to_x(delay + attack)
        attack_peak_y = amp_to_y(1.0)
        cr.line_to(p2_x, attack_peak_y)

        # Hold phase
        p3_x = time_to_x(delay + attack + hold)
        cr.line_to(p3_x, attack_peak_y)

        # Decay phase
        p4_x = time_to_x(delay + attack + hold + decay)
        sustain_y = amp_to_y(sustain)
        cr.line_to(p4_x, sustain_y)

        # Sustain visualization
        p5_x = time_to_x(delay + attack + hold + decay + sustain_viz_time)
        cr.line_to(p5_x, sustain_y)

        # Release phase
        p6_x = time_to_x(delay + attack + hold + decay + sustain_viz_time + release)
        cr.line_to(p6_x, amp_to_y(0))

        cr.stroke()
