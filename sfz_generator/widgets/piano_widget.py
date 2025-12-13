import time
from gi.repository import Gtk, Gdk, GObject
import cairo

class PianoWidget(Gtk.DrawingArea):
    __gsignals__ = {
        'note-on': (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        'note-off': (GObject.SignalFlags.RUN_FIRST, None, (int,))
    }

    WHITE_KEY_COUNT = 21  # 3 octaves
    OCTAVE_SPAN = 7

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_draw_func(self.on_draw)
        self.start_note = 36  # C2
        self.active_notes = set()
        self.pressed_notes = set()
        
        gesture = Gtk.GestureClick.new()
        gesture.connect("pressed", self.on_pressed)
        gesture.connect("released", self.on_released)
        self.add_controller(gesture)

    def set_note_active(self, note):
        self.active_notes.add(note)
        self.queue_draw()

    def set_note_inactive(self, note):
        self.active_notes.discard(note)
        self.queue_draw()

    def on_draw(self, area, cr, width, height):
        self.key_rects = []
        white_notes = [0, 2, 4, 5, 7, 9, 11]
        
        # White keys
        white_key_width = width / self.WHITE_KEY_COUNT
        for i in range(self.WHITE_KEY_COUNT):
            octave, note_in_octave_idx = divmod(i, self.OCTAVE_SPAN)
            note = self.start_note + octave * 12 + white_notes[note_in_octave_idx]

            if note in self.active_notes:
                cr.set_source_rgb(0.7, 0.8, 1)  # Light blue for active
            else:
                cr.set_source_rgb(1, 1, 1)
            
            rect = (i * white_key_width, 0, white_key_width, height)
            self.key_rects.append((note, rect, 'white'))
            cr.rectangle(*rect)
            cr.fill_preserve()
            cr.set_source_rgb(0, 0, 0)
            cr.stroke()

        # Black keys
        black_key_width = white_key_width * 0.6
        black_key_height = height * 0.65
        for i in range(self.WHITE_KEY_COUNT):
            if (i % self.OCTAVE_SPAN) not in [2, 6]:
                octave, note_in_octave_idx = divmod(i, self.OCTAVE_SPAN)
                note = self.start_note + octave * 12 + white_notes[note_in_octave_idx] + 1
                
                if note in self.active_notes:
                    cr.set_source_rgb(0.7, 0.8, 1)
                else:
                    cr.set_source_rgb(0, 0, 0)

                rect = ((i + 1) * white_key_width - (black_key_width / 2), 0, black_key_width, black_key_height)
                self.key_rects.append((note, rect, 'black'))
                cr.rectangle(*rect)
                cr.fill()


    def on_pressed(self, gesture, n_press, x, y):
        note = self.note_from_pos(x, y)
        if note is not None:
            self.pressed_notes.add(note)
            self.emit('note-on', note)

    def on_released(self, gesture, n_press, x, y):
        # The release event doesn't give a reliable position, so we release all pressed notes
        for note in self.pressed_notes:
             self.emit('note-off', note)
        self.pressed_notes.clear()
    
    def note_from_pos(self, x, y):
        # Black keys are drawn on top, so check them first
        for note, rect, key_type in reversed(self.key_rects):
            if key_type == 'black':
                if x >= rect[0] and x <= rect[0] + rect[2] and y >= rect[1] and y <= rect[1] + rect[3]:
                    return note

        # Then check white keys
        for note, rect, key_type in self.key_rects:
            if key_type == 'white':
                if x >= rect[0] and x <= rect[0] + rect[2] and y >= rect[1] and y <= rect[1] + rect[3]:
                    return note
        
        return None


GObject.type_register(PianoWidget)

if __name__ == '__main__':
    win = Gtk.Window()
    piano = PianoWidget()
    piano.set_size_request(600, 100)

    def play_note(widget, note):
        print(f"Note on: {note}")
        widget.set_note_active(note)
    
    def stop_note(widget, note):
        print(f"Note off: {note}")
        widget.set_note_inactive(note)

    piano.connect('note-on', play_note)
    piano.connect('note-off', stop_note)
    win.set_child(piano)
    win.connect("destroy", Gtk.main_quit)
    win.show()
    Gtk.main()
