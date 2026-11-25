# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Nova Assistant (single-file desktop executable).

Build with:  pyinstaller NovaAssistant.spec
Result:      dist/NovaAssistant(.exe)
"""

from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = [
    "plyer.platforms.win.notification",
    "plyer.platforms.linux.notification",
    "plyer.platforms.macosx.notification",
]

for pkg in ("sounddevice", "soundfile", "plyer", "pypdf"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "pandas", "IPython", "jupyter"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="NovaAssistant",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # windowed desktop app - no terminal
    disable_windowed_traceback=False,
    icon=None,              # optional: drop icon.ico here and set icon="icon.ico"
)
