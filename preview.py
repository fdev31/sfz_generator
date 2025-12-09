#!/usr/bin/env python3
"""
Play a sequence of notes from an SFZ file using sfizz_render.
Configure notes and durations in the 'notes_sequence' array.
"""

from midiutil import MIDIFile
import subprocess
import os
import sys

def note_name_to_midi(note_name):
    """Convert note name (e.g., 'C4', 'D#5') to MIDI number."""
    notes = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}
    
    # Handle sharps and flats
    note = note_name[0].upper()
    octave = int(note_name[-1])
    
    if len(note_name) > 2 and note_name[1] in '#b':
        if note_name[1] == '#':
            pitch = notes[note] + 1
        else:  # flat
            pitch = notes[note] - 1
    else:
        pitch = notes[note]
    
    return (octave + 1) * 12 + pitch

def create_sequence_midi(notes_sequence, output_file='sequence.mid', tempo=120, velocity=100):
    """
    Create a MIDI file from a sequence of notes and durations.
    
    Args:
        notes_sequence: List of tuples (note, duration_in_beats)
                       Examples: [('C4', 1), ('D4', 0.5), ('E4', 2)]
                       OR list of tuples (midi_number, duration_in_beats)
                       Examples: [(60, 1), (62, 0.5), (64, 2)]
        output_file: Output MIDI filename
        tempo: Tempo in BPM (default 120)
        velocity: Note velocity 0-127 (default 100)
    """
    
    # Create MIDI file with 1 track
    midi = MIDIFile(1)
    track = 0
    channel = 0
    
    # Add tempo
    midi.addTempo(track, 0, tempo)
    
    # Calculate timing and add notes
    current_time = 0
    for note, duration in notes_sequence:
        # Convert note name to MIDI number if it's a string
        if isinstance(note, str):
            midi_note = note_name_to_midi(note)
        else:
            midi_note = note
        
        # Add note to MIDI file
        midi.addNote(track, channel, midi_note, current_time, duration, velocity)
        
        # Move to next note position
        current_time += duration
    
    # Write to file
    with open(output_file, 'wb') as f:
        midi.writeFile(f)
    
    print(f"✓ MIDI file created: {output_file}")
    return output_file

def play_sfz_sequence(sfz_file, notes_sequence, tempo=120, output_wav='preview.wav'):
    """
    Generate MIDI from notes sequence and render it with SFZ using sfizz_render.
    
    Args:
        sfz_file: Path to your .sfz file
        notes_sequence: List of tuples (note, duration_in_beats)
        tempo: Tempo in BPM
        output_wav: Output WAV filename
    """
    
    # Create temporary MIDI file
    midi_file = 'temp_sequence.mid'
    create_sequence_midi(notes_sequence, midi_file, tempo)
    
    # Render with sfizz_render
    try:
        print(f"✓ Rendering with sfizz_render...")
        cmd = ['sfizz_render', '--sfz', sfz_file, '--midi', midi_file, '--wav', output_wav]
        subprocess.run(cmd, check=True, capture_output=True)
        print(f"✓ Rendered: {output_wav}")
    except FileNotFoundError:
        print("✗ Error: sfizz_render not found. Install it with: sudo apt install sfizz")
        return False
    except subprocess.CalledProcessError as e:
        print(f"✗ Render error: {e.stderr.decode()}")
        return False
    
    # Play the WAV file
    try:
        print("▶ Playing...")
        # Try PulseAudio first, fall back to ALSA
        try:
            subprocess.run(['paplay', output_wav], check=True)
        except FileNotFoundError:
            subprocess.run(['aplay', output_wav], check=True)
    except FileNotFoundError:
        print("✗ No audio player found (paplay/aplay). Use your preferred player:")
        print(f"   paplay {output_wav}")
    
    # Clean up temp MIDI
    if os.path.exists(midi_file):
        os.remove(midi_file)
    
    return True

# ============================================================================
# CONFIGURATION: Define your note sequence here
# ============================================================================

# Format: (note_name_or_midi_number, duration_in_beats)
# Examples:
#   'C4', 'D#4', 'Eb5', 'G3'  (note names, octave 0-8)
#   60, 62, 65, 67            (MIDI numbers: 60=C4, middle C)

notes_sequence = [
    ('C4', 1),      # Middle C, 1 beat
    ('D4', 1),      # D, 1 beat
    ('E4', 1),      # E, 1 beat
    ('F4', 1),      # F, 1 beat
    ('G4', 2),      # G, 2 beats
    ('A4', 0.5),    # A, half beat
    ('B4', 0.5),    # B, half beat
    ('C5', 2),      # C, 2 beats
]

# You can also use MIDI numbers directly:
# notes_sequence = [
#     (60, 1),  # C4, 1 beat
#     (62, 1),  # D4, 1 beat
#     (64, 1),  # E4, 1 beat
#     (65, 1),  # F4, 1 beat
# ]

# ============================================================================
# SETUP
# ============================================================================

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 play_sfz.py <path_to_sfz_file>")
        print("\nExample:")
        print("  python3 play_sfz.py ./my_instrument.sfz")
        sys.exit(1)
    
    sfz_file = sys.argv[1]
    
    if not os.path.exists(sfz_file):
        print(f"✗ Error: SFZ file not found: {sfz_file}")
        sys.exit(1)
    
    print(f"SFZ file: {sfz_file}")
    print(f"Sequence: {notes_sequence}")
    print()
    
    # Play the sequence
    play_sfz_sequence(sfz_file, notes_sequence, tempo=120)

