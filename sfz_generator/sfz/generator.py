import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from sfz_generator.audio.processing import process_midi_note


def generate_pitch_shifted_instrument(
    output_dir, audio_file_path, pitch_keycenter, low_key, high_key, sample_rate, extra_definitions: list[str],
    progress_callback=None
):
    """Generates a pitch-shifted SFZ instrument.
    """
    try:
        samples_dir_name = "samples"
        samples_dir_path = os.path.join(output_dir, samples_dir_name)
        os.makedirs(samples_dir_path, exist_ok=True)

        tasks = [(audio_file_path, samples_dir_path, midi, pitch_keycenter, sample_rate) for midi in range(low_key, high_key + 1)]
        
        results = []
        num_total = len(tasks)
        with ThreadPoolExecutor(max_workers=os.cpu_count()) as executor:
            futures = {executor.submit(process_midi_note, task): task for task in tasks}
            
            for i, future in enumerate(as_completed(futures)):
                if progress_callback:
                    progress_callback(i + 1, num_total)
                midi, note_name, success, error = future.result()
                if not success:
                    print(f"Failed to generate {note_name}: {error}")
                results.append((midi, note_name, success))

        successful_notes = [(midi, note_name) for midi, note_name, success in sorted(results) if success]
        
        if not successful_notes:
            return None, 0, num_total

        sfz_lines = ["<control>", f"default_path={samples_dir_name}", "<global>"] +  extra_definitions + [ "<group>"]

        for midi, note_name in successful_notes:
            out_wav = f"{note_name}.wav"
            sfz_lines.append(f"<region> sample={out_wav} key={midi} pitch_keycenter={midi}")

        sfz_content = "\n".join(sfz_lines) + "\n"

        sfz_path = os.path.join(output_dir, "instrument.sfz")
        with open(sfz_path, "w") as f:
            f.write(sfz_content)
        
        return sfz_path, len(successful_notes), num_total
    except Exception as e:
        print(f"Error during pitch-shifted generation: {e}")
        return None, 0, 0


def get_simple_sfz_content(audio_file_path, pitch_keycenter, extra_defs: list[str]):
    """Generates the content for a simple SFZ file.
    """
    if audio_file_path is None:
        return "// No audio file loaded"

    sfz_content = []
    sfz_content.append("<group>")
    sfz_content.append("<region>")
    sfz_content.append(f"sample={audio_file_path}")
    sfz_content.append(f"pitch_keycenter={int(pitch_keycenter)}")
    
    if extra_defs:
        sfz_content.extend(extra_defs)

    return "\n".join(sfz_content)
