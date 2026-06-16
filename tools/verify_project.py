from __future__ import annotations

from pathlib import Path

import verify_core


ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = ROOT / "dist" / "HEA_MEA_Designer"
EXE_PATH = DIST_DIR / "HEA_MEA_Designer.exe"
INTERNAL_DIR = DIST_DIR / "_internal"
VERSION_PATH = ROOT / "VERSION"

RELEASE_DATA_FILES = ("data/final.lmp",)
RELEASE_MODEL_FILES = (
    "models/二维六边形多晶/final.lmp",
    "models/二维随机多晶/final.lmp",
    "models/二维梯度孪晶多晶/final.cfg",
    "models/倾斜孪晶多晶/final.cfg",
    "models/预存孪晶多晶/final.cfg",
    "models/双相多晶/final_polycrystal.cfg",
    "models/K-S取向多晶/final_Fe.lmp",
)
RELEASE_DOC_FILES = (
    "docs/README_GUI.md",
    "docs/使用教程.md",
    "docs/verification.md",
    "docs/data_sources.md",
)


def as_posix_relative(path: Path, base: Path = INTERNAL_DIR) -> str:
    return path.relative_to(base).as_posix()


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
    for path_name in (*RELEASE_DATA_FILES, *RELEASE_MODEL_FILES, *RELEASE_DOC_FILES):
        if path_name not in spec_text:
            raise SystemExit(f"[fail] HEA_MEA_Designer.spec does not include release file {path_name}")
        print(f"  OK spec includes release file {path_name}")
    forbidden_tokens = ("rglob", "video_script", "iteration_log.md", "reference", "generated")
    if any(token in spec_text for token in forbidden_tokens):
        raise SystemExit("[fail] HEA_MEA_Designer.spec includes non-release documentation")
    print("  OK spec uses a release whitelist")

    package_text = (ROOT / "package.bat").read_text(encoding="utf-8", errors="replace")
    for marker in ("backup_runtime", "restore_runtime", "config.json"):
        if marker not in package_text:
            raise SystemExit(f"[fail] package.bat missing runtime preservation marker: {marker}")
        print(f"  OK package.bat marker: {marker}")
    if "generated" in package_text:
        raise SystemExit("[fail] package.bat preserves generated runtime output")
    print("  OK package.bat does not preserve generated runtime output")


def validate_exact_internal_tree(folder_name: str, expected_files: tuple[str, ...]) -> None:
    root = INTERNAL_DIR / folder_name
    expected = sorted(expected_files)
    actual = sorted(as_posix_relative(path) for path in root.rglob("*") if path.is_file())
    if actual != expected:
        raise SystemExit(
            "[fail] packaged {folder}/ tree mismatch\nexpected:\n  {expected}\nactual:\n  {actual}".format(
                folder=folder_name,
                expected="\n  ".join(expected),
                actual="\n  ".join(actual),
            )
        )
    print(f"  OK packaged {folder_name}/ whitelist: {len(actual)} files")


def validate_dist_layout() -> None:
    print("[dist] checking packaged application layout")
    require_path(EXE_PATH, "packaged exe")
    if EXE_PATH.stat().st_size <= 1_000_000:
        raise SystemExit(f"[fail] packaged exe is unexpectedly small: {EXE_PATH.stat().st_size} bytes")
    require_path(INTERNAL_DIR / "data" / "final.lmp", "packaged default data")
    require_path(INTERNAL_DIR / "docs" / "README_GUI.md", "packaged README")
    require_path(INTERNAL_DIR / "docs" / "使用教程.md", "packaged user tutorial")
    require_path(INTERNAL_DIR / "docs" / "verification.md", "packaged verification doc")
    require_path(INTERNAL_DIR / "docs" / "data_sources.md", "packaged data source doc")
    require_path(INTERNAL_DIR / "models", "packaged model library")
    validate_exact_internal_tree("data", RELEASE_DATA_FILES)
    validate_exact_internal_tree("models", RELEASE_MODEL_FILES)
    validate_exact_internal_tree("docs", RELEASE_DOC_FILES)
    require_path(INTERNAL_DIR / "VERSION", "packaged version file")
    packaged_version = (INTERNAL_DIR / "VERSION").read_text(encoding="utf-8").strip()
    if packaged_version != read_version():
        raise SystemExit(f"[fail] packaged VERSION mismatch: {packaged_version!r}")
    print(f"  OK packaged version: {packaged_version}")
    runtime_config = DIST_DIR / "config.json"
    if runtime_config.exists():
        require_path(runtime_config, "runtime config")
    else:
        require_path(ROOT / "config.example.json", "runtime config template")
    if (DIST_DIR / "generated").exists():
        generated_files = [path for path in (DIST_DIR / "generated").rglob("*") if path.is_file()]
        if generated_files:
            raise SystemExit("[fail] packaged dist includes generated runtime output")
    print("  OK generated runtime output excluded")


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
