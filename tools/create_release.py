from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = ROOT / "dist" / "HEA_MEA_Designer"
RELEASES_DIR = ROOT / "releases"


def read_version() -> str:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if not version:
        raise SystemExit("VERSION is empty")
    return version


def run_command(command: list[str]) -> str:
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, env=os.environ.copy(), check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise SystemExit(f"command failed: {' '.join(command)}\n{detail}")
    return result.stdout.strip()


def current_commit() -> str:
    try:
        return run_command(["git", "rev-parse", "--short", "HEAD"])
    except SystemExit:
        return "unknown"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dist_files() -> list[Path]:
    if not DIST_DIR.exists():
        raise SystemExit(f"missing packaged app: {DIST_DIR}")
    return sorted((path for path in DIST_DIR.rglob("*") if path.is_file()), key=lambda path: path.relative_to(DIST_DIR).as_posix().lower())


def build_manifest(version: str, commit: str, files: list[Path]) -> str:
    lines = [
        "HEA_MEA_Designer release manifest",
        f"Version: {version}",
        f"Git commit: {commit}",
        f"Created at: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"Source dist: {DIST_DIR}",
        "",
        "SHA256                                                        Size         Path",
    ]
    for path in files:
        relative = path.relative_to(DIST_DIR).as_posix()
        lines.append(f"{sha256_file(path)}  {path.stat().st_size:>12}  {relative}")
    lines.append("")
    return "\n".join(lines)


def build_release_notes(version: str, commit: str, archive_name: str) -> str:
    return "\n".join(
        [
            f"HEA_MEA_Designer v{version}",
            "",
            "Target: Windows 64-bit",
            "Entry point: HEA_MEA_Designer.exe",
            f"Git commit: {commit}",
            f"Archive: {archive_name}",
            "",
            "Distribution checklist:",
            "- Run HEA_MEA_Designer.exe from the extracted folder.",
            "- Keep the _internal directory beside the executable.",
            "- Keep config.json and generated/ if preserving local runtime state.",
            "- Verify the archive with the matching .sha256 file before sharing.",
            "",
        ]
    )


def create_release(skip_verify: bool = False) -> tuple[Path, Path, Path]:
    version = read_version()
    commit = current_commit()
    base_name = f"HEA_MEA_Designer-v{version}-win64"
    archive_path = RELEASES_DIR / f"{base_name}.zip"
    sha_path = RELEASES_DIR / f"{base_name}.sha256"
    manifest_path = RELEASES_DIR / f"{base_name}-manifest.txt"
    notes_path = RELEASES_DIR / f"{base_name}-release-notes.txt"

    RELEASES_DIR.mkdir(parents=True, exist_ok=True)
    if not skip_verify:
        print("[verify] running project verification")
        run_command([sys.executable, str(ROOT / "tools" / "verify_project.py")])

    files = dist_files()
    manifest = build_manifest(version, commit, files)
    notes = build_release_notes(version, commit, archive_path.name)

    for path in (archive_path, sha_path, manifest_path, notes_path):
        if path.exists():
            path.unlink()

    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
        archive.writestr(f"{base_name}/MANIFEST.txt", manifest)
        archive.writestr(f"{base_name}/RELEASE_NOTES.txt", notes)
        for path in files:
            relative = path.relative_to(DIST_DIR).as_posix()
            archive.write(path, f"{base_name}/{relative}")

    archive_hash = sha256_file(archive_path)
    sha_path.write_text(f"{archive_hash}  {archive_path.name}\n", encoding="utf-8")
    manifest_path.write_text(manifest, encoding="utf-8")
    notes_path.write_text(notes, encoding="utf-8")
    print(f"[done] archive: {archive_path}")
    print(f"[done] sha256:  {sha_path}")
    print(f"[done] manifest: {manifest_path}")
    print(f"[done] notes:    {notes_path}")
    return archive_path, sha_path, manifest_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a verified HEA_MEA_Designer release archive.")
    parser.add_argument("--skip-verify", action="store_true", help="Create the archive without running tools/verify_project.py first.")
    args = parser.parse_args()
    create_release(skip_verify=args.skip_verify)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
