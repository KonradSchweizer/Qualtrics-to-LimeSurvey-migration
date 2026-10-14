# Third-party components

The QSF2LSS source code is MIT-licensed (see `LICENSE`). The downloadable
executables also bundle the following open-source components. Each one keeps its own license:

| Component | Used for | License |
|---|---|---|
| [Python](https://www.python.org/) runtime and standard library | Runs the converter | [PSF License](https://docs.python.org/3/license.html) |
| [Tcl/Tk](https://www.tcl-lang.org/) (via Python's `tkinter`) | The window (GUI) | [Tcl/Tk license (BSD-style)](https://www.tcl-lang.org/software/tcltk/license.html) |
| [PyInstaller](https://pyinstaller.org/) bootloader | Packs everything into one executable | [GPL 2.0 with bootloader exception](https://github.com/pyinstaller/pyinstaller/blob/develop/COPYING.txt), which allows distributing bundled programs under any license |
| [tkinterdnd2](https://github.com/Eliav2/tkinterdnd2) | Drag & drop (GUI only) | [MIT](https://github.com/Eliav2/tkinterdnd2/blob/master/LICENSE) |
| [tkdnd](https://github.com/petasis/tkdnd) | Native drag & drop extension used by tkinterdnd2 (GUI only) | [BSD-style (Tcl license terms)](https://github.com/petasis/tkdnd/blob/master/license.terms) |

The project website (`docs/`) self-hosts the fonts [Fraunces](https://github.com/undercasetype/Fraunces),
[Instrument Sans](https://github.com/Instrument/instrument-sans) and
[JetBrains Mono](https://github.com/JetBrains/JetBrainsMono), all under the
[SIL Open Font License 1.1](https://openfontlicense.org/).

"Qualtrics" and "LimeSurvey" are trademarks of their respective owners. This project is
independent. It is not affiliated with, endorsed by or sponsored by either of them.
