from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILES = [
    ROOT / "hea_mea_designer.py",
    ROOT / "hea_mea_gui.py",
    ROOT / "tests" / "test_core_logic.py",
    ROOT / "tools" / "verify_core.py",
    ROOT / "tools" / "verify_project.py",
    ROOT / "tools" / "create_release.py",
]


def compile_sources() -> None:
    print("[compile] checking Python source syntax")
    for path in SOURCE_FILES:
        source = path.read_text(encoding="utf-8")
        compile(source, str(path), "exec")
        print(f"  OK {path.relative_to(ROOT)}")


def run_unit_tests() -> None:
    print("[tests] running unittest discovery")
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
    result = unittest.TextTestRunner(stream=sys.stdout, verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)


def validate_lammps_assets() -> None:
    print("[assets] reading bundled LAMMPS data files")
    sys.path.insert(0, str(ROOT))
    sys.dont_write_bytecode = True
    import hea_mea_designer as app

    paths = sorted(list((ROOT / "data").rglob("*.lmp")) + list((ROOT / "models").rglob("*.lmp")))
    failures: list[tuple[Path, Exception]] = []
    for path in paths:
        try:
            structure = app.read_lammps_structure(path)
            print(f"  OK {path.relative_to(ROOT)} atoms={len(structure.atoms)} types={structure.atom_types}")
        except Exception as exc:
            failures.append((path, exc))
            print(f"  FAIL {path.relative_to(ROOT)}: {exc}")
    if failures:
        raise SystemExit(1)


def main() -> int:
    compile_sources()
    run_unit_tests()
    validate_lammps_assets()
    print("[done] core verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
