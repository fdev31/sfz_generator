#!/usr/bin/env python3
import gi, sys, os

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw
from sfz_generator.gui.main_window import SFZGenerator

class SFZGeneratorApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id="com.example.sfzgenerator")

    def do_activate(self):
        win = SFZGenerator(application=self)
        win.present()


def main():
    app = SFZGeneratorApp()
    app.run(sys.argv)

if __name__ == "__main__":
    main()
