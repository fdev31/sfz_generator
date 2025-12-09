NOTES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

def midi_to_name(midi):
    octave = (midi // 12) - 1
    note = NOTES[midi % 12]
    return f"{note}{octave}"
