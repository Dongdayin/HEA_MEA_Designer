from __future__ import annotations

from pathlib import Path

import verify_core


ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = ROOT / "dist" / "HEA_MEA_Designer"
EXE_PATH = DIST_DIR / "HEA_MEA_Designer.exe"
INTERNAL_DIR = DIST_DIR / "_internal"
VERSION_PATH = ROOT / "VERSION"


def read_version() -> str:
    version = VERSION_PATH.read_text(encoding="utf-8").strip()
    if not version:
        raise SystemExit("[fail] VERSION is empty")
    return version


def require_path(path: Path, label: str) -> None:
    if not path.exists():
        raise SystemExit(f"[fail] missing {label}: {path}")
    print(f"  OK {label}: {path.relative_to(ROOT)}")


def validate_packaging_rules() -> None:
    print("[packaging] checking packaging rules")
    version = read_version()
    print(f"  OK project version: {version}")
    spec_text = (ROOT / "HEA_MEA_Designer.spec").read_text(encoding="utf-8")
    if "VERSION" not in spec_text:
        raise SystemExit("[fail] HEA_MEA_Designer.spec does not include VERSION")
    print("  OK spec includes VERSION")
    for folder_name in ("data", "models"):
        if f'"{folder_name}"' not in spec_text:
            raise SystemExit(f"[fail] HEA_MEA_Designer.spec does not include {folder_name}/")
        print(f"  OK spec includes {folder_name}/")
    for doc_name in ("README_GUI.md", "使用教程.md", "verification.md"):
        if doc_name not in spec_text:
            raise SystemExit(f"[fail] HEA_MEA_Designer.spec does not include release doc {doc_name}")
        print(f"  OK spec includes release doc {doc_name}")
    if "video_script" in spec_text or "iteration_log.md" in spec_text:
        raise SystemExit("[fail] HEA_MEA_Designer.spec includes non-release documentation")
    print("  OK spec excludes private/history docs")

    package_text = (ROOT / "package.bat").read_text(encoding="utf-8", errors="replace")
    for marker in ("backup_runtime", "restore_runtime", "config.json", "generated"):
        if marker not in package_text:
            raise SystemExit(f"[fail] package.bat missing runtime preservation marker: {marker}")
        print(f"  OK package.bat marker: {marker}")


def validate_dist_layout() -> None:
    print("[dist] checking packaged application layout")
    require_path(EXE_PATH, "packaged exe")
    if EXE_PATH.stat().st_size <= 1_000_000:
        raise SystemExit(f"[fail] packaged exe is unexpectedly small: {EXE_PATH.stat().st_size} bytes")
    require_path(INTERNAL_DIR / "data" / "final.lmp", "packaged default data")
    require_path(INTERNAL_DIR / "docs" / "README_GUI.md", "packaged README")
    require_path(INTERNAL_DIR / "docs" / "使用教程.md", "packaged user tutorial")
    require_path(INTERNAL_DIR / "docs" / "verification.md", "packaged verification doc")
    forbidden_docs = (
        INTERNAL_DIR / "docs" / "iteration_log.md",
        INTERNAL_DIR / "docs" / "video_script_v1.3.2.md",
        INTERNAL_DIR / "docs" / "video_script_v1.3.3.md",
    )
    for path in forbidden_docs:
        if path.exists():
            raise SystemExit(f"[fail] non-release doc was packaged: {path.relative_to(ROOT)}")
    print("  OK non-release docs excluded")
    require_path(INTERNAL_DIR / "models", "packaged model library")
    require_path(INTERNAL_DIR / "VERSION", "packaged version file")
    packaged_version = (INTERNAL_DIR / "VERSION").read_text(encoding="utf-8").strip()
    if packaged_version != read_version():
        raise SystemExit(f"[fail] packaged VERSION mismatch: {packaged_version!r}")
    print(f"  OK packaged version: {packaged_version}")
    require_path(DIST_DIR / "config.json", "runtime config")
    require_path(DIST_DIR / "generated", "generated runtime directory")
    generated_files = [path for path in (DIST_DIR / "generated").rglob("*") if path.is_file()]
    if not generated_files:
        raise SystemExit("[fail] generated runtime directory is empty")
    print(f"  OK generated runtime files: {len(generated_files)}")


def validate_packaged_lammps_assets() -> None:
    print("[dist-assets] reading packaged LAMMPS data files")
    import hea_mea_designer as app

    paths = sorted(list((INTERNAL_DIR / "data").rglob("*.lmp")) + list((INTERNAL_DIR / "models").rglob("*.lmp")))
    if not paths:
        raise SystemExit("[fail] packaged app contains no .lmp assets")
    failures: list[tuple[Path, Exception]] = []
    for path in paths:
        try:
            structure = app.read_lammps_structure(path)
            print(f"  OK {path.relative_to(DIST_DIR)} atoms={len(structure.atoms)} types={structure.atom_types}")
        except Exception as exc:
            failures.append((path, exc))
            print(f"  FAIL {path.relative_to(DIST_DIR)}: {exc}")
    if failures:
        raise SystemExit(1)


def main() -> int:
    verify_core.main()
    validate_packaging_rules()
    validate_dist_layout()
    validate_packaged_lammps_assets()
    print("[done] project verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
