import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk


class SfzOutputMixin:
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
        self.piano_widget = self.PianoWidget()
        self.piano_widget.set_size_request(-1, 80)
        self.piano_widget.connect("note-on", self.on_piano_press)
        self.piano_widget.connect("note-off", self.on_piano_release)
        piano_frame.set_child(self.piano_widget)
        self.right_panel.append(piano_frame)

    def on_piano_press(self, widget, note):
        self.note_queue.put(("on", note))

    def on_piano_release(self, widget, note):
        self.note_queue.put(("off", note))
