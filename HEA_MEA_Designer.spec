# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


BASE_DIR = Path.cwd()
datas = []
version_file = BASE_DIR / "VERSION"
if version_file.exists():
    datas.append((str(version_file), "."))
for folder_name in ["data", "models"]:
    folder = BASE_DIR / folder_name
    if folder.exists():
        for source in folder.rglob("*"):
            if source.is_file():
                relative_parent = source.relative_to(folder).parent
                destination = Path(folder_name) / relative_parent
                datas.append((str(source), str(destination)))
docs_dir = BASE_DIR / "docs"
release_docs = ["README_GUI.md", "使用教程.md", "verification.md"]
for doc_name in release_docs:
    source = docs_dir / doc_name
    if source.exists():
        datas.append((str(source), "docs"))


a = Analysis(
    ['hea_mea_designer.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=['matplotlib.backends.backend_tkagg'],
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
