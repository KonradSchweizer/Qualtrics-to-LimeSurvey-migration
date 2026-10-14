#!/usr/bin/env python3
"""Write a PyInstaller Windows version resource (product name + version metadata).

Usage: python tools/write_version_info.py v1.2.0 build/version_info.txt

Code signing via SignPath requires every signed .exe to carry the product name
"QSF2LSS" and the same product version, so both executables are built
with the file this script writes.
"""
import re
import sys
from pathlib import Path

tag = sys.argv[1] if len(sys.argv) > 1 else "0.0.0"
out = Path(sys.argv[2] if len(sys.argv) > 2 else "build/version_info.txt")
major, minor, patch = ([int(n) for n in re.findall(r"\d+", tag)[:3]] + [0, 0, 0])[:3]
version = f"{major}.{minor}.{patch}"

out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers=({major}, {minor}, {patch}, 0), prodvers=({major}, {minor}, {patch}, 0),
                    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Konrad Schweizer'),
      StringStruct('FileDescription', 'QSF2LSS - Qualtrics (.qsf) to LimeSurvey (.lss) converter'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('LegalCopyright', 'Copyright (c) 2026 Konrad Schweizer. MIT License.'),
      StringStruct('ProductName', 'QSF2LSS'),
      StringStruct('ProductVersion', '{version}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""", encoding="utf-8")
print(f"wrote {out} ({version})")
