# -*- mode: python ; coding: utf-8 -*-
# Windowed (no console) build of the QualtricsToLime GUI.
#   Windows:  pyinstaller QualtricsToLimeGUI.spec  -> dist/QualtricsToLimeGUI.exe
#   macOS:    pyinstaller QualtricsToLimeGUI.spec  -> dist/QualtricsToLimeGUI.app
# Drag & drop needs `pip install tkinterdnd2` before building; its native Tk
# extension is collected automatically via collect_data_files below.

import os
import sys
from PyInstaller.utils.hooks import collect_data_files

IS_MAC = sys.platform == 'darwin'
# Windows version resource (product name/version), written by tools/write_version_info.py
VERSION_FILE = os.environ.get('QTL_VERSION_FILE') or None

try:
    dnd_datas = collect_data_files("tkinterdnd2")
except Exception:
    dnd_datas = []

a = Analysis(
    ['source/gui.py'],
    pathex=['source'],
    binaries=[],
    datas=[('source/qsf_to_lss.py', '.'), ('source/qsf_inspector.py', '.'), ('source/app.py', '.')] + dnd_datas,
    hiddenimports=['tkinterdnd2'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

if not IS_MAC:
    # Windows / Linux: single-file executable
    exe = EXE(
        pyz, a.scripts, a.binaries, a.datas, [],
        name='QualtricsToLimeGUI',
        debug=False, strip=False, upx=True,
        console=False,           # windowed: no terminal window
        disable_windowed_traceback=False,
        version=VERSION_FILE,
        target_arch=None, codesign_identity=None, entitlements_file=None,
    )
else:
    # macOS: a .app bundle must be a folder, so build onedir and wrap it
    exe = EXE(
        pyz, a.scripts, [],
        exclude_binaries=True,
        name='QualtricsToLimeGUI',
        debug=False, strip=False, upx=False,
        console=False,
        argv_emulation=True,     # files dropped on the .app icon arrive in sys.argv
        target_arch=None, codesign_identity=None, entitlements_file=None,
    )
    coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='QualtricsToLimeGUI')
    app = BUNDLE(
        coll,
        name='QualtricsToLimeGUI.app',
        icon=None,
        bundle_identifier='de.konradschweizer.qualtricstolime',
        info_plist={
            'CFBundleDocumentTypes': [{
                'CFBundleTypeExtensions': ['qsf'],
                'CFBundleTypeName': 'Qualtrics Survey File',
                'CFBundleTypeRole': 'Viewer',
            }],
            'NSHighResolutionCapable': True,
        },
    )
