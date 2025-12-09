import numpy as np
import soundfile as sf
import os
import librosa
from sfz_generator.utils import midi_to_name

def load_audio(file_path):
    """Loads an audio file, converts it to mono, and returns data and sample rate."""
    try:
        audio_data, sample_rate = sf.read(file_path)
        # Convert to mono if stereo
        if len(audio_data.shape) > 1:
            audio_data = np.mean(audio_data, axis=1)
        
        # Normalize to 16-bit integer range for playback
        audio_data_int16 = (audio_data * 32767).astype(np.int16)
        
        return audio_data, audio_data_int16, sample_rate, None
    except Exception as e:
        return None, None, None, str(e)

def process_midi_note(args):
    """Generate pitch-shifted sample for a single MIDI note using librosa."""
    inp, out_dir, midi, root, sr = args
    
    semitones = midi - root
    note_name = midi_to_name(midi)
    out_wav = f"{note_name}.wav"
    out_path = os.path.join(out_dir, out_wav)

    try:
        y, loaded_sr = librosa.load(inp, sr=sr)
        
        # Pitch shift
        y_shifted = librosa.effects.pitch_shift(y, sr=loaded_sr, n_steps=float(semitones))
        
        sf.write(out_path, y_shifted, loaded_sr)
        return (midi, note_name, True, None)
    except Exception as e:
        return (midi, note_name, False, str(e))
