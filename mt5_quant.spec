# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


project_dir = Path.cwd()
datas = [
    (str(project_dir / "README.md"), "."),
    (str(project_dir / "config.example.yaml"), "."),
    (str(project_dir / "config.xauusd.m1.yaml"), "."),
    (str(project_dir / "config.btcusd.m15.yaml"), "."),
    (str(project_dir / "config.btcusd.m15.offline.yaml"), "."),
    (str(project_dir / "mql5"), "mql5"),
    (str(project_dir / "sample_mt5_calendar.csv"), "."),
    (str(project_dir / "templates"), "templates"),
]


a = Analysis(
    ["src/mt5_quant/cli.py"],
    pathex=[str(project_dir / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "MetaTrader5",
        "mt5_quant.gui",
        "mt5_quant.launcher_profiles",
        "tkinter",
        "tkinter.ttk",
        "tkinter.filedialog",
        "tkinter.messagebox",
    ],
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
    name="mt5-quant",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
