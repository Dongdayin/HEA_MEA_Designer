# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


BASE_DIR = Path.cwd()
datas = []

release_files = [
    ("VERSION", "."),
    ("data/final.lmp", "data"),
    ("models/二维六边形多晶/final.lmp", "models/二维六边形多晶"),
    ("models/二维随机多晶/final.lmp", "models/二维随机多晶"),
    ("models/二维梯度孪晶多晶/final.cfg", "models/二维梯度孪晶多晶"),
    ("models/倾斜孪晶多晶/final.cfg", "models/倾斜孪晶多晶"),
    ("models/预存孪晶多晶/final.cfg", "models/预存孪晶多晶"),
    ("models/双相多晶/final_polycrystal.cfg", "models/双相多晶"),
    ("models/K-S取向多晶/final_Fe.lmp", "models/K-S取向多晶"),
    ("docs/README_GUI.md", "docs"),
    ("docs/使用教程.md", "docs"),
    ("docs/verification.md", "docs"),
    ("docs/data_sources.md", "docs"),
]
for source_name, destination in release_files:
    source = BASE_DIR / source_name
    if source.exists():
        datas.append((str(source), destination))


a = Analysis(
    ['hea_mea_designer.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[],
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
    [],
    exclude_binaries=True,
    name='HEA_MEA_Designer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='HEA_MEA_Designer',
)
