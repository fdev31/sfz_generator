#!/usr/bin/env python3
"""
Play a sequence of notes from an SFZ file using sfizz_render.
"""

from midiutil import MIDIFile
import subprocess
import os
import tempfile
import sounddevice as sd
import soundfile as sf


def note_name_to_midi(note_name):
    """Convert note name (e.g., 'C4', 'D#5') to MIDI number."""
    notes = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}

    # Handle sharps and flats
    note = note_name[0].upper()
    octave = int(note_name[-1])

    if len(note_name) > 2 and note_name[1] in "#b":
        if note_name[1] == "#":
            pitch = notes[note] + 1
        else:  # flat
            pitch = notes[note] - 1
    else:
        pitch = notes[note]

    return (octave + 1) * 12 + pitch


def create_sequence_midi(notes_sequence, output_file="sequence.mid", tempo=120, velocity=100):
    """
    Create a MIDI file from a sequence of notes and durations.

    Args:
        notes_sequence: List of tuples (note, duration_in_beats)
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
        if isinstance(note, str):
            midi_note = note_name_to_midi(note)
        else:
            midi_note = note

        midi.addNote(track, channel, midi_note, current_time, duration, velocity)
        current_time += duration

    with open(output_file, "wb") as f:
        midi.writeFile(f)

    return output_file


def play_sfz_note(sfz_content, instrument_base_dir, note, duration_beats, lock, stop_event):
    """
    Generate MIDI for a single note and play it with sfizz_render,
    respecting different loop modes with interruptible, chunked playback.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        sfz_file = os.path.join(tmpdir, "preview.sfz")
        with open(sfz_file, "w") as f:
            f.write(sfz_content)

        midi_file = os.path.join(tmpdir, "temp_sequence.mid")
        output_wav = os.path.join(tmpdir, "preview.wav")

        create_sequence_midi([(note, duration_beats)], midi_file)

        try:
            cmd = ["sfizz_render", "--sfz", sfz_file, "--midi", midi_file, "--wav", output_wav]
            subprocess.run(cmd, check=True, capture_output=True, cwd=instrument_base_dir)
        except (FileNotFoundError, subprocess.CalledProcessError) as e:
            print(f"Error rendering note: {e}")
            return

        try:
            with lock:
                data, samplerate = sf.read(output_wav, dtype="float32")

                with sd.OutputStream(samplerate=samplerate, channels=data.shape[1] if data.ndim > 1 else 1, dtype="float32") as stream:
                    # --- Parse loop_mode ---
                    loop_mode = "no_loop"  # default
                    if "loop_mode=one_shot" in sfz_content:
                        loop_mode = "one_shot"
                    elif "loop_mode=loop_sustain" in sfz_content:
                        loop_mode = "loop_sustain"
                    elif "loop_mode=loop_continuous" in sfz_content:
                        loop_mode = "loop_continuous"

                    # --- Playback logic ---
                    frames_per_chunk = 1024

                    def as_frames(buffer):
                        return buffer.reshape(-1, 1) if (buffer.ndim == 1) else buffer

                    frames = as_frames(data)
                    total_frames = len(frames)

                    def play_chunked(stream, frames_to_play, stop_event):
                        current_frame = 0
                        while current_frame < total_frames and not stop_event.is_set():
                            chunk_end = min(current_frame + frames_per_chunk, total_frames)
                            stream.write(frames_to_play[current_frame:chunk_end])
                            current_frame = chunk_end

                    if loop_mode in ["one_shot", "loop_continuous"]:
                        # These modes ignore note-off. Play the full rendered buffer.
                        # sfizz_render handles making the sound loop for loop_continuous.
                        stream.write(frames)

                    elif loop_mode == "loop_sustain":
                        play_chunked(stream, frames, stop_event)
                        while not stop_event.is_set():
                            play_chunked(stream, frames, stop_event)

                    else:  # no_loop (default)
                        play_chunked(stream, frames, stop_event)

                    if stop_event.is_set():
                        stream.abort(ignore_xruns=True)

        except Exception as e:
            print(f"Error playing audio: {e}")
