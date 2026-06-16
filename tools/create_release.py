from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = ROOT / "dist" / "HEA_MEA_Designer"
RELEASES_DIR = ROOT / "releases"
SANITIZED_CONFIG_SOURCE = ROOT / "config.example.json"
ALLOWED_INTERNAL_FILES = {
    "VERSION",
    "data/final.lmp",
    "docs/README_GUI.md",
    "docs/使用教程.md",
    "docs/verification.md",
    "docs/data_sources.md",
    "models/二维六边形多晶/final.lmp",
    "models/二维随机多晶/final.lmp",
    "models/二维梯度孪晶多晶/final.cfg",
    "models/倾斜孪晶多晶/final.cfg",
    "models/预存孪晶多晶/final.cfg",
    "models/双相多晶/final_polycrystal.cfg",
    "models/K-S取向多晶/final_Fe.lmp",
}


@dataclass(frozen=True)
class ReleaseEntry:
    archive_path: str
    source_path: Path
    data: bytes | None = None


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


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def dist_files() -> list[Path]:
    if not DIST_DIR.exists():
        raise SystemExit(f"missing packaged app: {DIST_DIR}")
    return sorted((path for path in DIST_DIR.rglob("*") if path.is_file()), key=lambda path: path.relative_to(DIST_DIR).as_posix().lower())


def release_entries() -> list[ReleaseEntry]:
    entries: list[ReleaseEntry] = []
    has_runtime_config = False
    for path in dist_files():
        relative = path.relative_to(DIST_DIR).as_posix()
        if relative.startswith("generated/"):
            continue
        if relative == "config.json":
            if not SANITIZED_CONFIG_SOURCE.exists():
                raise SystemExit(f"missing sanitized config source: {SANITIZED_CONFIG_SOURCE}")
            entries.append(ReleaseEntry(relative, SANITIZED_CONFIG_SOURCE, SANITIZED_CONFIG_SOURCE.read_bytes()))
            has_runtime_config = True
        elif relative == "_internal/VERSION" or relative.startswith(("_internal/data/", "_internal/docs/", "_internal/models/")):
            internal_relative = relative.removeprefix("_internal/")
            if internal_relative not in ALLOWED_INTERNAL_FILES:
                raise SystemExit(f"non-release internal file found in dist: {relative}")
            entries.append(ReleaseEntry(relative, path))
        else:
            entries.append(ReleaseEntry(relative, path))
    if not has_runtime_config:
        if not SANITIZED_CONFIG_SOURCE.exists():
            raise SystemExit(f"missing sanitized config source: {SANITIZED_CONFIG_SOURCE}")
        entries.append(ReleaseEntry("config.json", SANITIZED_CONFIG_SOURCE, SANITIZED_CONFIG_SOURCE.read_bytes()))
    return entries


def entry_size(entry: ReleaseEntry) -> int:
    if entry.data is not None:
        return len(entry.data)
    return entry.source_path.stat().st_size


def entry_sha256(entry: ReleaseEntry) -> str:
    if entry.data is not None:
        return sha256_bytes(entry.data)
    return sha256_file(entry.source_path)


def build_manifest(version: str, commit: str, entries: list[ReleaseEntry]) -> str:
    lines = [
        "HEA_MEA_Designer release manifest",
        f"Version: {version}",
        f"Git commit: {commit}",
        f"Created at: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"Source dist: {DIST_DIR}",
        f"Distribution config source: {SANITIZED_CONFIG_SOURCE}",
        "",
        "SHA256                                                        Size         Path",
    ]
    for entry in entries:
        lines.append(f"{entry_sha256(entry)}  {entry_size(entry):>12}  {entry.archive_path}")
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
            "- The packaged config.json is copied from config.example.json and does not contain local machine paths.",
            "- Runtime output is created under generated/ after first use and is not included in the release archive.",
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

    entries = release_entries()
    manifest = build_manifest(version, commit, entries)
    notes = build_release_notes(version, commit, archive_path.name)

    for path in (archive_path, sha_path, manifest_path, notes_path):
        if path.exists():
            path.unlink()

    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
        archive.writestr(f"{base_name}/MANIFEST.txt", manifest)
        archive.writestr(f"{base_name}/RELEASE_NOTES.txt", notes)
        for entry in entries:
            archive_member = f"{base_name}/{entry.archive_path}"
            if entry.data is not None:
                archive.writestr(archive_member, entry.data)
            else:
                archive.write(entry.source_path, archive_member)

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
