# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build: one folder with Vox.exe, the runtime and the models."""

from pathlib import Path

ROOT = Path(SPECPATH).resolve()
MODELS = ROOT / "models"
ASSETS = ROOT / "assets"

REQUIRED = [
    "enroll.onnx",
    "enroll_fp16.onnx",
    "chunk_int8.onnx",
    "chunk_fp16.onnx",
    "config.yaml",
    "LICENSE",
    "NOTICE",
]
missing = [name for name in REQUIRED if not (MODELS / name).is_file()]
if missing:
    raise SystemExit(
        "Model files are missing from models/: "
        + ", ".join(missing)
        + "\nRun: .venv\\Scripts\\python tools\\fetch_models.py"
    )

a = Analysis(
    ["run.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(MODELS), "models"),
        (str(ASSETS), "assets"),
    ],
    hiddenimports=["voxlock.core"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtQuickWidgets",
        "PySide6.QtWebEngineCore",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Vox",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ASSETS / "icon.ico"),
    version=str(ROOT / "installer" / "version_info.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Vox",
)
