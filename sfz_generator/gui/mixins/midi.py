import os
import tempfile
from gi.repository import GLib

class MidiMixin:
    def populate_midi_devices(self):
        self.midi_device_combo.remove_all()
        self.midi_device_combo.append_text("None")
        self.midi_device_combo.set_active(0)
        ports = self.jack_client.get_midi_ports()
        for port in ports:
            self.midi_device_combo.append_text(port.name)

    def on_midi_device_changed(self, combo):
        text = combo.get_active_text()
        if text == "None":
            if self.selected_midi_port:
                self.jack_client.disconnect(self.selected_midi_port)
            self.selected_midi_port = None
            self.jack_client.stop_preview()
        else:
            self.selected_midi_port = text
            self.restart_preview()

    def restart_preview(self):
        if not self.selected_midi_port:
            return

        if self.generated_instrument_path:
            instrument_dir = os.path.dirname(self.generated_instrument_path)
            self.jack_client.start_preview(self.generated_instrument_path, cwd=instrument_dir)
            self.jack_client.connect(self.selected_midi_port)
        else:
            sfz_content = self.sfz_buffer.get_text(
                self.sfz_buffer.get_start_iter(),
                self.sfz_buffer.get_end_iter(),
                True,
            )
            
            with tempfile.NamedTemporaryFile(mode='w', suffix=".sfz", delete=False) as temp_sfz:
                temp_sfz.write(sfz_content)
                temp_sfz_path = temp_sfz.name

            self.jack_client.start_preview(temp_sfz_path)
            self.jack_client.connect(self.selected_midi_port)
            
            GLib.timeout_add(2000, os.unlink, temp_sfz_path)
