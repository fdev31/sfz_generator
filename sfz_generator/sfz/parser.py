import re
import os

def parse_sfz_file(sfz_path):
    """
    Parses an SFZ file and returns a dictionary of opcodes 
    and the resolved path to the sample file.
    """
    try:
        with open(sfz_path, 'r') as f:
            content = f.read()
        
        sfz_data = parse_sfz_content(content)

        sample_path = None
        if 'sample' in sfz_data:
            sample = sfz_data['sample']
            if os.path.isabs(sample):
                sample_path = sample
            else:
                sfz_dir = os.path.dirname(sfz_path)
                sample_path = os.path.join(sfz_dir, sample)
        
        return sfz_data, sample_path, None

    except Exception as e:
        return None, None, str(e)


def parse_sfz_content(content):
    # Initialize data dictionary
    sfz_data = {}

    # Remove comments and split into lines
    lines = []
    for line in content.split("\n"):
        # Remove comments
        line = re.sub(r"//.*$", "", line)
        line = re.sub(r"#.*$", "", line)
        line = line.strip()
        if line:
            lines.append(line)

    # Parse opcodes
    current_section = None
    for line in lines:
        line = line.strip()

        # Check for section headers
        if line.startswith("<") and line.endswith(">"):
            current_section = line[1:-1]
            continue

        # Parse opcode=value pairs
        if "=" in line:
            opcode, value = line.split("=", 1)
            opcode = opcode.strip().lower()
            value = value.strip()

            # Store only the first region's opcodes
            if current_section == "region":
                sfz_data[opcode] = value

    return sfz_data
