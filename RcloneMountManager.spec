# -*- mode: python ; coding: utf-8 -*-
import subprocess
from pathlib import Path

# Resolve version from git or environment for the build
build_version = "1.2.0"
try:
    res = subprocess.run(
        ["git", "describe", "--tags", "--always"],
        capture_output=True,
        text=True,
        check=False,
    )
    if res.returncode == 0 and res.stdout.strip():
        tag = res.stdout.strip()
        build_version = tag[1:] if tag.lower().startswith("v") else tag
except Exception:
    pass

# Write _version.py and version.txt so PyInstaller packages it
Path("_version.py").write_text(f'__version__ = "{build_version}"\n', encoding="utf-8")
Path("version.txt").write_text(f"{build_version}\n", encoding="utf-8")

a = Analysis(
    ['RcloneMountManager.py'],
    pathex=[],
    binaries=[],
    datas=[('icon.ico', '.'), ('version.txt', '.')],
    hiddenimports=['_version'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='RcloneMountManager',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['icon.ico'],
)
