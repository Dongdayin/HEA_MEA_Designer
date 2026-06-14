from __future__ import annotations

import json
import csv
import os
import hashlib
import colorsys
import math
import random
import re
import queue
import shutil
import subprocess
import string
import textwrap
import sys
import time
import threading
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk
import tkinter as tk

from matplotlib import rcParams
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
rcParams["axes.unicode_minus"] = False


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


ROOT = app_root()
WORK_DIR = ROOT / "generated"
PACKAGE_DATA_ROOT = ROOT / "data"
PACKAGE_MODEL_ROOT = ROOT / "models"
PACKAGE_INTERNAL_ROOT = ROOT / "_internal"
APP_CONFIG_PATH = ROOT / "config.json"
DEFAULT_LAMMPS_BIN_DIR = Path(r"E:\Program Files (x86)\LAMMPS 64-bit 22Jul2025 with GUI\bin")
DEFAULT_LAMMPS_EXE = DEFAULT_LAMMPS_BIN_DIR / "lmp.exe"


def _runtime_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    return env


def first_existing_path(*candidates: Path) -> Path:
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[-1]


def resolve_workspace_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    return path


def read_app_version() -> str:
    for candidate in (PACKAGE_INTERNAL_ROOT / "VERSION", ROOT / "VERSION"):
        try:
            text = candidate.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if text:
            return text
    return "0+unknown"


APP_VERSION = read_app_version()
APP_TITLE = f"DDOJY 高/中熵合金设计器 v{APP_VERSION}"


def data_resource_path(*parts: str) -> Path:
    relative = Path(*parts)
    return first_existing_path(PACKAGE_INTERNAL_ROOT / "data" / relative, PACKAGE_DATA_ROOT / relative, ROOT / relative)


def model_resource_path(*parts: str) -> Path:
    relative = Path(*parts)
    return first_existing_path(PACKAGE_INTERNAL_ROOT / "models" / relative, PACKAGE_MODEL_ROOT / relative, ROOT / relative)


def docs_resource_path(*parts: str) -> Path:
    relative = Path(*parts)
    return first_existing_path(PACKAGE_INTERNAL_ROOT / "docs" / relative, ROOT / "docs" / relative)


def set_workspace_dir(workspace_dir: Path) -> Path:
    global WORK_DIR, DEFAULT_OUTPUT, DEFAULT_GEOMETRY, DEFAULT_GEOMETRY_CRACK, DEFAULT_GRADIENT, DEFAULT_SEED
    resolved = resolve_workspace_path(workspace_dir)
    resolved.mkdir(parents=True, exist_ok=True)
    WORK_DIR = resolved
    DEFAULT_OUTPUT = WORK_DIR / "final_HEA.lmp"
    DEFAULT_GEOMETRY = WORK_DIR / "final.lmp"
    DEFAULT_GEOMETRY_CRACK = WORK_DIR / "final_crack.lmp"
    DEFAULT_GRADIENT = WORK_DIR / "gradient.txt"
    DEFAULT_SEED = WORK_DIR / "seed.xsf"
    return WORK_DIR


set_workspace_dir(WORK_DIR)


def resolve_lammps_executable(value: str | Path) -> Path:
    path = Path(value).expanduser()
    if path.is_dir():
        for candidate_name in ("lmp.exe", "lmp_serial.exe"):
            candidate = path / candidate_name
            if candidate.exists():
                return candidate
        python_executable = path / "python.exe"
        if python_executable.exists():
            return discover_lammps_executable_from_python(python_executable)
        scripts_candidate = path / "Scripts" / "lmp.exe"
        if scripts_candidate.exists():
            return scripts_candidate
        raise FileNotFoundError(f"找不到 LAMMPS 可执行文件: {path}")
    if path.name.lower() == "python.exe" and path.exists():
        return discover_lammps_executable_from_python(path)
    if path.exists():
        return path
    raise FileNotFoundError(f"找不到 LAMMPS 可执行文件: {path}")


def discover_lammps_executable_from_python(python_executable: Path) -> Path:
    if not python_executable.exists():
        raise FileNotFoundError(f"找不到 Python 可执行文件: {python_executable}")
    command = [
        str(python_executable),
        "-c",
        "import pathlib; import lammps; package_dir = pathlib.Path(lammps.__file__).resolve().parent; print(package_dir); print(package_dir / 'lmp.exe')",
    ]
    result = subprocess.run(command, capture_output=True, text=True, env=_runtime_env(), check=False)
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip()
        if not message:
            message = f"无法从 Python 环境解析 LAMMPS: {python_executable}"
        raise FileNotFoundError(message)
    lines = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
    if len(lines) < 2:
        raise FileNotFoundError(f"无法从 Python 环境解析 LAMMPS: {python_executable}")
    executable = Path(lines[-1]).expanduser()
    if not executable.exists():
        raise FileNotFoundError(f"LAMMPS 可执行文件不存在: {executable}")
    return executable


def _preferred_lammps_candidates() -> list[Path]:
    candidates: list[Path] = []
    seen: set[Path] = set()

    def add_candidate(candidate: Path) -> None:
        if candidate.exists() and candidate not in seen:
            seen.add(candidate)
            candidates.append(candidate)

    conda_env_roots: list[Path] = []
    conda_executable = shutil.which("conda")
    if conda_executable:
        try:
            result = subprocess.run([conda_executable, "env", "list", "--json"], capture_output=True, text=True, env=_runtime_env(), check=False, timeout=30)
            if result.returncode == 0 and result.stdout.strip():
                raw = json.loads(result.stdout)
                for env_path in raw.get("envs", []):
                    if env_path:
                        env_root = Path(env_path)
                        if env_root.exists():
                            conda_env_roots.append(env_root)
        except Exception:
            conda_env_roots = []
    for env_root in conda_env_roots:
        add_candidate(env_root / "Lib" / "site-packages" / "lammps" / "lmp.exe")
        add_candidate(env_root / "site-packages" / "lammps" / "lmp.exe")
        add_candidate(env_root / "Scripts" / "lmp.exe")

    roaming_python = Path.home() / "AppData" / "Roaming" / "Python"
    if roaming_python.exists():
        for python_root in sorted(roaming_python.glob("Python*"), reverse=True):
            add_candidate(python_root / "site-packages" / "lammps" / "lmp.exe")
            add_candidate(python_root / "Scripts" / "lmp.exe")

    located_lmp = shutil.which("lmp.exe")
    if located_lmp:
        add_candidate(Path(located_lmp))

    return candidates


def default_lammps_executable() -> Path:
    for candidate in _preferred_lammps_candidates():
        if candidate.exists():
            return candidate
    for candidate in (DEFAULT_LAMMPS_EXE, DEFAULT_LAMMPS_BIN_DIR / "lmp_serial.exe"):
        if candidate.exists():
            return candidate
    return DEFAULT_LAMMPS_EXE


def load_app_config() -> dict[str, str]:
    if not APP_CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(APP_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_app_config(config: dict[str, str]) -> None:
    APP_CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


@dataclass(frozen=True)
class AppSettings:
    workspace_dir: Path
    lammps_executable: Path
    lammps_core_count: int = 1
    lammps_use_gpu: bool = False
    inherit_previous: bool = True
    last_modeling_mode: str = "polycrystal"
    last_scenario: str = "NVT Relaxation"


@dataclass(frozen=True)
class LammpsRuntimeInfo:
    executable: Path
    package_dir: Path | None = None
    installed_packages: tuple[str, ...] = ()
    supports_mpi: bool = False
    supports_openmp: bool = False
    supports_gpu: bool = False
    supports_kokkos: bool = False
    discovery_error: str = ""


def _is_packaged_lammps_executable(path: Path) -> bool:
    normalized_parts = [part.lower() for part in path.parts]
    return path.name.lower() == "lmp.exe" and "site-packages" in normalized_parts and path.parent.name.lower() == "lammps"


def _parse_lammps_installed_packages(output: str) -> set[str]:
    packages: set[str] = set()
    collecting = False
    seen_package = False
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not collecting:
            if line == "Installed packages:":
                collecting = True
            continue
        if not line:
            if seen_package:
                break
            continue
        if seen_package and re.search(r"[a-z]", line):
            break
        for token in line.split():
            if re.fullmatch(r"[A-Z0-9][A-Z0-9/+-]*", token):
                packages.add(token)
                seen_package = True
    return packages


def probe_lammps_runtime(executable: Path) -> LammpsRuntimeInfo:
    executable = executable.expanduser()
    if not executable.exists():
        raise FileNotFoundError(f"找不到 LAMMPS 可执行文件: {executable}")
    discovery_error = ""
    output = ""
    try:
        result = subprocess.run([str(executable), "-h"], capture_output=True, text=True, env=_runtime_env(), check=False, timeout=60)
        output = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
        if result.returncode != 0 and not output.strip():
            discovery_error = f"LAMMPS -h 退出码 {result.returncode}"
    except Exception as exc:
        discovery_error = str(exc)
    installed_packages = tuple(sorted(_parse_lammps_installed_packages(output)))
    supports_mpi = bool(re.search(r"\bMPI v\d", output))
    supports_openmp = "OPENMP" in installed_packages
    supports_gpu = "GPU" in installed_packages
    supports_kokkos = "KOKKOS" in installed_packages
    package_dir = executable.parent if executable.parent.name.lower() == "lammps" else None
    if package_dir is not None and not any(part.lower() == "site-packages" for part in executable.parts):
        package_dir = None
    return LammpsRuntimeInfo(
        executable=executable,
        package_dir=package_dir,
        installed_packages=installed_packages,
        supports_mpi=supports_mpi,
        supports_openmp=supports_openmp,
        supports_gpu=supports_gpu,
        supports_kokkos=supports_kokkos,
        discovery_error=discovery_error,
    )


@dataclass(frozen=True)
class LammpsInputConfig:
    scenario: str
    data_file: Path
    output_dir: Path
    timestep: float
    run_steps: int
    temperature: float
    ensemble: str
    force_field: str
    potential_file: Path | None
    element_list: list[str]
    seed: int
    log_file: Path
    input_script: Path
    final_temperature: float | None = None
    pressure: float | None = None
    relax_steps: int = 0
    extra_commands: str = ""
    pair_style_override: str = ""
    pair_coeff_override: str = ""
    custom_template: str = ""
    thermo_every: int = 100
    dump_every: int = 100
    production_data_file: Path | None = None
    trajectory_file: Path | None = None
    restart_file: Path | None = None


@dataclass(frozen=True)
class LammpsStageFiles:
    name: str
    directory: Path
    data_file: Path
    trajectory_file: Path
    restart_file: Path


@dataclass(frozen=True)
class LammpsOutputLayout:
    base_dir: Path
    process_dir: Path
    process_script_file: Path
    process_log_file: Path
    relaxation: LammpsStageFiles
    production: LammpsStageFiles


def build_lammps_output_layout(
    output_dir: Path,
    *,
    process_script_file: Path | None = None,
    process_log_file: Path | None = None,
    production_data_file: Path | None = None,
    production_trajectory_file: Path | None = None,
    production_restart_file: Path | None = None,
) -> LammpsOutputLayout:
    base_dir = output_dir.expanduser()
    process_dir = base_dir / "process"
    relaxation_dir = base_dir / "relaxation"
    production_dir = production_data_file.parent.expanduser() if production_data_file is not None else base_dir / "md"
    if process_script_file is None:
        process_script_file = process_dir / "in.relax_md.lammps"
    if process_log_file is None:
        process_log_file = process_dir / "log.lammps"
    if production_data_file is None:
        production_data_file = production_dir / "production.data"
    else:
        production_data_file = production_data_file.expanduser()
    if production_trajectory_file is None:
        production_trajectory_file = production_dir / "trajectory.lammpstrj"
    else:
        production_trajectory_file = production_trajectory_file.expanduser()
    if production_restart_file is None:
        production_restart_file = production_dir / "production.restart"
    else:
        production_restart_file = production_restart_file.expanduser()
    relaxation = LammpsStageFiles(
        name="relaxation",
        directory=relaxation_dir,
        data_file=relaxation_dir / "relaxed.data",
        trajectory_file=relaxation_dir / "trajectory.lammpstrj",
        restart_file=relaxation_dir / "relaxed.restart",
    )
    production = LammpsStageFiles(
        name="md",
        directory=production_dir,
        data_file=production_data_file,
        trajectory_file=production_trajectory_file,
        restart_file=production_restart_file,
    )
    return LammpsOutputLayout(
        base_dir=base_dir,
        process_dir=process_dir,
        process_script_file=process_script_file.expanduser(),
        process_log_file=process_log_file.expanduser(),
        relaxation=relaxation,
        production=production,
    )


@dataclass(frozen=True)
class LammpsThermoPoint:
    step: int
    temperature: float | None = None
    total_energy: float | None = None
    pressure: float | None = None


class ScrollableFrame(ttk.Frame):
    def __init__(self, parent: tk.Misc, *, background: str = "#f4f6f8") -> None:
        super().__init__(parent)
        self.canvas = tk.Canvas(self, highlightthickness=0, bg=background)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.content = ttk.Frame(self.canvas, style="App.TFrame")
        self._window_id = self.canvas.create_window((0, 0), window=self.content, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.content.bind("<Configure>", self._on_content_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.bind_all("<MouseWheel>", self._on_mousewheel, add="+")
        self.bind_all("<Button-4>", self._on_mousewheel, add="+")
        self.bind_all("<Button-5>", self._on_mousewheel, add="+")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

    def _on_content_configure(self, _event: tk.Event) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self._window_id, width=event.width)

    def _is_descendant_widget(self, widget: tk.Misc | None) -> bool:
        current: tk.Misc | None = widget
        while current is not None:
            if current is self or current is self.canvas or current is self.content:
                return True
            current = getattr(current, "master", None)
        return False

    def _on_mousewheel(self, event: tk.Event) -> str | None:
        widget = getattr(event, "widget", None)
        if not self._is_descendant_widget(widget):
            return None
        widget_class = widget.winfo_class() if widget is not None else ""
        if widget_class == "Text":
            return None
        if getattr(event, "num", None) == 4:
            delta = -1
        elif getattr(event, "num", None) == 5:
            delta = 1
        else:
            delta_value = getattr(event, "delta", 0)
            delta = -1 if delta_value > 0 else 1 if delta_value < 0 else 0
        if delta:
            self.canvas.yview_scroll(delta, "units")
            return "break"
        return None


class DataFileWriter:
    def write(
        self,
        path: Path,
        structure: LammpsStructure,
        atoms: list[AtomRecord],
        *,
        mass_entries: list[CompositionEntry] | None = None,
        atom_types_count: int | None = None,
        type_assignments: list[int] | None = None,
        box_override: BoxBounds | None = None,
    ) -> Path:
        write_lammps_structure(
            path,
            structure,
            atoms,
            mass_entries=mass_entries,
            atom_types_count=atom_types_count,
            type_assignments=type_assignments,
            box_override=box_override,
        )
        return path

    def export_structure(self, source_path: Path, output_path: Path, *, atomsk_path: Path | None = None) -> Path:
        del atomsk_path
        structure = read_lammps_structure(source_path)
        self.write(output_path, structure, structure.atoms, atom_types_count=structure.atom_types or 1)
        return output_path


class InputGenerator:
    def default_template(self) -> str:
        return textwrap.dedent(
            """\
            # DDOJY generated LAMMPS input for HEA / MEA / doping workflows
            # Elements in the current data file: $elements
            # Potential file: $potential_file
            # Put alloy substitutions, vacancy creation, solute insertion, and region-based doping commands in $extra_commands.
            # Common snippets:
            # group dopant type 5
            # set group dopant type/fraction 5 0.02 $seed
            # create_atoms 6 single x y z
            # delete_atoms region vacancy
            units metal
            atom_style atomic
            boundary p p p
            neighbor 2.0 bin
            neigh_modify delay 10 every 1 check yes
            read_data \"$data_file\"
            timestep $timestep

            # Alloy and interatomic potential setup
            $pair_section

            # User-defined alloy / doping operations
            $extra_commands

            # Scenario stage: relaxation, annealing, quench, deformation, or custom run block
            $scenario_section
            """
        ).strip() + "\n"

    def _normalize_block(self, text: str) -> str:
        return "\n".join(line.rstrip() for line in text.splitlines()).strip()

    def safe_replace(self, template: str, mapping: dict[str, object]) -> str:
        template_obj = string.Template(template)
        normalized_mapping = {key: value.as_posix() if isinstance(value, Path) else str(value) for key, value in mapping.items()}
        return template_obj.safe_substitute(normalized_mapping)

    def _style_command(self, style_text: str) -> str:
        style = style_text.strip()
        if not style:
            return "pair_style lj/cut 2.5"
        if style.lower().startswith("pair_style"):
            return style
        return f"pair_style {style}"

    def _pair_style_name(self, style_text: str) -> str:
        style = style_text.strip()
        if style.lower().startswith("pair_style"):
            parts = style.split(None, 1)
            style = parts[1] if len(parts) > 1 else ""
        return style.strip().lower()

    def _potential_kind(self, potential_file: Path | None) -> str:
        if potential_file is None:
            return ""
        name = potential_file.name.lower()
        if name.endswith(".eam.fs"):
            return "eam/fs"
        if name.endswith(".eam.alloy"):
            return "eam/alloy"
        if name.endswith(".eam.he"):
            return "eam/he"
        if name.endswith(".eam.cd"):
            return "eam/cd"
        if name.endswith(".eam.cd.old"):
            return "eam/cd/old"
        if name.endswith(".msmeam"):
            return "meam/ms"
        if name.endswith(".meam") or name.endswith(".mean"):
            return "meam"
        if name.endswith(".eam"):
            return "eam"
        return ""

    def _resolve_meam_files(self, potential_file: Path) -> tuple[Path, Path | None]:
        name = potential_file.name
        lower = name.lower()
        if lower.startswith("library_") and (lower.endswith(".meam") or lower.endswith(".mean") or lower.endswith(".msmeam")):
            base = name[len("library_"):].rsplit(".", 1)[0]
            for suffix in (".mean", ".meam", ".msmeam"):
                companion = potential_file.with_name(f"{base}{suffix}")
                if companion.exists():
                    return potential_file, companion
            return potential_file, None
        if lower.endswith(".mean") and not lower.startswith("library_"):
            base = name[: -len(".mean")]
            for library_suffix in (".meam", ".mean", ".msmeam"):
                library_candidate = potential_file.with_name(f"library_{base}{library_suffix}")
                if library_candidate.exists():
                    return library_candidate, potential_file
            return potential_file, None
        if lower.endswith(".meam") and not lower.startswith("library_"):
            base = name[: -len(".meam")]
            for library_suffix in (".meam", ".mean", ".msmeam"):
                library_candidate = potential_file.with_name(f"library_{base}{library_suffix}")
                if library_candidate.exists():
                    return library_candidate, potential_file
            return potential_file, None
        if lower.endswith(".msmeam") and not lower.startswith("library_"):
            base = name[: -len(".msmeam")]
            for library_suffix in (".msmeam", ".meam", ".mean"):
                library_candidate = potential_file.with_name(f"library_{base}{library_suffix}")
                if library_candidate.exists():
                    return library_candidate, potential_file
            return potential_file, None
        return potential_file, None

    def _pair_section(self, config: LammpsInputConfig) -> str:
        style_text = config.pair_style_override.strip() or config.force_field.strip() or "lj/cut"
        style_name = self._pair_style_name(style_text) or "lj/cut"
        potential_kind = self._potential_kind(config.potential_file)
        elements = " ".join(config.element_list)
        style_line = self._style_command(style_text)
        coeff_override = self._normalize_block(config.pair_coeff_override)
        if coeff_override:
            return f"{style_line}\n{coeff_override}\n"
        if potential_kind in {"meam", "meam/ms"} and style_name in {"lj", "lj/cut", "eam", "eam/alloy", "eam/fs", "eam/he", "eam/cd", "eam/cd/old", "meam", "meam/ms"}:
            style_name = potential_kind
            style_line = self._style_command(style_name)
        elif potential_kind in {"eam", "eam/alloy", "eam/fs", "eam/he", "eam/cd", "eam/cd/old"} and style_name in {"lj", "lj/cut", "meam", "meam/ms"}:
            style_name = potential_kind
            style_line = self._style_command(style_name)

        if style_name in {"lj", "lj/cut"}:
            return "pair_style lj/cut 2.5\npair_coeff * * 0.0103 2.5\n"
        if style_name in {"hybrid", "hybrid/overlay", "lj/charmm/coul/long", "lj/cut/coul/long", "buck/coul/long", "coul/cut", "coul/long", "morse", "table", "soft"}:
            return f"{style_line}\n# 请在 pair_coeff 覆盖中补充该力场参数，必要时再加入 kspace_style 等命令\n"
        if style_name in {"meam", "meam/ms"}:
            if config.potential_file is None:
                raise ValueError(f"{style_text} 需要指定势函数文件，或在 pair_coeff 覆盖里填写完整参数")
            library_file, parameter_file = self._resolve_meam_files(config.potential_file)
            library_text = library_file.as_posix()
            if parameter_file is None:
                return f"{style_line}\npair_coeff * * \"{library_text}\" {elements} NULL {elements}\n"
            return f"{style_line}\npair_coeff * * \"{library_text}\" {elements} \"{parameter_file.as_posix()}\" {elements}\n"
        if style_name in {"eam", "eam/alloy", "eam/fs", "eam/he", "eam/cd", "eam/cd/old", "tersoff", "sw", "reax/c"}:
            if config.potential_file is None:
                raise ValueError(f"{style_text} 需要指定势函数文件，或在 pair_coeff 覆盖里填写完整参数")
            potential_text = config.potential_file.as_posix()
            if style_name == "reax/c":
                return f"pair_style reax/c NULL\npair_coeff * * \"{potential_text}\" {elements}\n"
            return f"{style_line}\npair_coeff * * \"{potential_text}\" {elements}\n"
        if config.potential_file is not None:
            potential_text = config.potential_file.as_posix()
            return f"{style_line}\npair_coeff * * \"{potential_text}\" {elements}\n"
        raise ValueError(f"当前力场 {style_text} 没有自动规则，请填写 pair_coeff 覆盖或势函数文件")

    def _thermo_section(self, config: LammpsInputConfig) -> str:
        thermo_every = max(1, config.thermo_every)
        return f"thermo {thermo_every}\nthermo_style custom step temp pe ke etotal press\n"

    def _stabilization_prefix(self, config: LammpsInputConfig, *, pressure: float, relax_box: bool) -> str:
        thermo_every = max(1, min(config.thermo_every, 20))
        lines = [
            "reset_timestep 0",
            "min_style cg",
            "min_modify dmax 0.1 line quadratic",
        ]
        if relax_box:
            lines.append(f"fix relax_box all box/relax iso {pressure:.6f} vmax 0.001")
        lines.append(f"thermo {thermo_every}")
        lines.append("thermo_style custom step pe etotal press")
        lines.append("minimize 1.0e-12 1.0e-12 2000 20000")
        if relax_box:
            lines.append("unfix relax_box")
        return "\n".join(lines) + "\n"

    def _resolve_output_layout(self, config: LammpsInputConfig) -> LammpsOutputLayout:
        return build_lammps_output_layout(
            config.output_dir,
            process_script_file=config.input_script,
            process_log_file=config.log_file,
            production_data_file=config.production_data_file,
            production_trajectory_file=config.trajectory_file,
            production_restart_file=config.restart_file,
        )

    def _dump_prefix(self, dump_id: str, trajectory_file: Path, dump_every: int) -> str:
        return self.safe_replace(
            """dump $dump_id all custom $dump_every "$trajectory_file" id type x y z vx vy vz
dump_modify $dump_id sort id
""",
            {
                "dump_id": dump_id,
                "dump_every": dump_every,
                "trajectory_file": trajectory_file,
            },
        )

    def _output_suffix(self, dump_id: str, data_file: Path, restart_file: Path, *, include_trajectory: bool = True) -> str:
        lines: list[str] = []
        if include_trajectory:
            lines.append(f"undump {dump_id}")
        lines.append(f'write_data "{data_file.as_posix()}"')
        lines.append(f'write_restart "{restart_file.as_posix()}"')
        return "\n".join(lines) + "\n"

    def _decorate_scenario_output(self, config: LammpsInputConfig, scenario_block: str) -> str:
        layout = self._resolve_output_layout(config)
        dump_every = max(1, config.dump_every)
        scenario_name = config.scenario.strip().lower()
        if scenario_name == "custom":
            if not re.search(r"\b(run|minimize)\b", scenario_block, re.IGNORECASE):
                return scenario_block
            production_has_trajectory = bool(re.search(r"\brun\b", scenario_block, re.IGNORECASE))
            return self._dump_prefix("ddojy_md", layout.production.trajectory_file, dump_every) + scenario_block + self._output_suffix("ddojy_md", layout.production.data_file, layout.production.restart_file, include_trajectory=production_has_trajectory)

        if scenario_name in {"energy minimization", "minimize", "minimization"}:
            return scenario_block + self._output_suffix("ddojy_relax", layout.relaxation.data_file, layout.relaxation.restart_file, include_trajectory=False)

        velocity_marker = "velocity all create"
        if velocity_marker not in scenario_block:
            return scenario_block + self._output_suffix("ddojy_relax", layout.relaxation.data_file, layout.relaxation.restart_file, include_trajectory=False)

        relaxation_block, production_block = scenario_block.split(velocity_marker, 1)
        relaxation_section = relaxation_block + self._output_suffix("ddojy_relax", layout.relaxation.data_file, layout.relaxation.restart_file, include_trajectory=False)
        production_section = self._dump_prefix("ddojy_md", layout.production.trajectory_file, dump_every) + velocity_marker + production_block + self._output_suffix("ddojy_md", layout.production.data_file, layout.production.restart_file, include_trajectory=True)
        return relaxation_section + production_section

    def _base_header(self, config: LammpsInputConfig) -> str:
        return self.safe_replace(
            """units metal
atom_style atomic
boundary p p p
neighbor 2.0 bin
neigh_modify delay 10 every 1 check yes
read_data \"$data_file\"
timestep $timestep
""",
            {"data_file": config.data_file, "timestep": f"{config.timestep:.6f}"},
        )

    def _scenario_section(self, config: LammpsInputConfig) -> str:
        scenario = config.scenario.strip().lower().replace("_", " ")
        temperature = float(config.temperature)
        final_temperature = float(config.final_temperature if config.final_temperature is not None else config.temperature)
        pressure = float(config.pressure if config.pressure is not None else 0.0)
        thermo = self._thermo_section(config)
        seed = config.seed
        timestep = f"{config.timestep:.6f}"
        damping = f"{max(1.0, 100.0 * config.timestep):.6f}"
        pressure_damping = f"{max(1.0, 1000.0 * config.timestep):.6f}"
        run_steps = config.run_steps
        if scenario in {"nvt relaxation", "nvt"}:
            return self._stabilization_prefix(config, pressure=pressure, relax_box=True) + self.safe_replace(
                """velocity all create $temperature $seed mom yes rot yes dist gaussian
fix 1 all nvt temp $temperature $temperature $damping
$thermo
run $run_steps
unfix 1
""",
                {
                    "temperature": f"{temperature:.3f}",
                    "seed": seed,
                    "damping": damping,
                    "thermo": thermo,
                    "run_steps": run_steps,
                },
            )
        if scenario in {"npt relaxation", "npt"}:
            return self._stabilization_prefix(config, pressure=pressure, relax_box=True) + self.safe_replace(
                """velocity all create $temperature $seed mom yes rot yes dist gaussian
fix 1 all npt temp $temperature $temperature $damping iso $pressure $pressure $pressure_damping
$thermo
run $run_steps
unfix 1
""",
                {
                    "temperature": f"{temperature:.3f}",
                    "pressure": f"{pressure:.6f}",
                    "seed": seed,
                    "damping": damping,
                    "pressure_damping": pressure_damping,
                    "thermo": thermo,
                    "run_steps": run_steps,
                },
            )
        if scenario in {"nph relaxation", "nph"}:
            return self._stabilization_prefix(config, pressure=pressure, relax_box=True) + self.safe_replace(
                """velocity all create $temperature $seed mom yes rot yes dist gaussian
fix 1 all nph iso $pressure $pressure $pressure_damping
$thermo
run $run_steps
unfix 1
""",
                {
                    "temperature": f"{temperature:.3f}",
                    "pressure": f"{pressure:.6f}",
                    "seed": seed,
                    "pressure_damping": pressure_damping,
                    "thermo": thermo,
                    "run_steps": run_steps,
                },
            )
        if scenario in {"nve dynamics", "nve"}:
            pre_run_steps = max(200, min(2000, max(1, run_steps // 10)))
            if pre_run_steps >= run_steps:
                pre_run_steps = run_steps
                main_run_steps = 0
            else:
                main_run_steps = run_steps - pre_run_steps
            warmup_block = self.safe_replace(
                """velocity all create $temperature $seed mom yes rot yes dist gaussian
fix 1 all nve/limit 0.1
$thermo
run $pre_run_steps
unfix 1
""",
                {
                    "temperature": f"{temperature:.3f}",
                    "seed": seed,
                    "thermo": thermo,
                    "pre_run_steps": pre_run_steps,
                },
            )
            if main_run_steps <= 0:
                return self._stabilization_prefix(config, pressure=pressure, relax_box=True) + warmup_block
            return self._stabilization_prefix(config, pressure=pressure, relax_box=True) + warmup_block + self.safe_replace(
                """fix 1 all nve
$thermo
run $run_steps
unfix 1
""",
                {
                    "thermo": thermo,
                    "run_steps": main_run_steps,
                },
            )
        if scenario in {"energy minimization", "minimize", "minimization"}:
            return self._stabilization_prefix(config, pressure=pressure, relax_box=True)
        if scenario in {"annealing", "heat treatment", "heat"}:
            return self._stabilization_prefix(config, pressure=pressure, relax_box=True) + self.safe_replace(
                """velocity all create $temperature $seed mom yes rot yes dist gaussian
fix 1 all nvt temp $temperature $final_temperature $damping
$thermo
run $run_steps
unfix 1
""",
                {
                    "temperature": f"{temperature:.3f}",
                    "final_temperature": f"{final_temperature:.3f}",
                    "seed": seed,
                    "damping": damping,
                    "thermo": thermo,
                    "run_steps": run_steps,
                },
            )
        if scenario in {"quench", "cooling"}:
            return self._stabilization_prefix(config, pressure=pressure, relax_box=True) + self.safe_replace(
                """velocity all create $temperature $seed mom yes rot yes dist gaussian
fix 1 all nvt temp $temperature $final_temperature $damping
$thermo
run $run_steps
unfix 1
""",
                {
                    "temperature": f"{temperature:.3f}",
                    "final_temperature": f"{final_temperature:.3f}",
                    "seed": seed,
                    "damping": damping,
                    "thermo": thermo,
                    "run_steps": run_steps,
                },
            )
        if scenario in {"uniaxial tension", "tension", "stretch"}:
            return self._stabilization_prefix(config, pressure=pressure, relax_box=False) + self.safe_replace(
                """velocity all create $temperature $seed mom yes rot yes dist gaussian
fix 1 all nvt temp $temperature $temperature $damping
compute stress all stress/atom NULL
compute c_reduce all reduce sum c_stress[1] c_stress[2] c_stress[3]
variable sxx equal c_reduce[1]
variable syy equal c_reduce[2]
variable szz equal c_reduce[3]
fix 2 all deform 1 x erate 1.0e-5 units box remap x
$thermo
thermo_style custom step temp pe ke etotal press v_sxx v_syy v_szz
run $run_steps
unfix 2
unfix 1
""",
                {
                    "temperature": f"{temperature:.3f}",
                    "seed": seed,
                    "damping": damping,
                    "thermo": thermo,
                    "run_steps": run_steps,
                },
            )
        if scenario in {"shear deformation", "shear", "simple shear"}:
            return self._stabilization_prefix(config, pressure=pressure, relax_box=False) + self.safe_replace(
                """velocity all create $temperature $seed mom yes rot yes dist gaussian
fix 1 all nvt temp $temperature $temperature $damping
fix 2 all deform 1 xy erate 1.0e-5 units box remap x
$thermo
thermo_style custom step temp pe ke etotal press
run $run_steps
unfix 2
unfix 1
""",
                {
                    "temperature": f"{temperature:.3f}",
                    "seed": seed,
                    "damping": damping,
                    "thermo": thermo,
                    "run_steps": run_steps,
                },
            )
        if scenario in {"nanoindentation", "indent", "indentation"}:
            return self.safe_replace(
                """boundary p p f
velocity all create $temperature $seed mom yes rot yes dist gaussian
fix 1 all nvt temp $temperature $temperature $damping
variable indenter_z equal 0.80*boxhi
fix 2 all indent 50.0 sphere 0.5*lx 0.5*ly v_indenter_z 20.0 units box
$thermo
thermo_style custom step temp pe ke etotal press
run $run_steps
unfix 2
unfix 1
""",
                {
                    "temperature": f"{temperature:.3f}",
                    "seed": seed,
                    "damping": damping,
                    "thermo": thermo,
                    "run_steps": run_steps,
                },
            )
        if scenario in {"rdf analysis", "rdf"}:
            return self._stabilization_prefix(config, pressure=pressure, relax_box=True) + self.safe_replace(
                """velocity all create $temperature $seed mom yes rot yes dist gaussian
fix 1 all nvt temp $temperature $temperature $damping
compute pairrdf all rdf 200
fix 2 all ave/time $thermo_every 1 $thermo_every c_pairrdf[*] file rdf.dat mode vector
$thermo
run $run_steps
unfix 2
unfix 1
""",
                {
                    "temperature": f"{temperature:.3f}",
                    "seed": seed,
                    "damping": damping,
                    "thermo_every": max(1, config.thermo_every),
                    "thermo": thermo,
                    "run_steps": run_steps,
                },
            )
        if scenario == "custom":
            custom_block = self._normalize_block(config.extra_commands)
            return f"{custom_block}\n" if custom_block else f"run {run_steps}\n"
        return self._stabilization_prefix(config, pressure=pressure, relax_box=False) + self.safe_replace(
            """velocity all create $temperature $seed mom yes rot yes dist gaussian
fix 1 all $ensemble temp $temperature $temperature $damping
$thermo
run $run_steps
unfix 1
""",
            {
                "temperature": f"{temperature:.3f}",
                "seed": seed,
                "damping": damping,
                "thermo": thermo,
                "run_steps": run_steps,
                "ensemble": config.ensemble.lower(),
            },
        )

    def build_script(self, config: LammpsInputConfig) -> str:
        pair_section = self._pair_section(config)
        scenario_section = self._scenario_section(config)
        scenario_section = self._decorate_scenario_output(config, scenario_section)
        extra_commands = self._normalize_block(config.extra_commands)
        scenario_name = config.scenario.strip().lower()
        if scenario_name == "custom":
            extra_commands = ""
        template = config.custom_template.strip() or self.default_template()
        layout = self._resolve_output_layout(config)
        dump_every = max(1, config.dump_every)
        payload = {
            "data_file": config.data_file,
            "output_dir": config.output_dir,
            "process_dir": layout.process_dir.as_posix(),
            "relaxation_dir": layout.relaxation.directory.as_posix(),
            "production_dir": layout.production.directory.as_posix(),
            "process_script_file": layout.process_script_file.as_posix(),
            "process_log_file": layout.process_log_file.as_posix(),
            "relaxation_data_file": layout.relaxation.data_file.as_posix(),
            "relaxation_trajectory_file": layout.relaxation.trajectory_file.as_posix(),
            "relaxation_restart_file": layout.relaxation.restart_file.as_posix(),
            "production_data_file": layout.production.data_file.as_posix(),
            "production_trajectory_file": layout.production.trajectory_file.as_posix(),
            "production_restart_file": layout.production.restart_file.as_posix(),
            "timestep": f"{config.timestep:.6f}",
            "run_steps": config.run_steps,
            "temperature": f"{config.temperature:.3f}",
            "final_temperature": f"{float(config.final_temperature if config.final_temperature is not None else config.temperature):.3f}",
            "pressure": f"{float(config.pressure if config.pressure is not None else 0.0):.6f}",
            "ensemble": config.ensemble,
            "force_field": config.force_field,
            "pair_style": self._style_command(config.pair_style_override.strip() or config.force_field.strip() or "lj/cut"),
            "pair_coeff": self._normalize_block(config.pair_coeff_override),
            "pair_style_override": self._normalize_block(config.pair_style_override),
            "pair_coeff_override": self._normalize_block(config.pair_coeff_override),
            "pair_section": pair_section.rstrip(),
            "scenario_section": scenario_section.rstrip(),
            "extra_commands": extra_commands,
            "seed": config.seed,
            "thermo_every": max(1, config.thermo_every),
            "dump_every": dump_every,
            "final_data_file": layout.production.data_file.as_posix(),
            "trajectory_file": layout.production.trajectory_file.as_posix(),
            "restart_file": layout.production.restart_file.as_posix(),
            "potential_file": config.potential_file.as_posix() if config.potential_file is not None else "",
            "elements": " ".join(config.element_list),
            "scenario_name": config.scenario,
        }
        rendered = self.safe_replace(template, payload)
        return rendered if rendered.endswith("\n") else rendered + "\n"

    def write(self, config: LammpsInputConfig) -> Path:
        layout = self._resolve_output_layout(config)
        for path in (
            config.input_script,
            layout.process_log_file,
            layout.relaxation.data_file,
            layout.relaxation.restart_file,
            layout.relaxation.trajectory_file,
            layout.production.data_file,
            layout.production.restart_file,
            layout.production.trajectory_file,
        ):
            path.parent.mkdir(parents=True, exist_ok=True)
        script = self.build_script(config)
        config.input_script.parent.mkdir(parents=True, exist_ok=True)
        config.input_script.write_text(script, encoding="utf-8")
        return config.input_script


class LammpsManager:
    def __init__(self) -> None:
        self.process: subprocess.Popen[str] | None = None
        self._output_queue: queue.Queue[str] = queue.Queue()
        self._reader_thread: threading.Thread | None = None
        self._finished = False

    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start(self, command: list[str], work_dir: Path, log_path: Path, env: dict[str, str] | None = None) -> None:
        if self.is_running():
            raise RuntimeError("LAMMPS 正在运行中")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        work_dir.mkdir(parents=True, exist_ok=True)
        if log_path.exists():
            log_path.unlink()
        self.process = subprocess.Popen(
            command,
            cwd=work_dir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        self._finished = False
        self._reader_thread = threading.Thread(target=self._read_output_loop, daemon=True)
        self._reader_thread.start()

    def _read_output_loop(self) -> None:
        if self.process is None or self.process.stdout is None:
            return
        for line in iter(self.process.stdout.readline, ""):
            self._output_queue.put(line)
        try:
            self.process.stdout.close()
        except Exception:
            pass
        self._finished = True

    def poll_output(self) -> list[str]:
        lines: list[str] = []
        while True:
            try:
                lines.append(self._output_queue.get_nowait())
            except queue.Empty:
                break
        return lines

    def poll_returncode(self) -> int | None:
        if self.process is None:
            return None
        return self.process.poll()

    def terminate(self) -> None:
        if self.process is None:
            return
        try:
            self.process.terminate()
        except Exception:
            pass

    def kill(self) -> None:
        if self.process is None:
            return
        try:
            self.process.kill()
        except Exception:
            pass


def parse_lammps_log(path: Path) -> list[LammpsThermoPoint]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    points: list[LammpsThermoPoint] = []
    headers: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        columns = stripped.split()
        if columns and columns[0].lower() == "step" and len(columns) >= 2:
            headers = columns
            continue
        if not headers:
            continue
        if len(columns) != len(headers):
            if columns[0].startswith("Loop"):
                headers = []
            continue
        try:
            values = [float(item) for item in columns]
        except ValueError:
            continue
        if not all(math.isfinite(value) for value in values):
            continue
        value_map = {header.lower(): value for header, value in zip(headers, values)}
        if "step" not in value_map:
            continue
        points.append(
            LammpsThermoPoint(
                step=int(value_map.get("step", 0)),
                temperature=value_map.get("temp"),
                total_energy=value_map.get("etotal"),
                pressure=value_map.get("press"),
            )
        )
    return points


LAMMPS_LOG_ISSUE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"Lost atoms", re.IGNORECASE), "检测到丢原子：建议先做能量最小化，或改用 NPT 松弛并降低步长。"),
    (re.compile(r"Out of range atoms", re.IGNORECASE), "检测到原子越界：建议先松弛结构或减小时间步长。"),
    (re.compile(r"Dangerous builds", re.IGNORECASE), "检测到危险邻居表更新：建议减小时间步长或提高邻居表更新频率。"),
    (re.compile(r"Bond atoms .* missing", re.IGNORECASE), "检测到缺失键原子：通常是结构失稳或步长过大。"),
    (re.compile(r"Non-numeric pressure", re.IGNORECASE), "检测到压力数值异常：请检查势函数和原子类型映射。"),
    (re.compile(r"\bnan\b", re.IGNORECASE), "检测到 NaN 数值：请检查初始结构近距离接触、势函数映射和时间步长。"),
)


def _append_unique(items: list[str], item: str) -> None:
    if item and item not in items:
        items.append(item)


def _matching_log_lines(text: str, pattern: re.Pattern[str], *, limit: int) -> list[str]:
    matches: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if pattern.search(stripped):
            matches.append(_truncate_process_output(stripped, limit=500))
            if len(matches) >= limit:
                break
    return matches


def scan_lammps_log_issues(path: Path) -> list[str]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    issues: list[str] = []
    for pattern, message in LAMMPS_LOG_ISSUE_PATTERNS:
        if pattern.search(text):
            _append_unique(issues, message)
    for line in _matching_log_lines(text, re.compile(r"^ERROR(?::|\s)", re.IGNORECASE), limit=3):
        _append_unique(issues, f"LAMMPS ERROR: {line}")
    for line in _matching_log_lines(text, re.compile(r"^WARNING(?::|\s)", re.IGNORECASE), limit=3):
        _append_unique(issues, f"LAMMPS WARNING: {line}")
    return issues


class WorkspaceDialog(tk.Toplevel):
    def __init__(self, parent: tk.Tk, initial: AppSettings) -> None:
        super().__init__(parent)
        self.result: AppSettings | None = None
        self._initial_settings = initial
        self.title(f"DDOJY 启动设置 v{APP_VERSION}")
        self.configure(bg=BACKGROUND)
        self.resizable(False, False)
        self.workspace_var = tk.StringVar(value=str(initial.workspace_dir))
        self.lammps_var = tk.StringVar(value=str(initial.lammps_executable))

        main = ttk.Frame(self, style="App.TFrame", padding=20)
        main.pack(fill="both", expand=True)
        header = tk.Frame(main, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        header.pack(fill="x", pady=(0, 14))
        tk.Frame(header, bg=ACCENT, width=5).pack(side="left", fill="y")
        header_body = tk.Frame(header, bg=PANEL)
        header_body.pack(side="left", fill="both", expand=True, padx=16, pady=12)
        tk.Label(header_body, text=f"DDOJY v{APP_VERSION}", bg=PANEL, fg=TEXT, font=("Microsoft YaHei UI", 20, "bold")).pack(anchor="w")
        tk.Label(header_body, text="启动设置", bg=PANEL, fg=MUTED, font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w", pady=(2, 0))

        form = ttk.LabelFrame(main, text="工作目录与运行环境", style="Section.TLabelframe", padding=12)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)
        ttk.Label(form, text="工作目录").grid(row=0, column=0, sticky="w")
        workspace_entry = ttk.Entry(form, textvariable=self.workspace_var, width=60)
        workspace_entry.grid(row=0, column=1, sticky="ew", padx=(8, 8))
        ttk.Button(form, text="浏览目录", command=self._browse_workspace).grid(row=0, column=2, sticky="w")
        ttk.Label(form, text="LAMMPS 环境/程序").grid(row=1, column=0, sticky="w", pady=(10, 0))
        lammps_entry = ttk.Entry(form, textvariable=self.lammps_var, width=60)
        lammps_entry.grid(row=1, column=1, sticky="ew", padx=(8, 8), pady=(10, 0))
        ttk.Button(form, text="浏览目录", command=self._browse_lammps_directory).grid(row=1, column=2, sticky="w", pady=(10, 0))
        ttk.Button(form, text="浏览程序", command=self._browse_lammps).grid(row=1, column=3, sticky="w", padx=(8, 0), pady=(10, 0))
        tk.Label(form, text="支持 conda 环境目录、python.exe 或 lmp.exe。", bg=PANEL, fg=MUTED, font=("Microsoft YaHei UI", 9)).grid(row=2, column=0, columnspan=4, sticky="w", pady=(8, 0))

        buttons = ttk.Frame(main)
        buttons.pack(fill="x", pady=(14, 0))
        ttk.Button(buttons, text="取消", command=self._cancel).pack(side="right")
        ttk.Button(buttons, text="保存并继续", style="Accent.TButton", command=self._accept).pack(side="right", padx=(0, 8))

        self.update_idletasks()
        width = max(self.winfo_width(), 720)
        height = max(self.winfo_height(), 260)
        screen_x = self.winfo_screenwidth()
        screen_y = self.winfo_screenheight()
        self.geometry(f"{width}x{height}+{(screen_x - width) // 2}+{(screen_y - height) // 2}")
        self.deiconify()
        self.lift()
        self.focus_force()
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._cancel)

    def _browse_workspace(self) -> None:
        selected = filedialog.askdirectory(title="选择工作目录", initialdir=self.workspace_var.get() or str(ROOT))
        if selected:
            self.workspace_var.set(selected)

    def _browse_lammps(self) -> None:
        selected = filedialog.askopenfilename(
            title="选择 LAMMPS 可执行文件",
            initialdir=str(DEFAULT_LAMMPS_BIN_DIR if DEFAULT_LAMMPS_BIN_DIR.exists() else ROOT),
            filetypes=[("LAMMPS executable", "*.exe"), ("All files", "*.*")],
        )
        if selected:
            self.lammps_var.set(selected)

    def _browse_lammps_directory(self) -> None:
        selected = filedialog.askdirectory(
            title="选择 LAMMPS conda 环境目录",
            initialdir=str(DEFAULT_LAMMPS_BIN_DIR.parent if DEFAULT_LAMMPS_BIN_DIR.exists() else ROOT),
        )
        if selected:
            self.lammps_var.set(selected)

    def _accept(self) -> None:
        try:
            workspace_text = self.workspace_var.get().strip()
            if not workspace_text:
                raise ValueError("工作目录不能为空")
            workspace_dir = Path(workspace_text).expanduser()
            workspace_dir.mkdir(parents=True, exist_ok=True)
            lammps_executable = resolve_lammps_executable(self.lammps_var.get().strip() or default_lammps_executable())
            self.result = AppSettings(
                workspace_dir=workspace_dir,
                lammps_executable=lammps_executable,
                lammps_core_count=self._initial_settings.lammps_core_count,
                lammps_use_gpu=self._initial_settings.lammps_use_gpu,
                inherit_previous=self._initial_settings.inherit_previous,
                last_modeling_mode=self._initial_settings.last_modeling_mode,
                last_scenario=self._initial_settings.last_scenario,
            )
            save_app_config(
                {
                    "workspace_dir": str(workspace_dir),
                    "lammps_executable": str(lammps_executable),
                    "lammps_core_count": str(self._initial_settings.lammps_core_count),
                    "lammps_use_gpu": "true" if self._initial_settings.lammps_use_gpu else "false",
                    "inherit_previous": "true" if self._initial_settings.inherit_previous else "false",
                    "last_modeling_mode": self._initial_settings.last_modeling_mode,
                    "last_scenario": self._initial_settings.last_scenario,
                }
            )
            self.destroy()
        except Exception as exc:
            messagebox.showerror("设置失败", str(exc), parent=self)

    def _cancel(self) -> None:
        self.result = None
        self.destroy()


DEFAULT_SOURCE = data_resource_path("final.lmp")
DEFAULT_OUTPUT = WORK_DIR / "final_HEA.lmp"
DEFAULT_GEOMETRY = WORK_DIR / "final.lmp"
DEFAULT_GEOMETRY_CRACK = WORK_DIR / "final_crack.lmp"
DEFAULT_GRADIENT = WORK_DIR / "gradient.txt"
DEFAULT_SEED = WORK_DIR / "seed.xsf"
DEFAULT_LOGICAL_LATTICE = 4.046
DEFAULT_HCP_C_OVER_A = 1.633
DEFAULT_OUTPUT_ATOMSK = "Al"
DEFAULT_RECIPE = "Fe20Co20Ni20Cr20Mn20"
DEFAULT_PRESET_3 = "Co33.3333Cr33.3333Ni33.3334"
DEFAULT_PRESET_5 = "Fe20Co20Ni20Cr20Mn20"
DEFAULT_PRESET_7 = "Al14.2857Co14.2857Cr14.2857Fe14.2857Mn14.2857Ni14.2857Ti14.2857"
DEFAULT_SIMPLE_GRAIN_SCALE = 80.0
DEFAULT_POWDER_SHAPE = "sphere"
CRYSTAL_STRUCTURE_CHOICES = ("fcc", "bcc", "hcp", "sc", "diamond")
CRYSTAL_STRUCTURE_DEFAULTS: dict[str, tuple[float, float | None]] = {
    "fcc": (DEFAULT_LOGICAL_LATTICE, None),
    "bcc": (2.866, None),
    "hcp": (2.950, DEFAULT_HCP_C_OVER_A),
    "sc": (3.000, None),
    "diamond": (5.431, None),
}
POWDER_SHAPE_PRESETS = ("sphere", "cube", "ellipsoid", "cylinder", "octahedron")
POLYCRYSTAL_LAYOUT_MODES = ("grid", "random")
SINGLE_CRYSTAL_ORIENTATIONS = ("100", "110", "111")
SINGLE_CRYSTAL_DEFECT_MODES = ("perfect", "grain_boundary", "edge_dislocation", "screw_dislocation")
ATOMSK_OPERATION_LABELS = {
    "standardize": "格式标准化 / wrap",
    "duplicate": "复制超胞",
    "mirror": "镜像孪晶",
    "mirror_merge": "镜像合并双层",
}
ATOMSK_OPERATION_CHOICES = tuple(ATOMSK_OPERATION_LABELS.values())
FCC_BASIS = (
    (0.0, 0.0, 0.0),
    (0.5, 0.5, 0.0),
    (0.5, 0.0, 0.5),
    (0.0, 0.5, 0.5),
)

BACKGROUND = "#f4f6f8"
PANEL = "#ffffff"
PANEL_ALT = "#f8fafc"
HEADER_BG = "#1f2933"
HEADER_SUBTLE = "#334155"
SIDEBAR_BG = "#111827"
SIDEBAR_HOVER = "#1f2937"
SIDEBAR_ACTIVE = "#0f766e"
SIDEBAR_TEXT = "#e5e7eb"
SIDEBAR_MUTED = "#94a3b8"
ACCENT = "#0f766e"
ACCENT_DARK = "#0b5f59"
ACCENT_SOFT = "#d9f1ef"
SECONDARY_ACCENT = "#4051b5"
TEXT = "#182230"
MUTED = "#667085"
BORDER = "#d0d7de"
SUCCESS = "#168a54"
WARNING = "#b7791f"
DANGER = "#c2410c"


class HoverTooltip:
    def __init__(self, widget: tk.Widget, text: str, *, delay: int = 350, wraplength: int = 320) -> None:
        self.widget = widget
        self.text = text
        self.delay = delay
        self.wraplength = wraplength
        self._after_id: str | None = None
        self._tipwindow: tk.Toplevel | None = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")
        widget.bind("<Motion>", self._follow, add="+")
        widget.bind("<Destroy>", self._on_destroy, add="+")

    def _schedule(self, _event: tk.Event | None = None) -> None:
        self._cancel()
        self._after_id = self.widget.after(self.delay, self._show)

    def _cancel(self) -> None:
        if self._after_id is None:
            return
        try:
            self.widget.after_cancel(self._after_id)
        except tk.TclError:
            pass
        self._after_id = None

    def _show(self) -> None:
        self._after_id = None
        if self._tipwindow is not None or not self.widget.winfo_exists():
            return
        x = self.widget.winfo_pointerx() + 16
        y = self.widget.winfo_pointery() + 20
        tip = tk.Toplevel(self.widget)
        tip.overrideredirect(True)
        try:
            tip.wm_attributes("-topmost", True)
        except tk.TclError:
            pass
        tip.configure(bg="#9dcdf5")
        frame = tk.Frame(tip, bg="#f8fcff", padx=10, pady=6, highlightthickness=1, highlightbackground="#7fb7eb")
        frame.pack(fill="both", expand=True)
        tk.Label(
            frame,
            text=self.text,
            bg="#f8fcff",
            fg=TEXT,
            justify="left",
            wraplength=self.wraplength,
            font=("Microsoft YaHei UI", 9),
        ).pack()
        tip.geometry(f"+{x}+{y}")
        self._tipwindow = tip

    def _follow(self, _event: tk.Event | None = None) -> None:
        if self._tipwindow is None or not self.widget.winfo_exists():
            return
        x = self.widget.winfo_pointerx() + 16
        y = self.widget.winfo_pointery() + 20
        self._tipwindow.geometry(f"+{x}+{y}")

    def _hide(self, _event: tk.Event | None = None) -> None:
        self._cancel()
        if self._tipwindow is not None:
            try:
                self._tipwindow.destroy()
            except tk.TclError:
                pass
            self._tipwindow = None

    def _on_destroy(self, _event: tk.Event | None = None) -> None:
        self._hide()


ELEMENT_MASSES = {
    "H": 1.00794,
    "C": 12.011,
    "Al": 26.9815385,
    "N": 14.0067,
    "O": 15.999,
    "Si": 28.085,
    "Mg": 24.305,
    "Sc": 44.955908,
    "Ti": 47.867,
    "V": 50.9415,
    "Cr": 51.9961,
    "Mn": 54.938044,
    "Fe": 55.845,
    "Co": 58.933194,
    "Ni": 58.6934,
    "Cu": 63.546,
    "Zn": 65.38,
    "Ga": 69.723,
    "Y": 88.90584,
    "Zr": 91.224,
    "Nb": 92.90637,
    "Mo": 95.95,
    "Ru": 101.07,
    "Rh": 102.9055,
    "Pd": 106.42,
    "Ag": 107.8682,
    "Cd": 112.414,
    "In": 114.818,
    "Sn": 118.71,
    "Hf": 178.49,
    "Ta": 180.94788,
    "W": 183.84,
    "Re": 186.207,
    "Os": 190.23,
    "Ir": 192.217,
    "Pt": 195.084,
    "Au": 196.96657,
    "Pb": 207.2,
}

ATOMIC_NUMBERS = {
    "H": 1,
    "C": 6,
    "Al": 13,
    "N": 7,
    "O": 8,
    "Si": 14,
    "Mg": 12,
    "Sc": 21,
    "Ti": 22,
    "V": 23,
    "Cr": 24,
    "Mn": 25,
    "Fe": 26,
    "Co": 27,
    "Ni": 28,
    "Cu": 29,
    "Zn": 30,
    "Ga": 31,
    "Y": 39,
    "Zr": 40,
    "Nb": 41,
    "Mo": 42,
    "Ru": 44,
    "Rh": 45,
    "Pd": 46,
    "Ag": 47,
    "Cd": 48,
    "In": 49,
    "Sn": 50,
    "Hf": 72,
    "Ta": 73,
    "W": 74,
    "Re": 75,
    "Os": 76,
    "Ir": 77,
    "Pt": 78,
    "Au": 79,
    "Pb": 82,
}

PRESET_RECIPES = {
    "3 元均分": DEFAULT_PRESET_3,
    "5 元均分": DEFAULT_PRESET_5,
    "7 元均分": DEFAULT_PRESET_7,
}


SUPPORTED_SOURCE_SUFFIXES = {".lmp", ".data"}
DEFAULT_GEOMETRY_PRESET_NAME = "参考 final.lmp"


@dataclass(frozen=True)
class ModelPreset:
    name: str
    path: Path
    basis: str
    description: str


@dataclass(frozen=True)
class GeometryPreset:
    name: str
    width: float
    height: float
    first_layer_count: int
    delta: int
    layers: int
    periodic: bool
    chaos: float
    layout_mode: str
    seed: int | None
    target_grain_size: float | None = None
    boundary_padding: bool = False


@dataclass(frozen=True)
class DopingEntry:
    symbol: str
    operation: str
    region: str
    amount: float
    amount_mode: str
    control: float


MODEL_LIBRARY = [
    ModelPreset(
        name="默认梯度泰森多边形多晶",
        path=data_resource_path("final.lmp"),
        basis="Atomsk 的 polycrystal/Voronoi（泰森多边形）梯度晶粒模型",
        description="适合做梯度晶粒、裂纹起裂和配方替换的基准模型。",
    ),
    ModelPreset(
        name="二维六边形多晶",
        path=model_resource_path("二维六边形多晶", "final.lmp"),
        basis="规则六边形晶粒的二维对照模型",
        description="适合对比理想晶界、规则晶粒与其他随机晶粒模型。",
    ),
    ModelPreset(
        name="二维随机多晶",
        path=model_resource_path("二维随机多晶", "final.lmp"),
        basis="随机泰森多边形/Voronoi 晶粒模型",
        description="适合统计晶粒尺寸分布、随机晶界与离散性研究。",
    ),
    ModelPreset(
        name="二维梯度孪晶多晶",
        path=model_resource_path("二维梯度孪晶多晶", "final.cfg"),
        basis="梯度层状孪晶模型",
        description="适合研究孪晶密度、层厚变化与梯度耦合效应。",
    ),
    ModelPreset(
        name="倾斜孪晶多晶",
        path=model_resource_path("倾斜孪晶多晶", "final.cfg"),
        basis="倾斜孪晶模型",
        description="适合研究倾角、孪晶界面与位错行为。",
    ),
    ModelPreset(
        name="预存孪晶多晶",
        path=model_resource_path("预存孪晶多晶", "final.cfg"),
        basis="预置孪晶模型",
        description="适合固定孪晶边界和对比不同初始结构的研究。",
    ),
    ModelPreset(
        name="双相多晶",
        path=model_resource_path("双相多晶", "final_polycrystal.cfg"),
        basis="Cu/W 双相多晶模型",
        description="适合相界、相失配和双相界面响应研究。",
    ),
    ModelPreset(
        name="K-S取向多晶",
        path=model_resource_path("K-S取向多晶", "final_Fe.lmp"),
        basis="K-S 取向关系相关模型",
        description="适合做取向关系、相界匹配与界面演化研究。",
    ),
]


GEOMETRY_PRESETS: dict[str, GeometryPreset] = {
    "参考 final.lmp": GeometryPreset(
        name="参考 final.lmp",
        width=500.0,
        height=1769.877344877345,
        first_layer_count=2,
        delta=1,
        layers=10,
        periodic=True,
        chaos=0.01,
        layout_mode="layered",
        seed=20260413,
        boundary_padding=False,
    ),
    "Fortran 默认 5 层": GeometryPreset(
        name="Fortran 默认 5 层",
        width=500.0,
        height=1200.0,
        first_layer_count=2,
        delta=1,
        layers=5,
        periodic=True,
        chaos=0.01,
        layout_mode="layered",
        seed=20260413,
        boundary_padding=False,
    ),
    "无周期 10 层": GeometryPreset(
        name="无周期 10 层",
        width=500.0,
        height=1010.0,
        first_layer_count=2,
        delta=1,
        layers=10,
        periodic=False,
        chaos=0.01,
        layout_mode="layered",
        seed=20260413,
    ),
    "六角错位对照": GeometryPreset(
        name="六角错位对照",
        width=500.0,
        height=1010.0,
        first_layer_count=2,
        delta=1,
        layers=10,
        periodic=False,
        chaos=0.01,
        layout_mode="hexagonal",
        seed=20260413,
    ),
    "细晶 5 层": GeometryPreset(
        name="细晶 5 层",
        width=500.0,
        height=1200.0,
        first_layer_count=4,
        delta=1,
        layers=5,
        periodic=True,
        chaos=0.01,
        layout_mode="layered",
        seed=20260413,
        boundary_padding=False,
    ),
}


DOPING_PRESETS: dict[str, list[DopingEntry]] = {
    "无掺杂": [],
    "H 间隙掺杂": [
        DopingEntry(symbol="H", operation="interstitial", region="bulk", amount=0.5, amount_mode="percent", control=1.0),
    ],
    "O 表面吸附": [
        DopingEntry(symbol="O", operation="adsorption", region="top_surface", amount=1.0, amount_mode="percent", control=1.8),
    ],
    "空位缺陷": [
        DopingEntry(symbol="", operation="vacancy", region="bulk", amount=2.0, amount_mode="percent", control=0.0),
    ],
    "Si 置换掺杂": [
        DopingEntry(symbol="Si", operation="substitution", region="bulk", amount=2.0, amount_mode="percent", control=0.0),
    ],
    "界面带掺杂": [
        DopingEntry(symbol="Cu", operation="substitution", region="interface_band", amount=1.0, amount_mode="percent", control=2.0),
    ],
}

DOPING_PRESET_PLACEHOLDER = "请选择模板"

DOPING_OPERATION_LABELS = {
    "substitution": "置换",
    "vacancy": "空位",
    "adsorption": "吸附",
    "interstitial": "间隙",
}

DOPING_OPERATION_VALUES = {label: value for value, label in DOPING_OPERATION_LABELS.items()}

DOPING_REGION_LABELS = {
    "bulk": "整体",
    "top_surface": "上表面",
    "bottom_surface": "下表面",
    "interface_band": "界面带",
}

DOPING_REGION_VALUES = {label: value for value, label in DOPING_REGION_LABELS.items()}

DOPING_AMOUNT_LABELS = {
    "percent": "比例%",
    "count": "个数",
}

DOPING_AMOUNT_VALUES = {label: value for value, label in DOPING_AMOUNT_LABELS.items()}


@dataclass(frozen=True)
class CompositionEntry:
    symbol: str
    weight: float
    mass: float | None


@dataclass(frozen=True)
class AtomRecord:
    atom_id: int
    atom_type: int
    x: float
    y: float
    z: float


@dataclass(frozen=True)
class BoxBounds:
    xlo: float
    xhi: float
    ylo: float
    yhi: float
    zlo: float
    zhi: float

    @property
    def width(self) -> float:
        return self.xhi - self.xlo

    @property
    def height(self) -> float:
        return self.yhi - self.ylo

    @property
    def depth(self) -> float:
        return self.zhi - self.zlo


@dataclass
class LammpsStructure:
    path: Path
    header_lines: list[str]
    mass_lines: list[str]
    atom_lines: list[str]
    tail_lines: list[str]
    atoms: list[AtomRecord]
    box: BoxBounds
    atom_count: int | None
    atom_types: int | None


@dataclass(frozen=True)
class GeometryLayerPreview:
    layer: int
    grains: int
    grain_size: float
    center_y: float


@dataclass(frozen=True)
class GeometryConfig:
    atomsk_path: Path
    width: float
    height: float
    crystal_structure: str
    lattice_parameter: float
    hcp_c_over_a: float | None
    first_layer_count: int
    target_grain_size: float | None
    delta: int
    layers: int
    periodic: bool
    boundary_padding: bool
    chaos: float
    seed: int | None
    layout_mode: str


@dataclass(frozen=True)
class SimplePolycrystalConfig:
    atomsk_path: Path
    length: float
    width: float
    height: float
    crystal_structure: str = "fcc"
    grain_scale: float = DEFAULT_SIMPLE_GRAIN_SCALE
    lattice_parameter: float = DEFAULT_LOGICAL_LATTICE
    hcp_c_over_a: float | None = None
    seed: int | None = None
    layout_mode: str = "grid"


@dataclass(frozen=True)
class VolumeSeed:
    x: float
    y: float
    z: float
    ix: int
    iy: int
    iz: int


@dataclass(frozen=True)
class PowderParticle:
    index: int
    center_x: float
    center_y: float
    center_z: float
    size: float
    shape: str
    atom_count: int


@dataclass(frozen=True)
class NanopowderConfig:
    particle_size: float
    particle_count: int
    shape: str
    lattice_parameter: float = DEFAULT_LOGICAL_LATTICE
    seed: int | None = None


@dataclass(frozen=True)
class SingleCrystalConfig:
    length: float
    width: float
    height: float
    orientation: str
    defect_mode: str
    defect_angle: float = 10.0
    defect_core_radius: float = 6.0
    lattice_parameter: float = DEFAULT_LOGICAL_LATTICE
    seed: int | None = None


@dataclass(frozen=True)
class CrackConfig:
    mode: str
    shape: str
    orientation: str
    edge_side: str
    length: float
    opening: float


@dataclass(frozen=True)
class PipelineResult:
    source_path: Path
    final_path: Path
    atom_count: int
    atom_types: int
    removed_atoms: int


@dataclass(frozen=True)
class AtomskPostprocessConfig:
    atomsk_path: Path
    source_path: Path
    output_path: Path
    operation: str
    duplicate: tuple[int, int, int] = (1, 1, 1)
    mirror_axis: str = "Y"


@dataclass(frozen=True)
class AtomskCommandPlan:
    commands: list[list[str]]
    temporary_paths: tuple[Path, ...]
    description: str


COUNT_RE = re.compile(r"^\s*(\d+)\s+atoms?\s*(?:#.*)?$", re.IGNORECASE)
TYPE_RE = re.compile(r"^\s*(\d+)\s+atom types?\s*(?:#.*)?$", re.IGNORECASE)
BOX_RE = re.compile(
    r"^\s*([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+(xlo xhi|ylo yhi|zlo zhi)\s*(?:#.*)?$",
    re.IGNORECASE,
)


def normalize_symbol(text: str) -> str:
    value = text.strip()
    if not value:
        return ""
    if len(value) == 1:
        return value.upper()
    return value[0].upper() + value[1:].lower()


def element_mass(symbol: str) -> float | None:
    return ELEMENT_MASSES.get(normalize_symbol(symbol))


def element_number(symbol: str) -> int:
    normalized = normalize_symbol(symbol)
    if normalized in ATOMIC_NUMBERS:
        return ATOMIC_NUMBERS[normalized]
    return sum(ord(char) for char in normalized)


def element_color(symbol: str) -> str:
    number = element_number(symbol)
    hue = (number * 0.61803398875) % 1.0
    lightness = 0.58
    saturation = 0.52
    red, green, blue = colorsys.hls_to_rgb(hue, lightness, saturation)
    return "#{:02x}{:02x}{:02x}".format(int(red * 255), int(green * 255), int(blue * 255))


def choose_foreground(color_hex: str) -> str:
    red = int(color_hex[1:3], 16)
    green = int(color_hex[3:5], 16)
    blue = int(color_hex[5:7], 16)
    brightness = 0.299 * red + 0.587 * green + 0.114 * blue
    return "#111111" if brightness > 150 else "#ffffff"


def parse_float(text: str, label: str) -> float:
    try:
        value = float(text)
    except ValueError as exc:
        raise ValueError(f"{label} 不是有效数字") from exc
    if math.isnan(value) or math.isinf(value):
        raise ValueError(f"{label} 不能是无穷或 NaN")
    return value


def parse_int(text: str, label: str) -> int:
    stripped = text.strip()
    if not re.fullmatch(r"[-+]?\d+", stripped):
        raise ValueError(f"{label} 不是有效整数")
    try:
        return int(stripped)
    except ValueError as exc:
        raise ValueError(f"{label} 不是有效整数") from exc


def parse_positive_float(text: str, label: str) -> float:
    value = parse_float(text, label)
    if value <= 0:
        raise ValueError(f"{label} 必须大于 0")
    return value


def parse_optional_float_value(text: str, label: str) -> float | None:
    stripped = text.strip()
    if not stripped:
        return None
    return parse_float(stripped, label)


def parse_positive_int(text: str, label: str, *, default: int | None = None) -> int:
    stripped = text.strip()
    if not stripped and default is not None:
        return default
    value = parse_int(stripped, label)
    if value <= 0:
        raise ValueError(f"{label} 必须大于 0")
    return value


def parse_optional_float(text: str) -> float | None:
    stripped = text.strip()
    if not stripped:
        return None
    value = parse_float(stripped, "数值")
    if value <= 0:
        return None
    return value


def normalize_atomsk_operation(value: str) -> str:
    stripped = value.strip()
    if stripped in ATOMSK_OPERATION_LABELS:
        return stripped
    for key, label in ATOMSK_OPERATION_LABELS.items():
        if stripped == label:
            return key
    raise ValueError(f"不支持的 Atomsk 操作: {value}")


def normalize_atomsk_axis(value: str) -> str:
    axis = value.strip().upper()
    if axis not in {"X", "Y", "Z"}:
        raise ValueError(f"Atomsk 轴向必须是 X、Y 或 Z: {value}")
    return axis


def parse_atomsk_duplicate_factors(x_text: str, y_text: str, z_text: str) -> tuple[int, int, int]:
    return (
        parse_positive_int(x_text, "Atomsk X 复制倍数"),
        parse_positive_int(y_text, "Atomsk Y 复制倍数"),
        parse_positive_int(z_text, "Atomsk Z 复制倍数"),
    )


def normalize_crystal_structure(value: str) -> str:
    structure = value.strip().lower() or "fcc"
    if structure not in CRYSTAL_STRUCTURE_DEFAULTS:
        raise ValueError(f"不支持的种晶晶体结构: {value}")
    return structure


def crystal_structure_defaults(structure: str) -> tuple[float, float | None]:
    normalized = normalize_crystal_structure(structure)
    return CRYSTAL_STRUCTURE_DEFAULTS[normalized]


def build_atomsk_create_command(
    atomsk_exe: Path,
    crystal_structure: str,
    lattice_parameter: float,
    output_path: Path | str,
    *,
    hcp_c_over_a: float | None = None,
) -> list[str]:
    structure = normalize_crystal_structure(crystal_structure)
    command = [str(atomsk_exe), "--create", structure, f"{lattice_parameter:.8f}"]
    if structure == "hcp":
        c_over_a = hcp_c_over_a if hcp_c_over_a and hcp_c_over_a > 0 else DEFAULT_HCP_C_OVER_A
        command.append(f"{(lattice_parameter * c_over_a):.8f}")
    command.extend([DEFAULT_OUTPUT_ATOMSK, str(output_path)])
    return command


def detect_atomsk_path() -> Path | None:
    candidates: list[str | None] = [
        shutil.which("atomsk"),
        shutil.which("atomsk.exe"),
        r"E:\Program Files (x86)\Atomsk\atomsk.exe",
        r"C:\Program Files\Atomsk\atomsk.exe",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if path.exists():
            return path
    return None


def find_section_index(lines: list[str], name: str) -> int:
    normalized_name = name.lower()
    for index, line in enumerate(lines):
        if line.strip().lower().startswith(normalized_name):
            return index
    raise ValueError(f"找不到 {name} 段")


def parse_box_bounds(lines: list[str]) -> BoxBounds:
    xlo = xhi = ylo = yhi = zlo = zhi = None
    for line in lines:
        match = BOX_RE.match(line)
        if not match:
            continue
        low = float(match.group(1))
        high = float(match.group(2))
        label = match.group(3).lower()
        if label == "xlo xhi":
            xlo, xhi = low, high
        elif label == "ylo yhi":
            ylo, yhi = low, high
        elif label == "zlo zhi":
            zlo, zhi = low, high
    if xlo is None or xhi is None or ylo is None or yhi is None or zlo is None or zhi is None:
        raise ValueError("LAMMPS 头部缺少盒子边界信息")
    if not all(math.isfinite(value) for value in (xlo, xhi, ylo, yhi, zlo, zhi)):
        raise ValueError("LAMMPS 盒子边界不能包含无穷或 NaN")
    if xhi <= xlo or yhi <= ylo or zhi <= zlo:
        raise ValueError("LAMMPS 盒子上边界必须大于下边界")
    return BoxBounds(xlo, xhi, ylo, yhi, zlo, zhi)


def parse_count(lines: list[str]) -> int | None:
    for line in lines:
        match = COUNT_RE.match(line)
        if match:
            return int(match.group(1))
    return None


def parse_atom_types(lines: list[str]) -> int | None:
    for line in lines:
        match = TYPE_RE.match(line)
        if match:
            return int(match.group(1))
    return None


MASS_ENTRY_RE = re.compile(r"^\s*(\d+)\s+([-+0-9.eE]+)(?:\s+#\s*(.*))?\s*$")


def _symbol_from_mass_comment(comment: str) -> str:
    for token in re.split(r"[\s,]+", comment.strip()):
        cleaned = token.strip("()[]{}:;")
        if not cleaned:
            continue
        candidate = normalize_symbol(cleaned)
        if candidate and element_mass(candidate) is not None:
            return candidate
    return ""


def _symbol_from_mass_value(mass_value: float, *, tolerance: float = 0.5) -> str:
    best_symbol = ""
    best_difference = float("inf")
    for symbol, expected_mass in ELEMENT_MASSES.items():
        difference = abs(expected_mass - mass_value)
        if difference < best_difference:
            best_symbol = symbol
            best_difference = difference
    if best_difference <= tolerance:
        return best_symbol
    return ""


def detect_lammps_element_symbols(structure: LammpsStructure) -> list[str]:
    detected: list[tuple[int, str]] = []
    for line in structure.mass_lines:
        stripped = line.strip()
        if not stripped or stripped.lower().startswith("masses") or stripped.startswith("#"):
            continue
        match = MASS_ENTRY_RE.match(line)
        if not match:
            continue
        type_index = int(match.group(1))
        mass_value = float(match.group(2))
        comment = (match.group(3) or "").strip()
        symbol = _symbol_from_mass_comment(comment) or _symbol_from_mass_value(mass_value)
        if symbol:
            detected.append((type_index, symbol))
    detected.sort(key=lambda item: item[0])
    return [symbol for _, symbol in detected]


def split_atoms_section(lines: list[str], atoms_index: int) -> tuple[list[str], list[str]]:
    index = atoms_index + 1
    while index < len(lines) and not lines[index].strip():
        index += 1

    atom_lines: list[str] = []
    while index < len(lines):
        stripped = lines[index].strip()
        if not stripped:
            index += 1
            continue
        if stripped[0].isalpha() or stripped.startswith("#"):
            break
        atom_lines.append(lines[index])
        index += 1

    return atom_lines, lines[index:]


def parse_atom_line(line: str, line_number: int) -> AtomRecord | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    content = line.split("#", 1)[0].strip()
    fields = content.split()
    if len(fields) != 5:
        raise ValueError(f"当前程序只支持 id type x y z 格式的 Atoms 段；第 {line_number} 行无法解析")
    try:
        atom_id = int(fields[0])
        atom_type = int(fields[1])
        x = float(fields[2])
        y = float(fields[3])
        z = float(fields[4])
    except ValueError as exc:
        raise ValueError(f"当前程序只支持 id type x y z 格式的 Atoms 段；第 {line_number} 行无法解析") from exc
    if atom_id <= 0 or atom_type <= 0:
        raise ValueError(f"Atoms 段第 {line_number} 行的 id 和 type 必须为正整数")
    if not all(math.isfinite(value) for value in (x, y, z)):
        raise ValueError(f"Atoms 段第 {line_number} 行坐标不能包含无穷或 NaN")
    return AtomRecord(atom_id=atom_id, atom_type=atom_type, x=x, y=y, z=z)


def parse_atom_lines(atom_lines: list[str]) -> list[AtomRecord]:
    atoms: list[AtomRecord] = []
    for line_number, line in enumerate(atom_lines, start=1):
        atom = parse_atom_line(line, line_number)
        if atom is None:
            continue
        atoms.append(atom)
    if not atoms:
        raise ValueError("没有读取到任何原子坐标")
    return atoms


def read_lammps_structure(path: Path) -> LammpsStructure:
    if not path.exists():
        raise FileNotFoundError(f"找不到输入文件: {path}")

    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    masses_index = find_section_index(lines, "Masses")
    atoms_index = find_section_index(lines, "Atoms")
    header_lines = lines[:masses_index]
    mass_lines = lines[masses_index:atoms_index]
    atom_lines, tail_lines = split_atoms_section(lines, atoms_index)
    atoms = parse_atom_lines(atom_lines)
    box = parse_box_bounds(header_lines)
    atom_count = parse_count(header_lines)
    atom_types = parse_atom_types(header_lines)
    if atom_count is not None and atom_count != len(atoms):
        raise ValueError(f"LAMMPS 头部声明 {atom_count} 个原子，但 Atoms 段读取到 {len(atoms)} 个")
    atom_ids = [atom.atom_id for atom in atoms]
    if len(set(atom_ids)) != len(atom_ids):
        raise ValueError("LAMMPS Atoms 段存在重复 atom id")
    max_atom_type = max((atom.atom_type for atom in atoms), default=0)
    if atom_types is not None and max_atom_type > atom_types:
        raise ValueError(f"LAMMPS 头部声明 {atom_types} 种 atom types，但 Atoms 段出现 type {max_atom_type}")
    return LammpsStructure(
        path=path,
        header_lines=header_lines,
        mass_lines=mass_lines,
        atom_lines=atom_lines,
        tail_lines=tail_lines,
        atoms=atoms,
        box=box,
        atom_count=atom_count,
        atom_types=atom_types,
    )


def replace_count_lines(header_lines: list[str], atom_count: int, atom_types: int) -> list[str]:
    updated: list[str] = []
    found_count = False
    found_types = False
    for line in header_lines:
        count_match = COUNT_RE.match(line)
        if count_match:
            indent_match = re.match(r"^\s*", line)
            indent = indent_match.group(0) if indent_match else ""
            updated.append(f"{indent}{atom_count:>10} atoms")
            found_count = True
            continue
        type_match = TYPE_RE.match(line)
        if type_match:
            indent_match = re.match(r"^\s*", line)
            indent = indent_match.group(0) if indent_match else ""
            updated.append(f"{indent}{atom_types:>10} atom types")
            found_types = True
            continue
        updated.append(line)
    if not found_count:
        raise ValueError("LAMMPS 头部缺少 atoms 行")
    if not found_types:
        raise ValueError("LAMMPS 头部缺少 atom types 行")
    return updated

def replace_box_lines(header_lines: list[str], box: BoxBounds) -> list[str]:
    updated: list[str] = []
    found = {"x": False, "y": False, "z": False}
    for line in header_lines:
        match = BOX_RE.match(line)
        if not match:
            updated.append(line)
            continue
        indent_match = re.match(r"^\s*", line)
        indent = indent_match.group(0) if indent_match else ""
        label = match.group(3).lower()
        if label == "xlo xhi":
            updated.append(f"{indent}{box.xlo:>18.12f} {box.xhi:>18.12f} xlo xhi")
            found["x"] = True
        elif label == "ylo yhi":
            updated.append(f"{indent}{box.ylo:>18.12f} {box.yhi:>18.12f} ylo yhi")
            found["y"] = True
        elif label == "zlo zhi":
            updated.append(f"{indent}{box.zlo:>18.12f} {box.zhi:>18.12f} zlo zhi")
            found["z"] = True
        else:
            updated.append(line)
    if not all(found.values()):
        raise ValueError("LAMMPS 头部缺少盒子边界信息")
    return updated


def _metadata_value(value: object) -> str:
    text = str(value).replace("\n", " ").replace("\r", " ").replace("|", "/")
    return " ".join(text.split())


def format_lammps_title_line(source_path: Path, atom_count: int, atom_types: int) -> str:
    generated_at = datetime.now().isoformat(timespec="seconds")
    source_text = _metadata_value(source_path.as_posix() if isinstance(source_path, Path) else source_path)
    return (
        "# DDOJY generated LAMMPS data"
        f" | generated_at={generated_at}"
        f" | source={source_text}"
        f" | atoms={atom_count}"
        f" | atom_types={atom_types}"
    )


def apply_lammps_title_metadata(header_lines: list[str], source_path: Path, atom_count: int, atom_types: int) -> list[str]:
    updated = list(header_lines)
    title = format_lammps_title_line(source_path, atom_count, atom_types)
    if updated:
        updated[0] = title
        return updated
    return [title, ""]


def format_mass_section(entries: list[CompositionEntry]) -> list[str]:
    lines = ["Masses", ""]
    for index, entry in enumerate(entries, start=1):
        if entry.mass is None or not math.isfinite(entry.mass) or entry.mass <= 0:
            raise ValueError(f"元素 {entry.symbol} 缺少有效原子质量")
        mass_value = entry.mass
        lines.append(f"{index:>10} {mass_value:>18.8f}             # {entry.symbol}")
    lines.append("")
    return lines

def format_box_section(box: BoxBounds) -> list[str]:
    return [
        f"{box.xlo:>18.12f} {box.xhi:>18.12f} xlo xhi",
        f"{box.ylo:>18.12f} {box.yhi:>18.12f} ylo yhi",
        f"{box.zlo:>18.12f} {box.zhi:>18.12f} zlo zhi",
        "",
    ]


def format_atoms_section(atoms: list[AtomRecord], types: list[int]) -> list[str]:
    if len(atoms) != len(types):
        raise ValueError("Atoms 写出失败：原子数量与类型分配数量不一致")
    lines = ["Atoms # atomic", ""]
    for row_index, (atom, atom_type) in enumerate(zip(atoms, types), start=1):
        if atom.atom_id <= 0:
            raise ValueError(f"Atoms 写出失败：第 {row_index} 个原子的 id 必须为正整数")
        if atom_type <= 0:
            raise ValueError(f"Atoms 写出失败：第 {row_index} 个原子的 type 必须为正整数")
        if not all(math.isfinite(value) for value in (atom.x, atom.y, atom.z)):
            raise ValueError(f"Atoms 写出失败：第 {row_index} 个原子的坐标不能包含无穷或 NaN")
        lines.append(f"{atom.atom_id:>10} {atom_type:>4} {atom.x:>20.12f} {atom.y:>20.12f} {atom.z:>20.12f}")
    return lines


def write_lammps_structure(
    path: Path,
    structure: LammpsStructure,
    atoms: list[AtomRecord],
    mass_entries: list[CompositionEntry] | None = None,
    atom_types_count: int | None = None,
    type_assignments: list[int] | None = None,
    box_override: BoxBounds | None = None,
) -> None:
    if type_assignments is None:
        type_assignments = [atom.atom_type for atom in atoms]
    if len(type_assignments) != len(atoms):
        raise ValueError("原子数量与类型分配数量不一致，无法写出 LAMMPS 数据")
    actual_atom_types = max(type_assignments, default=0)
    atom_types = atom_types_count if atom_types_count is not None else (structure.atom_types or 1)
    if mass_entries is not None:
        atom_types = max(atom_types, len(mass_entries))
    if actual_atom_types > atom_types:
        raise ValueError(f"实际 atom type 最大值为 {actual_atom_types}，超过头部声明的 {atom_types}")
    header_lines = replace_count_lines(structure.header_lines, len(atoms), atom_types)
    header_lines = apply_lammps_title_metadata(header_lines, structure.path, len(atoms), atom_types)
    if box_override is not None:
        header_lines = replace_box_lines(header_lines, box_override)
    lines: list[str] = []
    lines.extend(header_lines)
    if mass_entries is None:
        lines.extend(structure.mass_lines)
    else:
        lines.extend(format_mass_section(mass_entries))
    lines.extend(format_atoms_section(atoms, type_assignments))
    lines.extend(structure.tail_lines)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_recipe_text(recipe_text: str) -> list[CompositionEntry]:
    compact = recipe_text.replace("%", "")
    compact = re.sub(r"[\s,;+]+", "", compact.strip())
    if not compact:
        return []
    pattern = re.compile(r"([A-Z][a-z]?)([-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?)?")
    entries: list[CompositionEntry] = []
    index = 0
    while index < len(compact):
        match = pattern.match(compact, index)
        if not match:
            raise ValueError(f"无法解析配方字符串: {compact[index:]}")
        symbol = normalize_symbol(match.group(1))
        mass = element_mass(symbol)
        if mass is None:
            raise ValueError(f"未知或暂不支持的元素符号: {symbol}")
        weight = float(match.group(2)) if match.group(2) else 1.0
        if not math.isfinite(weight) or weight <= 0:
            raise ValueError(f"元素 {symbol} 的配方权重必须为正有限数")
        entries.append(CompositionEntry(symbol=symbol, weight=weight, mass=mass))
        index = match.end()
    merged: dict[str, CompositionEntry] = {}
    order: list[str] = []
    for entry in entries:
        if entry.symbol not in merged:
            merged[entry.symbol] = CompositionEntry(entry.symbol, entry.weight, entry.mass)
            order.append(entry.symbol)
        else:
            current = merged[entry.symbol]
            merged[entry.symbol] = CompositionEntry(
                entry.symbol,
                current.weight + entry.weight,
                entry.mass if entry.mass is not None else current.mass,
            )
    return [merged[symbol] for symbol in order]


def normalize_entries(entries: list[CompositionEntry]) -> list[CompositionEntry]:
    if not entries:
        return []
    for entry in entries:
        if not math.isfinite(entry.weight) or entry.weight <= 0:
            raise ValueError(f"元素 {entry.symbol} 的配方权重必须为正有限数")
    total = sum(entry.weight for entry in entries)
    if total <= 0:
        raise ValueError("配方权重总和必须大于零")
    normalized: list[CompositionEntry] = []
    for entry in entries:
        normalized.append(CompositionEntry(entry.symbol, entry.weight / total, entry.mass))
    return normalized


def format_formula(entries: list[CompositionEntry], percent_digits: int = 4) -> str:
    normalized = normalize_entries(entries)
    if not normalized:
        return ""
    parts = []
    for entry in normalized:
        parts.append(f"{entry.symbol}{entry.weight * 100:.{percent_digits}f}")
    return "".join(parts)


def largest_remainder_counts(weights: list[float], total: int) -> list[int]:
    if total <= 0:
        raise ValueError("原子总数必须大于零")
    if not weights:
        raise ValueError("没有可用的组分")
    if any((not math.isfinite(weight)) or weight < 0 for weight in weights):
        raise ValueError("组分比例不能为负数、无穷或 NaN")
    weight_sum = sum(weights)
    if weight_sum <= 0:
        raise ValueError("组分比例总和必须大于零")
    raw = [weight / weight_sum * total for weight in weights]
    counts = [math.floor(value) for value in raw]
    missing = total - sum(counts)
    order = sorted(range(len(raw)), key=lambda idx: raw[idx] - counts[idx], reverse=True)
    for index in order[:missing]:
        counts[index] += 1
    return counts


def count_assignments(total_atoms: int, entries: list[CompositionEntry]) -> tuple[list[int], list[CompositionEntry]]:
    if not entries:
        return [], []
    counts = largest_remainder_counts([entry.weight for entry in entries], total_atoms)
    return counts, entries


def normalize_doping_operation(operation: str) -> str:
    stripped = operation.strip()
    return DOPING_OPERATION_VALUES.get(stripped, stripped)


def normalize_doping_region(region: str) -> str:
    stripped = region.strip()
    return DOPING_REGION_VALUES.get(stripped, stripped)


def normalize_doping_amount_mode(amount_mode: str) -> str:
    stripped = amount_mode.strip()
    return DOPING_AMOUNT_VALUES.get(stripped, stripped)


def select_doping_region_indices(atoms: list[AtomRecord], box: BoxBounds, region: str, control: float) -> list[int]:
    normalized_region = normalize_doping_region(region)
    if normalized_region == "bulk":
        return list(range(len(atoms)))
    if normalized_region == "top_surface":
        surface_band = max(1.0, min(2.5, 0.25 * max(box.depth, 1.0)))
        threshold = box.zhi - surface_band
        return [index for index, atom in enumerate(atoms) if atom.z >= threshold]
    if normalized_region == "bottom_surface":
        surface_band = max(1.0, min(2.5, 0.25 * max(box.depth, 1.0)))
        threshold = box.zlo + surface_band
        return [index for index, atom in enumerate(atoms) if atom.z <= threshold]
    if normalized_region == "interface_band":
        band_width = control if control > 0 else max(2.0, 0.15 * max(box.height, 1.0))
        center_y = 0.5 * (box.ylo + box.yhi)
        half_band = 0.5 * band_width
        return [index for index, atom in enumerate(atoms) if abs(atom.y - center_y) <= half_band]
    raise ValueError(f"未知掺杂区域: {region}")


def resolve_doping_target_count(amount: float, amount_mode: str, available_count: int) -> int:
    if available_count <= 0:
        return 0
    if not math.isfinite(amount) or amount <= 0:
        raise ValueError("掺杂数量必须为正有限数")
    normalized_mode = normalize_doping_amount_mode(amount_mode)
    if normalized_mode == "percent":
        if amount > 100:
            raise ValueError("掺杂比例不能超过 100%")
        target_count = math.floor(available_count * amount / 100.0 + 0.5)
    elif normalized_mode == "count":
        target_count = math.floor(amount + 0.5)
    else:
        raise ValueError(f"未知掺杂单位: {amount_mode}")
    return min(available_count, max(1, target_count))


def choose_doping_indices(indices: list[int], count: int, rng: random.Random) -> list[int]:
    if count <= 0 or not indices:
        return []
    shuffled = list(indices)
    rng.shuffle(shuffled)
    return shuffled[: min(count, len(shuffled))]


def expand_box_to_atoms(box: BoxBounds, atoms: list[AtomRecord]) -> BoxBounds:
    if not atoms:
        return box
    x_values = [atom.x for atom in atoms]
    y_values = [atom.y for atom in atoms]
    z_values = [atom.z for atom in atoms]
    return BoxBounds(
        xlo=min(box.xlo, min(x_values)),
        xhi=max(box.xhi, max(x_values)),
        ylo=min(box.ylo, min(y_values)),
        yhi=max(box.yhi, max(y_values)),
        zlo=min(box.zlo, min(z_values)),
        zhi=max(box.zhi, max(z_values)),
    )


def apply_doping_entries(
    structure: LammpsStructure,
    atoms: list[AtomRecord],
    type_assignments: list[int],
    mass_entries: list[CompositionEntry],
    entries: list[DopingEntry],
    *,
    enabled: bool,
    seed: int,
) -> tuple[list[AtomRecord], list[int], list[CompositionEntry], BoxBounds, list[str]]:
    working_atoms = [AtomRecord(atom_id=atom.atom_id, atom_type=atom.atom_type, x=atom.x, y=atom.y, z=atom.z) for atom in atoms]
    working_types = list(type_assignments)
    working_mass_entries = list(mass_entries)
    box = structure.box
    summaries: list[str] = []

    if not enabled or not entries:
        final_atoms = [
            AtomRecord(atom_id=index, atom_type=atom_type, x=atom.x, y=atom.y, z=atom.z)
            for index, (atom, atom_type) in enumerate(zip(working_atoms, working_types), start=1)
        ]
        return final_atoms, working_types, working_mass_entries, box, summaries

    symbol_to_type = {entry.symbol: index for index, entry in enumerate(working_mass_entries, start=1)}

    def ensure_type(symbol: str) -> int:
        normalized_symbol = normalize_symbol(symbol)
        if not normalized_symbol:
            raise ValueError("掺杂元素不能为空")
        existing = symbol_to_type.get(normalized_symbol)
        if existing is not None:
            return existing
        mass = element_mass(normalized_symbol)
        if mass is None:
            raise ValueError(f"元素 {normalized_symbol} 缺少质量数据，无法添加到掺杂类型中")
        working_mass_entries.append(CompositionEntry(symbol=normalized_symbol, weight=0.0, mass=mass))
        type_id = len(working_mass_entries)
        symbol_to_type[normalized_symbol] = type_id
        return type_id

    for row_index, entry in enumerate(entries, start=1):
        operation = normalize_doping_operation(entry.operation)
        region = normalize_doping_region(entry.region)
        amount_mode = normalize_doping_amount_mode(entry.amount_mode)
        if entry.amount <= 0:
            raise ValueError(f"掺杂第 {row_index} 行的数量必须大于 0")
        if operation not in DOPING_OPERATION_LABELS:
            raise ValueError(f"掺杂第 {row_index} 行的操作无效: {entry.operation}")
        if region not in DOPING_REGION_LABELS:
            raise ValueError(f"掺杂第 {row_index} 行的区域无效: {entry.region}")

        region_indices = select_doping_region_indices(working_atoms, box, region, entry.control)
        if not region_indices:
            raise ValueError(f"掺杂第 {row_index} 行在当前区域中没有可用原子")

        target_count = resolve_doping_target_count(entry.amount, amount_mode, len(region_indices))
        rng = random.Random(seed + row_index * 10007)

        if operation == "vacancy":
            target_count = min(target_count, len(region_indices))
            selected_indices = choose_doping_indices(region_indices, target_count, rng)
            selected_set = set(selected_indices)
            paired = [
                (atom, atom_type)
                for index, (atom, atom_type) in enumerate(zip(working_atoms, working_types))
                if index not in selected_set
            ]
            if not paired:
                raise ValueError(f"掺杂第 {row_index} 行删除后结构为空")
            working_atoms = [atom for atom, _ in paired]
            working_types = [atom_type for _, atom_type in paired]
            summaries.append(f"第 {row_index} 行 空位: 删除 {len(selected_indices)} 个原子")
        elif operation == "substitution":
            target_count = min(target_count, len(region_indices))
            selected_indices = choose_doping_indices(region_indices, target_count, rng)
            dopant_type = ensure_type(entry.symbol)
            for index in selected_indices:
                working_types[index] = dopant_type
            summaries.append(f"第 {row_index} 行 置换: 将 {len(selected_indices)} 个原子替换为 {normalize_symbol(entry.symbol)}")
        elif operation in {"adsorption", "interstitial"}:
            dopant_type = ensure_type(entry.symbol)
            selected_indices = choose_doping_indices(region_indices, target_count, rng)
            offset = abs(entry.control) if entry.control > 0 else (1.8 if operation == "adsorption" else 1.0)
            new_atoms: list[AtomRecord] = []
            new_types: list[int] = []
            for index in selected_indices:
                base_atom = working_atoms[index]
                if region == "top_surface":
                    z_value = box.zhi + offset
                elif region == "bottom_surface":
                    z_value = box.zlo - offset
                else:
                    z_value = base_atom.z + offset
                new_atoms.append(AtomRecord(atom_id=0, atom_type=dopant_type, x=base_atom.x, y=base_atom.y, z=z_value))
                new_types.append(dopant_type)
            working_atoms.extend(new_atoms)
            working_types.extend(new_types)
            summaries.append(f"第 {row_index} 行 {DOPING_OPERATION_LABELS[operation]}: 新增 {len(new_atoms)} 个 {normalize_symbol(entry.symbol)} 原子")
        else:
            raise ValueError(f"不支持的掺杂操作: {entry.operation}")

        box = expand_box_to_atoms(box, working_atoms)

    final_atoms = [
        AtomRecord(atom_id=index, atom_type=atom_type, x=atom.x, y=atom.y, z=atom.z)
        for index, (atom, atom_type) in enumerate(zip(working_atoms, working_types), start=1)
    ]
    return final_atoms, working_types, working_mass_entries, box, summaries


@dataclass(frozen=True)
class GrainNode:
    x: float
    y: float
    layer: int


def derive_first_layer_count(width: float, first_layer_count: int, target_size: float | None) -> int:
    if target_size is not None and target_size > 0:
        derived = max(1, int(round(width / target_size)))
        return derived
    return max(1, first_layer_count)


def normalize_geometry_x(x: float, width: float, *, periodic: bool) -> float:
    return normalize_box_coordinate(x, width, periodic=periodic)


def normalize_box_coordinate(value: float, limit: float, *, periodic: bool = False) -> float:
    if limit <= 0:
        return value
    epsilon = max(min(limit * 1e-4, 0.01), 1e-6)
    if periodic:
        wrapped = value % limit
        if wrapped <= 0:
            return epsilon
        if wrapped >= limit:
            return limit - epsilon
        return wrapped
    return min(limit - epsilon, max(epsilon, value))


def build_geometry_layout(config: GeometryConfig) -> tuple[list[GrainNode], list[GeometryLayerPreview], int, float]:
    first_count = derive_first_layer_count(config.width, config.first_layer_count, config.target_grain_size)
    counts: list[int] = []
    for layer in range(config.layers):
        grains = first_count + layer * config.delta
        if grains <= 0:
            raise ValueError("某一层的晶粒数小于等于 0，请检查第一层晶粒数和层间变化量")
        counts.append(grains)
    grain_sizes = [config.width / grains for grains in counts]
    previews: list[GeometryLayerPreview] = []
    nodes: list[GrainNode] = []
    rng = random.Random(config.seed)
    cumulative_y = 0.0
    for layer_index, grains in enumerate(counts, start=1):
        size = grain_sizes[layer_index - 1]
        center_y = cumulative_y + 0.5 * size
        previews.append(GeometryLayerPreview(layer=layer_index, grains=grains, grain_size=size, center_y=center_y))
        row_shift = 0.0
        if config.layout_mode == "hexagonal" and layer_index % 2 == 0:
            row_shift = -0.5 * size
        for grain_index in range(grains):
            x = (0.5 * size) + grain_index * size + row_shift
            y = center_y
            if config.chaos > 0:
                x += (rng.random() - 0.5) * size * config.chaos
                y += (rng.random() - 0.5) * size * config.chaos
            x = normalize_geometry_x(x, config.width, periodic=config.periodic)
            nodes.append(GrainNode(x=x, y=y, layer=layer_index))
        cumulative_y += size
    box_height = cumulative_y
    if config.periodic:
        y_shift = sum(grain_sizes[1:]) if len(grain_sizes) > 1 else 0.0
        mirror_center = 0.5 * grain_sizes[0]
        shifted_nodes = [GrainNode(x=normalize_geometry_x(node.x, config.width, periodic=True), y=node.y + y_shift, layer=node.layer) for node in nodes]
        mirrored: list[GrainNode] = []
        for node in nodes[first_count:]:
            mirrored_y = 2.0 * mirror_center - node.y + y_shift
            mirrored.append(GrainNode(x=normalize_geometry_x(node.x, config.width, periodic=True), y=mirrored_y, layer=node.layer))
        nodes = shifted_nodes + mirrored
        box_height = 2.0 * cumulative_y - grain_sizes[0]
    if config.boundary_padding and nodes:
        first_layer_nodes = [node for node in nodes if node.layer == 1]
        last_layer_nodes = [node for node in nodes if node.layer == config.layers]
        padded_nodes = [GrainNode(x=normalize_geometry_x(node.x, config.width, periodic=True), y=node.y - box_height, layer=0) for node in first_layer_nodes]
        padded_nodes.extend(GrainNode(x=normalize_geometry_x(node.x, config.width, periodic=True), y=node.y + box_height, layer=config.layers + 1) for node in last_layer_nodes)
        nodes = nodes + padded_nodes
    if config.height > 0:
        scale = config.height / box_height
        nodes = [GrainNode(x=normalize_geometry_x(node.x, config.width, periodic=config.periodic), y=node.y * scale, layer=node.layer) for node in nodes]
        box_height = config.height
    return nodes, previews, len(nodes), box_height


def generate_gradient_text(config: GeometryConfig) -> tuple[str, list[GeometryLayerPreview], int, float]:
    nodes, previews, node_count, box_height = build_geometry_layout(config)
    lines = [f"box {config.width:.12f} {box_height:.12f} 0.000000000000"]
    for node in nodes:
        lines.append(f"node {node.x:.12f} {node.y:.12f} 0.000000000000 random")
    return "\n".join(lines) + "\n", previews, node_count, box_height


def polycrystal_layout_label(layout_mode: str) -> str:
    normalized = layout_mode.strip().lower()
    if normalized == "grid":
        return "规则网格"
    if normalized == "random":
        return "随机播种"
    return layout_mode


def build_uniform_polycrystal_layout(config: SimplePolycrystalConfig) -> tuple[list[VolumeSeed], tuple[int, int, int], tuple[float, float, float], float]:
    if config.length <= 0 or config.width <= 0 or config.height <= 0:
        raise ValueError("多晶建模的长宽高必须大于 0")
    grain_scale = max(20.0, config.grain_scale)
    grid_x = max(2, int(round(config.length / grain_scale)))
    grid_y = max(2, int(round(config.width / grain_scale)))
    grid_z = max(2, int(round(config.height / grain_scale)))
    cell_x = config.length / grid_x
    cell_y = config.width / grid_y
    cell_z = config.height / grid_z
    layout_mode = config.layout_mode.strip().lower()
    if layout_mode not in POLYCRYSTAL_LAYOUT_MODES:
        raise ValueError(f"不支持的三维多晶布局模式: {config.layout_mode}")
    rng = random.Random(config.seed)
    seeds: list[VolumeSeed] = []
    for z_index in range(grid_z):
        for y_index in range(grid_y):
            for x_index in range(grid_x):
                if layout_mode == "random":
                    x = (x_index + 0.12 + rng.random() * 0.76) * cell_x
                    y = (y_index + 0.12 + rng.random() * 0.76) * cell_y
                    z = (z_index + 0.12 + rng.random() * 0.76) * cell_z
                else:
                    jitter = 0.18
                    x = (x_index + 0.5) * cell_x + (rng.random() - 0.5) * cell_x * jitter
                    y = (y_index + 0.5) * cell_y + (rng.random() - 0.5) * cell_y * jitter
                    z = (z_index + 0.5) * cell_z + (rng.random() - 0.5) * cell_z * jitter
                seeds.append(
                    VolumeSeed(
                        x=normalize_box_coordinate(x, config.length),
                        y=normalize_box_coordinate(y, config.width),
                        z=normalize_box_coordinate(z, config.height),
                        ix=x_index,
                        iy=y_index,
                        iz=z_index,
                    )
                )
    return seeds, (grid_x, grid_y, grid_z), (cell_x, cell_y, cell_z), grain_scale


def generate_uniform_polycrystal_text(config: SimplePolycrystalConfig) -> tuple[str, list[VolumeSeed], tuple[int, int, int], tuple[float, float, float], float]:
    seeds, grid, cells, grain_scale = build_uniform_polycrystal_layout(config)
    lines = [f"box {config.length:.12f} {config.width:.12f} {config.height:.12f} 0.000000000000 0.000000000000 0.000000000000"]
    for seed in seeds:
        lines.append(f"node {seed.x:.12f} {seed.y:.12f} {seed.z:.12f} random")
    return "\n".join(lines) + "\n", seeds, grid, cells, grain_scale


def generate_uniform_polycrystal(
    atomsk_exe: Path,
    config: SimplePolycrystalConfig,
    output_path: Path,
    env: dict[str, str] | None = None,
) -> tuple[list[VolumeSeed], tuple[int, int, int], tuple[float, float, float], float]:
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    seed_path = DEFAULT_SEED
    seed_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()
    ensure_seed_file(atomsk_exe, seed_path, config.crystal_structure, config.lattice_parameter, hcp_c_over_a=config.hcp_c_over_a, env=env)
    gradient_path = output_path.parent / "polycrystal_gradient.txt"
    gradient_text, seeds, grid, cells, grain_scale = generate_uniform_polycrystal_text(config)
    gradient_path.write_text(gradient_text, encoding="utf-8")
    generate_polycrystal(atomsk_exe, seed_path, gradient_path, output_path, env=env)
    return seeds, grid, cells, grain_scale


def single_crystal_orientation_axes(orientation: str) -> tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]:
    normalized = orientation.strip().lower()
    if normalized == "100":
        return (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)
    if normalized == "110":
        root2 = math.sqrt(2.0)
        return (0.0, 0.0, 1.0), (1.0 / root2, -1.0 / root2, 0.0), (1.0 / root2, 1.0 / root2, 0.0)
    if normalized == "111":
        root2 = math.sqrt(2.0)
        root3 = math.sqrt(3.0)
        root6 = math.sqrt(6.0)
        return (1.0 / root2, -1.0 / root2, 0.0), (1.0 / root6, 1.0 / root6, -2.0 / root6), (1.0 / root3, 1.0 / root3, 1.0 / root3)
    raise ValueError(f"不支持的单晶晶向: {orientation}")


def single_crystal_orientation_label(orientation: str) -> str:
    normalized = orientation.strip().lower()
    labels = {
        "100": "[100]/[010]/[001] 标准晶面",
        "110": "[001]/[1-10]/[110] 棱柱晶面",
        "111": "[1-10]/[11-2]/[111] 密排晶面",
    }
    return labels.get(normalized, orientation)


def single_crystal_defect_label(defect_mode: str) -> str:
    normalized = defect_mode.strip().lower()
    labels = {
        "perfect": "完美单晶",
        "grain_boundary": "晶界双晶",
        "edge_dislocation": "边位错",
        "screw_dislocation": "螺位错",
    }
    return labels.get(normalized, defect_mode)


def transform_local_point(x: float, y: float, z: float, axes: tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]) -> tuple[float, float, float]:
    x_axis, y_axis, z_axis = axes
    return (
        x * x_axis[0] + y * y_axis[0] + z * z_axis[0],
        x * x_axis[1] + y * y_axis[1] + z * z_axis[1],
        x * x_axis[2] + y * y_axis[2] + z * z_axis[2],
    )


def rotate_xy_point(x: float, y: float, angle_radians: float) -> tuple[float, float]:
    cos_angle = math.cos(angle_radians)
    sin_angle = math.sin(angle_radians)
    return x * cos_angle - y * sin_angle, x * sin_angle + y * cos_angle


def deduplicate_atoms(atoms: list[AtomRecord], tolerance: float = 1e-4) -> list[AtomRecord]:
    if not atoms:
        return []
    scale = 1.0 / max(tolerance, 1e-9)
    seen: set[tuple[int, int, int]] = set()
    unique: list[AtomRecord] = []
    for atom in atoms:
        key = (round(atom.x * scale), round(atom.y * scale), round(atom.z * scale))
        if key in seen:
            continue
        seen.add(key)
        unique.append(atom)
    return unique


def _minimum_image_delta(delta: float, length: float) -> float:
    if length <= 0:
        return delta
    half_length = 0.5 * length
    if delta > half_length:
        return delta - length
    if delta < -half_length:
        return delta + length
    return delta


def prune_close_contact_atoms(
    atoms: list[AtomRecord],
    box: BoxBounds,
    *,
    type_assignments: list[int] | None = None,
    threshold: float = 0.8,
) -> tuple[list[AtomRecord], list[int] | None, int, float]:
    if not atoms:
        return [], [] if type_assignments is not None else None, 0, 0.0
    if type_assignments is not None and len(type_assignments) != len(atoms):
        raise ValueError("原子类型数量与原子数量不一致，无法执行近距离清理")
    if threshold <= 0:
        copied_atoms = [AtomRecord(atom_id=index, atom_type=atom.atom_type, x=atom.x, y=atom.y, z=atom.z) for index, atom in enumerate(atoms, start=1)]
        copied_types = list(type_assignments) if type_assignments is not None else None
        return copied_atoms, copied_types, 0, 0.0

    cell_size = threshold
    box_lengths = (box.width, box.height, box.depth)
    box_lows = (box.xlo, box.ylo, box.zlo)
    cell_counts = [max(1, int(math.ceil(length / cell_size))) if length > 0 else 1 for length in box_lengths]

    def cell_index(value: float, low: float, length: float, cells: int) -> int:
        if cells <= 1 or length <= 0:
            return 0
        relative = (value - low) % length
        index = int(relative / cell_size)
        return min(cells - 1, max(0, index))

    kept_atoms: list[AtomRecord] = []
    kept_types: list[int] | None = [] if type_assignments is not None else None
    cell_map: dict[tuple[int, int, int], list[int]] = {}
    removed_count = 0
    minimum_distance = float("inf")

    for source_index, atom in enumerate(atoms):
        atom_type = atom.atom_type if type_assignments is None else type_assignments[source_index]
        key = (
            cell_index(atom.x, box_lows[0], box_lengths[0], cell_counts[0]),
            cell_index(atom.y, box_lows[1], box_lengths[1], cell_counts[1]),
            cell_index(atom.z, box_lows[2], box_lengths[2], cell_counts[2]),
        )
        is_close_contact = False
        for dx in (-1, 0, 1):
            nx = (key[0] + dx) % cell_counts[0]
            for dy in (-1, 0, 1):
                ny = (key[1] + dy) % cell_counts[1]
                for dz in (-1, 0, 1):
                    nz = (key[2] + dz) % cell_counts[2]
                    for kept_index in cell_map.get((nx, ny, nz), []):
                        kept_atom = kept_atoms[kept_index]
                        dx_value = _minimum_image_delta(atom.x - kept_atom.x, box_lengths[0])
                        dy_value = _minimum_image_delta(atom.y - kept_atom.y, box_lengths[1])
                        dz_value = _minimum_image_delta(atom.z - kept_atom.z, box_lengths[2])
                        distance = math.sqrt(dx_value * dx_value + dy_value * dy_value + dz_value * dz_value)
                        if distance < minimum_distance:
                            minimum_distance = distance
                        if distance < threshold:
                            is_close_contact = True
                            break
                    if is_close_contact:
                        break
                if is_close_contact:
                    break
            if is_close_contact:
                break
        if is_close_contact:
            removed_count += 1
            continue
        kept_index = len(kept_atoms)
        kept_atoms.append(AtomRecord(atom_id=kept_index + 1, atom_type=atom_type, x=atom.x, y=atom.y, z=atom.z))
        if kept_types is not None:
            kept_types.append(atom_type)
        cell_map.setdefault(key, []).append(kept_index)

    if minimum_distance == float("inf"):
        minimum_distance = 0.0
    return kept_atoms, kept_types, removed_count, minimum_distance


def shift_atoms_to_origin(atoms: list[AtomRecord]) -> tuple[list[AtomRecord], BoxBounds]:
    if not atoms:
        raise ValueError("没有可用于构建单晶的原子")
    x_values = [atom.x for atom in atoms]
    y_values = [atom.y for atom in atoms]
    z_values = [atom.z for atom in atoms]
    x_min = min(x_values)
    y_min = min(y_values)
    z_min = min(z_values)
    x_max = max(x_values)
    y_max = max(y_values)
    z_max = max(z_values)
    shifted = [
        AtomRecord(atom_id=atom.atom_id, atom_type=atom.atom_type, x=atom.x - x_min, y=atom.y - y_min, z=atom.z - z_min)
        for atom in atoms
    ]
    return shifted, BoxBounds(0.0, x_max - x_min, 0.0, y_max - y_min, 0.0, z_max - z_min)


def build_single_crystal_structure(config: SingleCrystalConfig) -> tuple[LammpsStructure, list[str], BoxBounds]:
    if config.length <= 0 or config.width <= 0 or config.height <= 0:
        raise ValueError("单晶长宽高必须大于 0")
    orientation = config.orientation.strip().lower()
    defect_mode = config.defect_mode.strip().lower()
    if orientation not in SINGLE_CRYSTAL_ORIENTATIONS:
        raise ValueError(f"不支持的单晶晶向: {config.orientation}")
    if defect_mode not in SINGLE_CRYSTAL_DEFECT_MODES:
        raise ValueError(f"不支持的单晶缺陷模式: {config.defect_mode}")

    lattice = config.lattice_parameter
    axes = single_crystal_orientation_axes(orientation)
    max_cells_x = max(2, int(math.ceil(config.length / lattice)) + 2)
    max_cells_y = max(2, int(math.ceil(config.width / lattice)) + 2)
    max_cells_z = max(2, int(math.ceil(config.height / lattice)) + 2)
    local_atoms: list[AtomRecord] = []
    tolerance = 0.5 * lattice
    for ix in range(-1, max_cells_x + 1):
        for iy in range(-1, max_cells_y + 1):
            for iz in range(-1, max_cells_z + 1):
                for basis_x, basis_y, basis_z in FCC_BASIS:
                    local_x = (ix + basis_x) * lattice
                    local_y = (iy + basis_y) * lattice
                    local_z = (iz + basis_z) * lattice
                    if (
                        -tolerance <= local_x <= config.length + tolerance
                        and -tolerance <= local_y <= config.width + tolerance
                        and -tolerance <= local_z <= config.height + tolerance
                    ):
                        local_atoms.append(AtomRecord(atom_id=0, atom_type=1, x=local_x, y=local_y, z=local_z))
    if not local_atoms:
        raise ValueError("单晶参数过小，未生成到任何原子")

    center_local = (0.5 * config.length, 0.5 * config.width, 0.5 * config.height)
    oriented_atoms: list[AtomRecord] = []
    for atom in local_atoms:
        world_x, world_y, world_z = transform_local_point(atom.x - center_local[0], atom.y - center_local[1], atom.z - center_local[2], axes)
        oriented_atoms.append(AtomRecord(atom_id=0, atom_type=1, x=world_x, y=world_y, z=world_z))

    oriented_atoms, oriented_box = shift_atoms_to_origin(oriented_atoms)

    if defect_mode == "grain_boundary":
        angle = math.radians(config.defect_angle)
        center_x = 0.5 * oriented_box.width
        center_y = 0.5 * oriented_box.height
        band = max(config.defect_core_radius, 1.5)
        boundary_atoms: list[AtomRecord] = []
        for atom in oriented_atoms:
            if atom.x < center_x - band:
                boundary_atoms.append(atom)
            elif atom.x > center_x + band:
                rel_x = atom.x - center_x
                rel_y = atom.y - center_y
                rot_x, rot_y = rotate_xy_point(rel_x, rel_y, angle)
                boundary_atoms.append(AtomRecord(atom_id=atom.atom_id, atom_type=atom.atom_type, x=center_x + rot_x, y=center_y + rot_y, z=atom.z))
        oriented_atoms = boundary_atoms
    elif defect_mode == "edge_dislocation":
        center_x = 0.5 * oriented_box.width
        center_y = 0.5 * oriented_box.height
        core_radius = max(config.defect_core_radius, 1.5)
        burgers = lattice / math.sqrt(2.0)
        poisson_ratio = 0.33
        defect_atoms: list[AtomRecord] = []
        for atom in oriented_atoms:
            dx = atom.x - center_x
            dy = atom.y - center_y
            radius2 = dx * dx + dy * dy
            if radius2 < core_radius * core_radius:
                continue
            safe_radius2 = max(radius2, core_radius * core_radius)
            ux = (burgers / (2.0 * math.pi)) * (math.atan2(dy, dx) + (dx * dy) / (2.0 * (1.0 - poisson_ratio) * safe_radius2))
            uy = -(
                burgers
                / (2.0 * math.pi)
                * (
                    ((1.0 - 2.0 * poisson_ratio) / (4.0 * (1.0 - poisson_ratio))) * math.log(safe_radius2 / (core_radius * core_radius))
                    + (dx * dx - dy * dy) / (4.0 * (1.0 - poisson_ratio) * safe_radius2)
                )
            )
            defect_atoms.append(AtomRecord(atom_id=atom.atom_id, atom_type=atom.atom_type, x=atom.x + ux, y=atom.y + uy, z=atom.z))
        oriented_atoms = defect_atoms
    elif defect_mode == "screw_dislocation":
        center_x = 0.5 * oriented_box.width
        center_y = 0.5 * oriented_box.height
        core_radius = max(config.defect_core_radius, 1.5)
        burgers = lattice / math.sqrt(2.0)
        defect_atoms = []
        for atom in oriented_atoms:
            dx = atom.x - center_x
            dy = atom.y - center_y
            radius2 = dx * dx + dy * dy
            if radius2 < core_radius * core_radius:
                continue
            uz = burgers * math.atan2(dy, dx) / (2.0 * math.pi)
            defect_atoms.append(AtomRecord(atom_id=atom.atom_id, atom_type=atom.atom_type, x=atom.x, y=atom.y, z=atom.z + uz))
        oriented_atoms = defect_atoms

    oriented_atoms = deduplicate_atoms(oriented_atoms)
    oriented_atoms, final_box = shift_atoms_to_origin(oriented_atoms)
    atoms = [AtomRecord(atom_id=index, atom_type=1, x=atom.x, y=atom.y, z=atom.z) for index, atom in enumerate(oriented_atoms, start=1)]
    structure = LammpsStructure(
        path=Path("single_crystal.lmp"),
        header_lines=[
            "# HEA single crystal structure generated by HEA_MEA Designer",
            "",
            f"{len(atoms):>10} atoms",
            f"{1:>10} atom types",
            "",
            *format_box_section(final_box),
        ],
        mass_lines=format_mass_section([CompositionEntry(symbol="Al", weight=1.0, mass=element_mass("Al"))]),
        atom_lines=[],
        tail_lines=[],
        atoms=atoms,
        box=final_box,
        atom_count=len(atoms),
        atom_types=1,
    )
    summary = [
        f"晶向: {single_crystal_orientation_label(orientation)}",
        f"缺陷: {single_crystal_defect_label(defect_mode)}",
        f"原子数: {len(atoms)}",
        f"盒子: {final_box.width:.3f} x {final_box.height:.3f} x {final_box.depth:.3f} Å",
    ]
    return structure, summary, final_box


def powder_shape_axes(size: float, shape: str) -> tuple[float, float, float]:
    half = size * 0.5
    normalized = shape.lower()
    if normalized == "sphere":
        return half, half, half
    if normalized == "cube":
        return half, half, half
    if normalized == "ellipsoid":
        return half, max(size * 0.36, 1e-6), max(size * 0.24, 1e-6)
    if normalized == "cylinder":
        return half, half, half
    if normalized == "octahedron":
        return half, half, half
    raise ValueError(f"不支持的粉末形状: {shape}")


def powder_shape_contains(dx: float, dy: float, dz: float, size: float, shape: str) -> bool:
    half = size * 0.5
    normalized = shape.lower()
    if normalized == "sphere":
        return dx * dx + dy * dy + dz * dz <= half * half
    if normalized == "cube":
        return abs(dx) <= half and abs(dy) <= half and abs(dz) <= half
    if normalized == "ellipsoid":
        ax, ay, az = powder_shape_axes(size, shape)
        return (dx / ax) ** 2 + (dy / ay) ** 2 + (dz / az) ** 2 <= 1.0
    if normalized == "cylinder":
        return dx * dx + dy * dy <= half * half and abs(dz) <= half
    if normalized == "octahedron":
        ax, ay, az = powder_shape_axes(size, shape)
        return abs(dx) / ax + abs(dy) / ay + abs(dz) / az <= 1.0
    raise ValueError(f"不支持的粉末形状: {shape}")


def build_nanopowder_structure(config: NanopowderConfig) -> tuple[LammpsStructure, list[PowderParticle], BoxBounds]:
    if config.particle_size <= 0:
        raise ValueError("粉末大小必须大于 0")
    if config.particle_count <= 0:
        raise ValueError("粉末个数必须大于 0")
    normalized_shape = config.shape.lower()
    if normalized_shape not in set(POWDER_SHAPE_PRESETS):
        raise ValueError(f"不支持的粉末形状: {config.shape}")
    grid_x = max(1, math.ceil(config.particle_count ** (1 / 3)))
    grid_y = max(1, math.ceil(math.sqrt(config.particle_count / grid_x)))
    grid_z = max(1, math.ceil(config.particle_count / (grid_x * grid_y)))
    spacing = max(config.particle_size * 1.9, config.lattice_parameter * 6.0)
    margin = max(config.particle_size * 0.8, config.lattice_parameter * 4.0)
    box = BoxBounds(
        xlo=0.0,
        xhi=margin * 2 + (grid_x - 1) * spacing + config.particle_size,
        ylo=0.0,
        yhi=margin * 2 + (grid_y - 1) * spacing + config.particle_size,
        zlo=0.0,
        zhi=margin * 2 + (grid_z - 1) * spacing + config.particle_size,
    )
    particles: list[PowderParticle] = []
    atoms: list[AtomRecord] = []
    particle_index = 0
    for z_index in range(grid_z):
        for y_index in range(grid_y):
            for x_index in range(grid_x):
                if particle_index >= config.particle_count:
                    break
                center_x = margin + x_index * spacing + config.particle_size * 0.5
                center_y = margin + y_index * spacing + config.particle_size * 0.5
                center_z = margin + z_index * spacing + config.particle_size * 0.5
                particle_atoms = build_nanopowder_particle_atoms(
                    center_x=center_x,
                    center_y=center_y,
                    center_z=center_z,
                    particle_size=config.particle_size,
                    shape=normalized_shape,
                    lattice_parameter=config.lattice_parameter,
                )
                particle_index += 1
                particles.append(
                    PowderParticle(
                        index=particle_index,
                        center_x=center_x,
                        center_y=center_y,
                        center_z=center_z,
                        size=config.particle_size,
                        shape=normalized_shape,
                        atom_count=len(particle_atoms),
                    )
                )
                atoms.extend(particle_atoms)
            if particle_index >= config.particle_count:
                break
        if particle_index >= config.particle_count:
            break
    atoms = [AtomRecord(atom_id=index, atom_type=1, x=atom.x, y=atom.y, z=atom.z) for index, atom in enumerate(atoms, start=1)]
    structure = LammpsStructure(
        path=Path("nanopowder.lmp"),
        header_lines=[
            "# HEA nanopowder structure generated by HEA_MEA Designer",
            "",
            f"{len(atoms):>10} atoms",
            f"{1:>10} atom types",
            "",
            *format_box_section(box),
        ],
        mass_lines=format_mass_section([CompositionEntry(symbol="Al", weight=1.0, mass=element_mass("Al"))]),
        atom_lines=[],
        tail_lines=[],
        atoms=atoms,
        box=box,
        atom_count=len(atoms),
        atom_types=1,
    )
    return structure, particles, box


def build_nanopowder_particle_atoms(
    *,
    center_x: float,
    center_y: float,
    center_z: float,
    particle_size: float,
    shape: str,
    lattice_parameter: float,
) -> list[AtomRecord]:
    cells = max(1, int(math.ceil(particle_size / lattice_parameter))) + 1
    atoms: list[AtomRecord] = []
    for ix in range(-cells, cells + 1):
        for iy in range(-cells, cells + 1):
            for iz in range(-cells, cells + 1):
                for basis_x, basis_y, basis_z in FCC_BASIS:
                    dx = (ix + basis_x) * lattice_parameter
                    dy = (iy + basis_y) * lattice_parameter
                    dz = (iz + basis_z) * lattice_parameter
                    if powder_shape_contains(dx, dy, dz, particle_size, shape):
                        atoms.append(
                            AtomRecord(
                                atom_id=0,
                                atom_type=1,
                                x=center_x + dx,
                                y=center_y + dy,
                                z=center_z + dz,
                            )
                        )
    return atoms


def find_atomsk_exe(user_value: str) -> Path:
    path = Path(user_value.strip()) if user_value.strip() else None
    if path and path.exists():
        return path
    detected = detect_atomsk_path()
    if detected is None:
        raise FileNotFoundError("未找到 atomsk.exe，请在界面里选择 Atomsk 路径")
    return detected


def build_parallel_env(worker_count: int | None) -> dict[str, str]:
    env = os.environ.copy()
    if worker_count is None or worker_count <= 1:
        return env
    value = str(worker_count)
    env.update(
        {
            "OMP_NUM_THREADS": value,
            "OMP_THREAD_LIMIT": value,
            "OPENBLAS_NUM_THREADS": value,
            "MKL_NUM_THREADS": value,
            "NUMEXPR_NUM_THREADS": value,
        }
    )
    return env


def _truncate_process_output(text: str, *, limit: int = 4000) -> str:
    if len(text) <= limit:
        return text
    omitted = len(text) - limit
    return f"{text[:limit]}\n... <truncated {omitted} characters>"


def format_command_failure(command: list[str], result: subprocess.CompletedProcess[str], cwd: Path | None = None) -> str:
    command_text = subprocess.list2cmdline([str(part) for part in command])
    lines = [
        f"命令执行失败，退出码 {result.returncode}",
        f"命令: {command_text}",
    ]
    if cwd is not None:
        lines.append(f"工作目录: {cwd}")
    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    if stdout:
        lines.append("stdout:")
        lines.append(_truncate_process_output(stdout))
    if stderr:
        lines.append("stderr:")
        lines.append(_truncate_process_output(stderr))
    return "\n".join(lines)


def run_command(command: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(format_command_failure(command, result, cwd))
    return result


def convert_source_to_lammps(atomsk_exe: Path, source_path: Path, env: dict[str, str] | None = None) -> Path:
    if not source_path.exists():
        raise FileNotFoundError(f"找不到源文件: {source_path}")
    if source_path.suffix.lower() in SUPPORTED_SOURCE_SUFFIXES:
        return source_path
    cache_dir = WORK_DIR / "source_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_key = hashlib.sha1(str(source_path.resolve()).encode("utf-8", errors="ignore")).hexdigest()[:12]
    converted_path = cache_dir / f"{cache_key}.lmp"
    if converted_path.exists() and converted_path.stat().st_mtime >= source_path.stat().st_mtime:
        return converted_path
    if converted_path.exists():
        converted_path.unlink()
    command = [str(atomsk_exe), str(source_path), str(converted_path)]
    run_command(command, cwd=source_path.parent, env=env)
    return converted_path


def ensure_seed_file(
    atomsk_exe: Path,
    seed_path: Path,
    crystal_structure: str,
    lattice_parameter: float,
    *,
    hcp_c_over_a: float | None = None,
    env: dict[str, str] | None = None,
) -> None:
    seed_path.parent.mkdir(parents=True, exist_ok=True)
    if seed_path.exists():
        seed_path.unlink()
    command = build_atomsk_create_command(
        atomsk_exe,
        crystal_structure,
        lattice_parameter,
        seed_path,
        hcp_c_over_a=hcp_c_over_a,
    )
    run_command(command, cwd=seed_path.parent, env=env)


def generate_polycrystal(atomsk_exe: Path, seed_path: Path, gradient_path: Path, output_path: Path, env: dict[str, str] | None = None) -> None:
    if output_path.exists():
        output_path.unlink()
    command = [str(atomsk_exe), "--polycrystal", str(seed_path), str(gradient_path), str(output_path), "-wrap"]
    run_command(command, cwd=output_path.parent, env=env)


def build_atomsk_postprocess_plan(config: AtomskPostprocessConfig) -> AtomskCommandPlan:
    operation = normalize_atomsk_operation(config.operation)
    axis = normalize_atomsk_axis(config.mirror_axis)
    atomsk = str(config.atomsk_path)
    source = str(config.source_path)
    output = str(config.output_path)
    nx, ny, nz = config.duplicate
    if operation == "standardize":
        return AtomskCommandPlan(
            commands=[[atomsk, source, "-wrap", output]],
            temporary_paths=(),
            description="格式标准化并包裹到盒子内",
        )
    if operation == "duplicate":
        return AtomskCommandPlan(
            commands=[[atomsk, source, "-duplicate", str(nx), str(ny), str(nz), "-wrap", output]],
            temporary_paths=(),
            description=f"复制超胞 {nx} x {ny} x {nz}",
        )
    if operation == "mirror":
        return AtomskCommandPlan(
            commands=[[atomsk, source, "-mirror", "0", axis, "-wrap", output]],
            temporary_paths=(),
            description=f"沿 {axis} 方向镜像构型",
        )
    if operation == "mirror_merge":
        suffix = config.source_path.suffix or ".lmp"
        temporary = config.output_path.with_name(f"{config.output_path.stem}_mirror_tmp{suffix}")
        return AtomskCommandPlan(
            commands=[
                [atomsk, source, "-mirror", "0", axis, "-wrap", str(temporary)],
                [atomsk, "--merge", axis, "2", source, str(temporary), output, "-wrap"],
            ],
            temporary_paths=(temporary,),
            description=f"沿 {axis} 方向生成镜像并合并成双层构型",
        )
    raise ValueError(f"不支持的 Atomsk 操作: {config.operation}")


def write_atomsk_postprocess_report(config: AtomskPostprocessConfig, plan: AtomskCommandPlan, report_path: Path) -> None:
    lines = [
        "Atomsk postprocess report",
        f"Generated at: {datetime.now().isoformat(timespec='seconds')}",
        f"Operation: {ATOMSK_OPERATION_LABELS[normalize_atomsk_operation(config.operation)]}",
        f"Description: {plan.description}",
        f"Atomsk: {config.atomsk_path}",
        f"Source: {config.source_path}",
        f"Output: {config.output_path}",
        f"Duplicate: {config.duplicate[0]} {config.duplicate[1]} {config.duplicate[2]}",
        f"Mirror axis: {normalize_atomsk_axis(config.mirror_axis)}",
        "",
        "Commands:",
    ]
    for command in plan.commands:
        lines.append(subprocess.list2cmdline([str(part) for part in command]))
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_atomsk_postprocess(config: AtomskPostprocessConfig, env: dict[str, str] | None = None) -> tuple[Path, Path]:
    if not config.atomsk_path.exists():
        raise FileNotFoundError(f"找不到 Atomsk: {config.atomsk_path}")
    if not config.source_path.exists():
        raise FileNotFoundError(f"找不到源文件: {config.source_path}")
    if config.source_path.resolve() == config.output_path.resolve():
        raise ValueError("Atomsk 输出文件不能覆盖源文件")
    config.output_path.parent.mkdir(parents=True, exist_ok=True)
    plan = build_atomsk_postprocess_plan(config)
    source_resolved = config.source_path.resolve()
    output_resolved = config.output_path.resolve()
    for temporary in plan.temporary_paths:
        temporary_resolved = temporary.resolve()
        if temporary_resolved == source_resolved:
            raise ValueError(f"Atomsk 临时文件不能覆盖源文件: {temporary}")
        if temporary_resolved == output_resolved:
            raise ValueError(f"Atomsk 临时文件不能覆盖输出文件: {temporary}")
    if config.output_path.exists():
        config.output_path.unlink()
    for temporary in plan.temporary_paths:
        if temporary.exists():
            temporary.unlink()
    for command in plan.commands:
        run_command(command, cwd=config.output_path.parent, env=env)
    for temporary in plan.temporary_paths:
        if temporary.exists():
            temporary.unlink()
    if not config.output_path.exists():
        raise RuntimeError(f"Atomsk 未生成输出文件: {config.output_path}")
    report_path = config.output_path.with_suffix(config.output_path.suffix + ".atomsk.txt")
    write_atomsk_postprocess_report(config, plan, report_path)
    return config.output_path, report_path


def apply_slit_crack(structure: LammpsStructure, config: CrackConfig) -> tuple[list[AtomRecord], int, str]:
    if config.mode == "none":
        return list(structure.atoms), 0, "未启用裂纹"
    if config.length <= 0 or config.opening <= 0:
        raise ValueError("裂纹长度和裂纹开口必须大于 0")
    box = structure.box
    x_center = 0.5 * (box.xlo + box.xhi)
    y_center = 0.5 * (box.ylo + box.yhi)
    kept: list[AtomRecord] = []
    removed = 0
    if config.orientation == "horizontal":
        half_opening = 0.5 * min(config.opening, box.height)
        y_min = y_center - half_opening
        y_max = y_center + half_opening
        if config.mode == "center":
            half_length = 0.5 * min(config.length, box.width)
            x_min = x_center - half_length
            x_max = x_center + half_length
            description = f"中心水平裂纹: 长度 {2 * half_length:.3f} Å, 开口 {2 * half_opening:.3f} Å"
        else:
            length = min(config.length, box.width)
            if config.edge_side == "left":
                x_min = box.xlo
                x_max = box.xlo + length
                description = f"左边缘水平裂纹: 长度 {length:.3f} Å, 开口 {2 * half_opening:.3f} Å"
            elif config.edge_side == "right":
                x_min = box.xhi - length
                x_max = box.xhi
                description = f"右边缘水平裂纹: 长度 {length:.3f} Å, 开口 {2 * half_opening:.3f} Å"
            else:
                raise ValueError("水平裂纹时边缘方向只能是左或右")
        for atom in structure.atoms:
            if config.shape == "ellipse":
                rx = (atom.x - (x_min + x_max)/2.0) / (0.5 * (x_max - x_min)) if x_max > x_min else 0
                ry = (atom.y - (y_min + y_max)/2.0) / (0.5 * (y_max - y_min)) if y_max > y_min else 0
                inside = (rx*rx + ry*ry) <= 1.0
            else:
                inside = x_min <= atom.x <= x_max and y_min <= atom.y <= y_max
            if inside:
                removed += 1
            else:
                kept.append(atom)
    elif config.orientation == "vertical":
        half_opening = 0.5 * min(config.opening, box.width)
        x_min = x_center - half_opening
        x_max = x_center + half_opening
        if config.mode == "center":
            half_length = 0.5 * min(config.length, box.height)
            y_min = y_center - half_length
            y_max = y_center + half_length
            description = f"中心垂直裂纹: 长度 {2 * half_length:.3f} Å, 开口 {2 * half_opening:.3f} Å"
        else:
            length = min(config.length, box.height)
            if config.edge_side == "bottom":
                y_min = box.ylo
                y_max = box.ylo + length
                description = f"下边缘垂直裂纹: 长度 {length:.3f} Å, 开口 {2 * half_opening:.3f} Å"
            elif config.edge_side == "top":
                y_min = box.yhi - length
                y_max = box.yhi
                description = f"上边缘垂直裂纹: 长度 {length:.3f} Å, 开口 {2 * half_opening:.3f} Å"
            else:
                raise ValueError("垂直裂纹时边缘方向只能是上或下")
        for atom in structure.atoms:
            if config.shape == "ellipse":
                rx = (atom.x - (x_min + x_max)/2.0) / (0.5 * (x_max - x_min)) if x_max > x_min else 0
                ry = (atom.y - (y_min + y_max)/2.0) / (0.5 * (y_max - y_min)) if y_max > y_min else 0
                inside = (rx*rx + ry*ry) <= 1.0
            else:
                inside = x_min <= atom.x <= x_max and y_min <= atom.y <= y_max
            if inside:
                removed += 1
            else:
                kept.append(atom)
    else:
        raise ValueError("裂纹方向必须是 horizontal 或 vertical")
    if not kept:
        raise ValueError("裂纹参数过大，所有原子都被删除了")
    reindexed = [AtomRecord(atom_id=index, atom_type=atom.atom_type, x=atom.x, y=atom.y, z=atom.z) for index, atom in enumerate(kept, start=1)]
    return reindexed, removed, description


class CompositionRow:
    def __init__(self, parent: tk.Misc, index: int, on_change, on_clear):
        self.symbol_var = tk.StringVar()
        self.weight_var = tk.StringVar()
        self.mass_var = tk.StringVar()
        self.color = "#d0d7e2"
        self.frame = ttk.Frame(parent)
        self.frame.grid_columnconfigure(1, weight=1)
        self.frame.grid_columnconfigure(2, weight=1)
        self.frame.grid_columnconfigure(3, weight=1)
        self.swatch = tk.Label(self.frame, width=2, text=" ", bg=self.color, relief="flat")
        self.swatch.grid(row=0, column=0, padx=(0, 8), pady=3, sticky="ns")
        self.symbol_box = ttk.Combobox(self.frame, textvariable=self.symbol_var, values=ELEMENT_SYMBOLS, width=10, state="normal")
        self.symbol_box.grid(row=0, column=1, padx=(0, 8), pady=3, sticky="ew")
        self.weight_entry = ttk.Entry(self.frame, textvariable=self.weight_var, width=12)
        self.weight_entry.grid(row=0, column=2, padx=(0, 8), pady=3, sticky="ew")
        self.mass_entry = ttk.Entry(self.frame, textvariable=self.mass_var, width=12)
        self.mass_entry.grid(row=0, column=3, padx=(0, 8), pady=3, sticky="ew")
        self.clear_button = ttk.Button(self.frame, text="清除", width=6, command=on_clear)
        self.clear_button.grid(row=0, column=4, pady=3, sticky="e")
        self._on_change = on_change
        self.symbol_box.bind("<<ComboboxSelected>>", lambda _event: self._changed())
        self.symbol_box.bind("<KeyRelease>", lambda _event: self._changed())
        self.weight_entry.bind("<KeyRelease>", lambda _event: self._changed())
        self.mass_entry.bind("<KeyRelease>", lambda _event: self._changed())

    def _changed(self):
        self.update_color()
        self._on_change()

    def update_color(self):
        symbol = normalize_symbol(self.symbol_var.get())
        self.symbol_var.set(symbol)
        if symbol:
            color = element_color(symbol)
            self.color = color
            self.swatch.configure(bg=color)
            mass = element_mass(symbol)
            if mass is not None and not self.mass_var.get().strip():
                self.mass_var.set(f"{mass:.8f}")
        else:
            self.color = "#d0d7e2"
            self.swatch.configure(bg=self.color)

    def clear(self):
        self.symbol_var.set("")
        self.weight_var.set("")
        self.mass_var.set("")
        self.update_color()

    def load_entry(self, entry: CompositionEntry):
        self.symbol_var.set(entry.symbol)
        self.weight_var.set(f"{entry.weight:g}")
        mass = entry.mass if entry.mass is not None else element_mass(entry.symbol)
        self.mass_var.set(f"{mass:.8f}" if mass is not None else "")
        self.update_color()

    def get_entry(self) -> CompositionEntry | None:
        symbol = normalize_symbol(self.symbol_var.get())
        if not symbol:
            return None
        weight_text = self.weight_var.get().strip()
        if not weight_text:
            raise ValueError(f"元素 {symbol} 的摩尔分数不能为空")
        weight = parse_float(weight_text, f"元素 {symbol} 的摩尔分数")
        if weight <= 0:
            raise ValueError(f"元素 {symbol} 的摩尔分数必须大于 0")
        mass_text = self.mass_var.get().strip()
        if mass_text:
            mass = parse_float(mass_text, f"元素 {symbol} 的质量")
        else:
            mass = element_mass(symbol)
        return CompositionEntry(symbol=symbol, weight=weight, mass=mass)


class DopingRow:
    def __init__(self, parent: tk.Misc, index: int, on_change, on_clear):
        self.index = index
        self.symbol_var = tk.StringVar()
        self.operation_var = tk.StringVar(value=DOPING_OPERATION_LABELS["substitution"])
        self.region_var = tk.StringVar(value=DOPING_REGION_LABELS["bulk"])
        self.amount_var = tk.StringVar()
        self.amount_mode_var = tk.StringVar(value=DOPING_AMOUNT_LABELS["percent"])
        self.control_var = tk.StringVar()
        self.color = "#d0d7e2"
        self.frame = ttk.Frame(parent)
        self.frame.grid_columnconfigure(1, weight=1)
        self.frame.grid_columnconfigure(2, weight=1)
        self.frame.grid_columnconfigure(3, weight=1)
        self.frame.grid_columnconfigure(4, weight=1)
        self.frame.grid_columnconfigure(5, weight=1)
        self.frame.grid_columnconfigure(6, weight=1)
        self.swatch = tk.Label(self.frame, width=2, text=" ", bg=self.color, relief="flat")
        self.swatch.grid(row=0, column=0, padx=(0, 8), pady=3, sticky="ns")
        self.symbol_box = ttk.Combobox(self.frame, textvariable=self.symbol_var, values=ELEMENT_SYMBOLS, width=10, state="normal")
        self.symbol_box.grid(row=0, column=1, padx=(0, 8), pady=3, sticky="ew")
        self.operation_box = ttk.Combobox(self.frame, textvariable=self.operation_var, values=list(DOPING_OPERATION_LABELS.values()), width=10, state="readonly")
        self.operation_box.grid(row=0, column=2, padx=(0, 8), pady=3, sticky="ew")
        self.region_box = ttk.Combobox(self.frame, textvariable=self.region_var, values=list(DOPING_REGION_LABELS.values()), width=12, state="readonly")
        self.region_box.grid(row=0, column=3, padx=(0, 8), pady=3, sticky="ew")
        self.amount_entry = ttk.Entry(self.frame, textvariable=self.amount_var, width=10)
        self.amount_entry.grid(row=0, column=4, padx=(0, 8), pady=3, sticky="ew")
        self.amount_mode_box = ttk.Combobox(self.frame, textvariable=self.amount_mode_var, values=list(DOPING_AMOUNT_LABELS.values()), width=10, state="readonly")
        self.amount_mode_box.grid(row=0, column=5, padx=(0, 8), pady=3, sticky="ew")
        self.control_entry = ttk.Entry(self.frame, textvariable=self.control_var, width=10)
        self.control_entry.grid(row=0, column=6, padx=(0, 8), pady=3, sticky="ew")
        self.clear_button = ttk.Button(self.frame, text="清除", width=6, command=on_clear)
        self.clear_button.grid(row=0, column=7, pady=3, sticky="e")
        self._on_change = on_change
        self.symbol_box.bind("<<ComboboxSelected>>", lambda _event: self._changed())
        self.symbol_box.bind("<KeyRelease>", lambda _event: self._changed())
        self.operation_box.bind("<<ComboboxSelected>>", lambda _event: self._changed())
        self.region_box.bind("<<ComboboxSelected>>", lambda _event: self._changed())
        self.amount_entry.bind("<KeyRelease>", lambda _event: self._changed())
        self.amount_mode_box.bind("<<ComboboxSelected>>", lambda _event: self._changed())
        self.control_entry.bind("<KeyRelease>", lambda _event: self._changed())

    def _changed(self):
        self.update_color()
        self._on_change()

    def update_color(self):
        symbol = normalize_symbol(self.symbol_var.get())
        self.symbol_var.set(symbol)
        if symbol:
            color = element_color(symbol)
            self.color = color
            self.swatch.configure(bg=color)
        else:
            self.color = "#d0d7e2"
            self.swatch.configure(bg=self.color)

    def is_blank(self) -> bool:
        return (
            not self.symbol_var.get().strip()
            and not self.amount_var.get().strip()
            and not self.control_var.get().strip()
            and self.operation_var.get().strip() == DOPING_OPERATION_LABELS["substitution"]
            and self.region_var.get().strip() == DOPING_REGION_LABELS["bulk"]
            and self.amount_mode_var.get().strip() == DOPING_AMOUNT_LABELS["percent"]
        )

    def clear(self):
        self.symbol_var.set("")
        self.operation_var.set(DOPING_OPERATION_LABELS["substitution"])
        self.region_var.set(DOPING_REGION_LABELS["bulk"])
        self.amount_var.set("")
        self.amount_mode_var.set(DOPING_AMOUNT_LABELS["percent"])
        self.control_var.set("")
        self.update_color()

    def load_entry(self, entry: DopingEntry):
        self.symbol_var.set(entry.symbol)
        self.operation_var.set(DOPING_OPERATION_LABELS.get(entry.operation, entry.operation))
        self.region_var.set(DOPING_REGION_LABELS.get(entry.region, entry.region))
        self.amount_var.set(f"{entry.amount:g}")
        self.amount_mode_var.set(DOPING_AMOUNT_LABELS.get(entry.amount_mode, entry.amount_mode))
        self.control_var.set(f"{entry.control:g}")
        self.update_color()

    def get_entry(self) -> DopingEntry | None:
        symbol = normalize_symbol(self.symbol_var.get())
        operation = normalize_doping_operation(self.operation_var.get())
        region = normalize_doping_region(self.region_var.get())
        amount_mode = normalize_doping_amount_mode(self.amount_mode_var.get())
        amount_text = self.amount_var.get().strip()
        if not amount_text:
            raise ValueError(f"掺杂第 {self.index + 1} 行的数量不能为空")
        amount = parse_float(amount_text, f"掺杂第 {self.index + 1} 行的数量")
        if amount <= 0:
            raise ValueError(f"掺杂第 {self.index + 1} 行的数量必须大于 0")
        control_text = self.control_var.get().strip()
        control = parse_float(control_text, f"掺杂第 {self.index + 1} 行的控制参数") if control_text else 0.0
        if control < 0:
            raise ValueError(f"掺杂第 {self.index + 1} 行的控制参数不能小于 0")
        if operation != "vacancy" and not symbol:
            raise ValueError(f"掺杂第 {self.index + 1} 行的元素不能为空")
        if symbol and element_mass(symbol) is None:
            raise ValueError(f"元素 {symbol} 不在当前元素库中")
        if operation == "vacancy":
            symbol = ""
        return DopingEntry(symbol=symbol, operation=operation, region=region, amount=amount, amount_mode=amount_mode, control=control)


ELEMENT_SYMBOLS = sorted(ELEMENT_MASSES.keys())


class AlloyDesignerApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1360x920")
        self.minsize(1240, 860)
        self.configure(bg=BACKGROUND)
        self._refresh_scheduled = False
        self._tooltips: list[HoverTooltip] = []
        self._pending_log_messages: list[str] = []
        self._style = ttk.Style(self)
        try:
            self._style.theme_use("clam")
        except tk.TclError:
            pass
        self._setup_style()
        self._startup_initialized = False
        self.after(0, self._initialize_application)

    def _initialize_application(self) -> None:
        if self._startup_initialized:
            return
        self._startup_initialized = True
        self._app_settings = self._bootstrap_settings()
        set_workspace_dir(self._app_settings.workspace_dir)
        self.workspace_dir = WORK_DIR
        self.lammps_executable = self._app_settings.lammps_executable
        self.data_writer = DataFileWriter()
        self.input_generator = InputGenerator()
        self.lammps_manager = LammpsManager()
        self._lammps_poll_job: str | None = None
        self._last_thermo_points: list[LammpsThermoPoint] = []
        self._startup_splash = self._show_splash_screen()
        self.atomsk_path_var = tk.StringVar(value=str(detect_atomsk_path() or ""))
        self.source_path_var = tk.StringVar(value=str(DEFAULT_SOURCE if DEFAULT_SOURCE.exists() else DEFAULT_GEOMETRY))
        self.output_path_var = tk.StringVar(value=str(DEFAULT_OUTPUT))
        self.workspace_dir_var = tk.StringVar(value=str(self.workspace_dir))
        self.lammps_path_var = tk.StringVar(value=str(self.lammps_executable))
        self.lammps_core_count_var = tk.StringVar(value=str(self._app_settings.lammps_core_count))
        self.lammps_gpu_var = tk.BooleanVar(value=self._app_settings.lammps_use_gpu)
        self.lammps_runtime_summary_var = tk.StringVar(value="正在检测 LAMMPS 运行时能力...")
        self.lammps_runtime_info: LammpsRuntimeInfo | None = None
        self.lammps_gpu_checkbox: ttk.Checkbutton | None = None
        self.lammps_script_preview_text: tk.Text | None = None
        self.model_preset_var = tk.StringVar(value=MODEL_LIBRARY[0].name)
        self.model_info_var = tk.StringVar(
            value="流程已覆盖配方、掺杂、梯度晶粒、单晶/多晶/纳米粉末建模、裂纹、梯度输出和 LAMMPS 接口；工作目录与最近场景会保存到 config.json。"
        )
        self.lammps_scenario_var = tk.StringVar(value=self._app_settings.last_scenario)
        self.lammps_data_file_var = tk.StringVar(value=str(self.source_path_var.get()))
        self.lammps_output_dir_var = tk.StringVar(value=str(self.workspace_dir))
        self.lammps_script_var = tk.StringVar(value=str(self.workspace_dir / "process" / "in.relax_md.lammps"))
        self.lammps_log_var = tk.StringVar(value=str(self.workspace_dir / "process" / "log.lammps"))
        self.lammps_timestep_var = tk.StringVar(value="0.001")
        self.lammps_steps_var = tk.StringVar(value="20000")
        self.lammps_relax_steps_var = tk.StringVar(value="2000")
        self.lammps_temperature_var = tk.StringVar(value="300")
        self.lammps_final_temperature_var = tk.StringVar(value="300")
        self.lammps_pressure_var = tk.StringVar(value="0.0")
        self.lammps_thermo_every_var = tk.StringVar(value="100")
        self.lammps_dump_every_var = tk.StringVar(value="100")
        self.lammps_ensemble_var = tk.StringVar(value="nvt")
        self.lammps_force_field_var = tk.StringVar(value="lj/cut")
        self.lammps_pair_style_override_var = tk.StringVar(value="")
        self.lammps_pair_coeff_override_var = tk.StringVar(value="")
        self.lammps_potential_var = tk.StringVar(value="")
        self.lammps_elements_var = tk.StringVar(value="Fe Co Ni Cr Mn")
        self.lammps_extra_var = tk.StringVar(value="")
        self.lammps_status_var = tk.StringVar(value="就绪")
        self.lammps_script_preview_var = tk.StringVar(value="点击“生成输入”可生成并预览当前 in 文件。")
        self.lammps_type_summary_var = tk.StringVar(value="未识别")
        self.lammps_output_summary_var = tk.StringVar(value="")
        self.lammps_scrollable_frame: ScrollableFrame | None = None
        self.lammps_custom_template_text: tk.Text | None = None
        self.recipe_var = tk.StringVar(value=DEFAULT_RECIPE)
        self.doping_preset_var = tk.StringVar(value=DOPING_PRESET_PLACEHOLDER)
        self.doping_enabled_var = tk.BooleanVar(value=False)
        self.inherit_previous_var = tk.BooleanVar(value=self._app_settings.inherit_previous)
        self.geometry_preset_var = tk.StringVar(value=DEFAULT_GEOMETRY_PRESET_NAME)
        self.modeling_mode_var = tk.StringVar(value=self._app_settings.last_modeling_mode)
        self.poly_layout_var = tk.StringVar(value="grid")
        self.poly_length_var = tk.StringVar(value="300")
        self.poly_width_var = tk.StringVar(value="300")
        self.poly_height_var = tk.StringVar(value="300")
        self.single_length_var = tk.StringVar(value="120")
        self.single_width_var = tk.StringVar(value="120")
        self.single_height_var = tk.StringVar(value="120")
        self.single_orientation_var = tk.StringVar(value="100")
        self.single_defect_var = tk.StringVar(value="perfect")
        self.single_defect_angle_var = tk.StringVar(value="10")
        self.single_defect_core_var = tk.StringVar(value="6")
        self.powder_size_var = tk.StringVar(value="50")
        self.powder_count_var = tk.StringVar(value="8")
        self.powder_shape_var = tk.StringVar(value=DEFAULT_POWDER_SHAPE)
        self.atomsk_operation_var = tk.StringVar(value=ATOMSK_OPERATION_LABELS["duplicate"])
        self.atomsk_duplicate_x_var = tk.StringVar(value="1")
        self.atomsk_duplicate_y_var = tk.StringVar(value="1")
        self.atomsk_duplicate_z_var = tk.StringVar(value="2")
        self.atomsk_mirror_axis_var = tk.StringVar(value="Z")
        self.atomsk_output_var = tk.StringVar(value=str(WORK_DIR / "atomsk_advanced" / "atomsk_model.lmp"))
        self.atomsk_command_preview_var = tk.StringVar(value="Atomsk 命令预览等待参数。")
        self.model_width_var = tk.StringVar(value="500")
        self.model_height_var = tk.StringVar(value="1200")
        self.crystal_structure_var = tk.StringVar(value="fcc")
        self.lattice_param_var = tk.StringVar(value=f"{DEFAULT_LOGICAL_LATTICE:.3f}")
        self.hcp_c_over_a_var = tk.StringVar(value=f"{DEFAULT_HCP_C_OVER_A:.3f}")
        self.first_layer_count_var = tk.StringVar(value="2")
        self.target_grain_size_var = tk.StringVar(value="")
        self.delta_var = tk.StringVar(value="1")
        self.layers_var = tk.StringVar(value="5")
        self.chaos_var = tk.StringVar(value="0.01")
        self.layout_mode_var = tk.StringVar(value="layered")
        self.parallel_workers_var = tk.StringVar(value=str(max(1, min((os.cpu_count() or 1), 8))))
        self.periodic_var = tk.BooleanVar(value=True)
        self.boundary_padding_var = tk.BooleanVar(value=False)
        self.seed_var = tk.StringVar(value="20260413")
        self.crack_mode_var = tk.StringVar(value="none")
        self.crack_orientation_var = tk.StringVar(value="horizontal")
        self.crack_side_var = tk.StringVar(value="left")
        self.crack_shape_var = tk.StringVar(value="rectangle")
        self.crack_length_var = tk.StringVar(value="80")
        self.crack_opening_var = tk.StringVar(value="8")
        self.current_atom_count: int | None = None
        self.current_box: BoxBounds | None = None
        self.current_geometry_preview: list[GeometryLayerPreview] = []
        self.current_geometry_nodes: list[GrainNode] = []
        self.current_geometry_node_count: int = 0
        self.current_geometry_height: float = 0.0
        self._doping_status = tk.StringVar(value="当前未设置掺杂")
        self._refresh_job: str | None = None
        self._structure_cache_key: tuple[str, int, str] | None = None
        self._structure_cache_value: tuple[LammpsStructure, Path] | None = None
        self._modeling_structure_export: LammpsStructure | None = None
        self._modeling_structure_export_label: str = ""
        self._current_lammps_run_config: LammpsInputConfig | None = None
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._refresh_lammps_runtime_info()
        self._load_source_info()
        self._apply_geometry_preset(DEFAULT_GEOMETRY_PRESET_NAME, log=False)
        self._apply_preset(DEFAULT_PRESET_5)
        self._refresh_all()
        if self._startup_splash is not None:
            try:
                self._startup_splash.destroy()
            except tk.TclError:
                pass
        self.deiconify()

    def _bootstrap_settings(self) -> AppSettings:
        raw = load_app_config()
        workspace_dir = resolve_workspace_path(raw.get("workspace_dir", str(WORK_DIR)))
        preferred_lammps = default_lammps_executable()
        lammps_text = str(raw.get("lammps_executable", "")).strip()
        lammps_candidate = Path(lammps_text).expanduser() if lammps_text else preferred_lammps
        try:
            if lammps_candidate.exists():
                resolved_candidate = resolve_lammps_executable(lammps_candidate)
                if _is_packaged_lammps_executable(resolved_candidate):
                    lammps_executable = resolved_candidate
                elif _is_packaged_lammps_executable(preferred_lammps):
                    lammps_executable = preferred_lammps
                else:
                    lammps_executable = resolved_candidate
            else:
                lammps_executable = preferred_lammps
        except Exception:
            lammps_executable = preferred_lammps
        core_count_text = str(raw.get("lammps_core_count", str(max(1, min((os.cpu_count() or 1), 8))))).strip()
        try:
            lammps_core_count = max(1, int(float(core_count_text)))
        except ValueError:
            lammps_core_count = max(1, min((os.cpu_count() or 1), 8))
        lammps_use_gpu = str(raw.get("lammps_use_gpu", "false")).strip().lower() not in {"false", "0", "no"}
        inherit_previous = str(raw.get("inherit_previous", "true")).strip().lower() not in {"false", "0", "no"}
        last_modeling_mode = str(raw.get("last_modeling_mode", "polycrystal"))
        last_scenario = str(raw.get("last_scenario", "NVT Relaxation"))
        dialog = WorkspaceDialog(
            self,
            AppSettings(
                workspace_dir=workspace_dir,
                lammps_executable=lammps_executable,
                lammps_core_count=lammps_core_count,
                lammps_use_gpu=lammps_use_gpu,
                inherit_previous=inherit_previous,
                last_modeling_mode=last_modeling_mode,
                last_scenario=last_scenario,
            ),
        )
        self.wait_window(dialog)
        if dialog.result is None:
            raise SystemExit(0)
        return dialog.result

    def _save_app_settings(self) -> None:
        try:
            save_app_config(
                {
                    "workspace_dir": str(self.workspace_dir),
                    "lammps_executable": str(self.lammps_executable),
                    "lammps_core_count": str(self._lammps_core_count()),
                    "lammps_use_gpu": "true" if self.lammps_gpu_var.get() else "false",
                    "inherit_previous": "true" if self.inherit_previous_var.get() else "false",
                    "last_modeling_mode": self.modeling_mode_var.get(),
                    "last_scenario": self.lammps_scenario_var.get(),
                }
            )
        except Exception:
            pass

    def _workspace_summary_text(self) -> str:
        lammps_status = self.lammps_path_var.get()
        if not lammps_status:
            lammps_status = "未设置"
        runtime_status = self.lammps_runtime_summary_var.get() if hasattr(self, "lammps_runtime_summary_var") else "未检测"
        return (
            f"工作目录: {self.workspace_dir}\n"
            f"LAMMPS: {lammps_status}\n"
            f"运行时: {runtime_status}\n"
            f"当前源文件: {self.source_path_var.get()}\n"
            f"输出文件: {self.output_path_var.get()}"
        )

    def _refresh_home_summary(self) -> None:
        if hasattr(self, "home_summary_var"):
            self.home_summary_var.set(self._workspace_summary_text())
        if hasattr(self, "footer_workspace"):
            self.footer_workspace.configure(text=f"工作目录: {self.workspace_dir}")
        if hasattr(self, "about_summary_var"):
            self.about_summary_var.set(
                f"内置教程与帮助页已载入，可直接浏览使用教程和快速说明。\n"
                f"工作目录: {self.workspace_dir}\nLAMMPS: {self.lammps_path_var.get()}\n运行时: {self.lammps_runtime_summary_var.get()}"
            )

    def _open_workspace_settings(self) -> None:
        dialog = WorkspaceDialog(
            self,
            AppSettings(
                workspace_dir=self.workspace_dir,
                lammps_executable=self.lammps_executable,
                lammps_core_count=self._lammps_core_count(),
                lammps_use_gpu=self.lammps_gpu_var.get(),
                inherit_previous=self.inherit_previous_var.get(),
                last_modeling_mode=self.modeling_mode_var.get(),
                last_scenario=self.lammps_scenario_var.get(),
            ),
        )
        self.wait_window(dialog)
        if dialog.result is None:
            return
        self._apply_workspace_settings(dialog.result)

    def _apply_workspace_settings(self, settings: AppSettings) -> None:
        self.workspace_dir = set_workspace_dir(settings.workspace_dir)
        self.lammps_executable = settings.lammps_executable
        self.inherit_previous_var.set(settings.inherit_previous)
        self.modeling_mode_var.set(settings.last_modeling_mode)
        self.lammps_core_count_var.set(str(settings.lammps_core_count))
        self.lammps_gpu_var.set(settings.lammps_use_gpu)
        self.workspace_dir_var.set(str(self.workspace_dir))
        self.lammps_path_var.set(str(self.lammps_executable))
        self.output_path_var.set(str(DEFAULT_OUTPUT))
        self.lammps_output_dir_var.set(str(self.workspace_dir))
        if hasattr(self, "atomsk_output_var"):
            self.atomsk_output_var.set(str(self._default_atomsk_postprocess_output()))
            self._refresh_atomsk_command_preview()
        self._sync_lammps_output_paths()
        if not self.source_path_var.get().strip() or not Path(self.source_path_var.get()).exists():
            self.source_path_var.set(str(DEFAULT_SOURCE if DEFAULT_SOURCE.exists() else DEFAULT_GEOMETRY))
        self.lammps_data_file_var.set(self.source_path_var.get())
        if hasattr(self, "atomsk_output_var"):
            self._refresh_atomsk_command_preview()
        self._refresh_lammps_runtime_info()
        self._save_app_settings()
        self._refresh_home_summary()
        self._refresh_all()

    def _workspace_dir(self) -> Path:
        return self.workspace_dir

    def _open_workspace_dir(self) -> None:
        directory = self._workspace_dir()
        directory.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["explorer", str(directory)], shell=False)

    def _open_lammps_output_directory(self) -> None:
        directory = self._current_lammps_output_layout().base_dir
        directory.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["explorer", str(directory)], shell=False)

    def _panel(self, parent: tk.Misc, *, background: str = PANEL) -> tk.Frame:
        return tk.Frame(parent, bg=background, highlightbackground=BORDER, highlightthickness=1, bd=0)

    def _home_action_card(
        self,
        parent: tk.Misc,
        title: str,
        detail: str,
        button_text: str,
        command,
        *,
        primary: bool = False,
    ) -> tk.Frame:
        card = self._panel(parent)
        body = tk.Frame(card, bg=PANEL)
        body.pack(fill="both", expand=True, padx=16, pady=14)
        tk.Label(body, text=title, bg=PANEL, fg=TEXT, font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w")
        tk.Label(body, text=detail, bg=PANEL, fg=MUTED, font=("Microsoft YaHei UI", 9), wraplength=310, justify="left").pack(anchor="w", pady=(6, 12))
        ttk.Button(body, text=button_text, style="Accent.TButton" if primary else "TButton", command=command).pack(anchor="w")
        return card

    def _metric_card(self, parent: tk.Misc, label: str, value: str, detail: str, accent: str) -> tk.Frame:
        card = self._panel(parent, background=PANEL_ALT)
        tk.Frame(card, bg=accent, height=4).pack(fill="x")
        body = tk.Frame(card, bg=PANEL_ALT)
        body.pack(fill="both", expand=True, padx=14, pady=12)
        tk.Label(body, text=label, bg=PANEL_ALT, fg=MUTED, font=("Microsoft YaHei UI", 9, "bold")).pack(anchor="w")
        tk.Label(body, text=value, bg=PANEL_ALT, fg=TEXT, font=("Microsoft YaHei UI", 15, "bold")).pack(anchor="w", pady=(4, 0))
        tk.Label(body, text=detail, bg=PANEL_ALT, fg=MUTED, font=("Microsoft YaHei UI", 8), wraplength=190, justify="left").pack(anchor="w", pady=(4, 0))
        return card

    def _adopt_lammps_output_as_source(self, output_path: Path | None = None, *, announce: bool = True) -> bool:
        layout = self._current_lammps_output_layout()
        target_path = (output_path or layout.production.data_file).expanduser()
        if not target_path.exists():
            if announce:
                messagebox.showinfo("接续模型", f"找不到文件: {target_path}")
            return False
        self.source_path_var.set(str(target_path))
        self.lammps_data_file_var.set(str(target_path))
        self._load_source_info()
        detected = self._auto_detect_lammps_elements(target_path, update_status=False)
        self._refresh_all()
        if detected:
            self.lammps_status_var.set(f"已切换到 {target_path.name}，识别到原子类型: {' '.join(detected)}")
        else:
            self.lammps_status_var.set(f"已切换到 {target_path.name}")
        self._append_lammps_console(f"[接续] 已切换到 {target_path}\n")
        return True

    def _on_close(self) -> None:
        try:
            self._save_app_settings()
        except Exception:
            pass
        if self.lammps_manager.is_running():
            if not messagebox.askyesno("退出确认", "LAMMPS 当前正在运行，是否停止并退出？"):
                return
            self.lammps_manager.terminate()
        self.destroy()

    def _build_home_tab(self) -> None:
        self.home_summary_var = tk.StringVar(value=self._workspace_summary_text())
        self.about_summary_var = tk.StringVar(value="")
        root = ttk.Frame(self.tab_home, style="App.TFrame")
        root.pack(fill="both", expand=True)
        hero = self._panel(root)
        hero.pack(fill="x")
        tk.Frame(hero, bg=ACCENT, width=6).pack(side="left", fill="y")
        hero_body = tk.Frame(hero, bg=PANEL)
        hero_body.pack(side="left", fill="both", expand=True, padx=20, pady=18)
        title_row = tk.Frame(hero_body, bg=PANEL)
        title_row.pack(fill="x")
        tk.Label(title_row, text="DDOJY 科研建模工作台", bg=PANEL, fg=TEXT, font=("Microsoft YaHei UI", 22, "bold")).pack(side="left")
        tk.Label(title_row, text=f"v{APP_VERSION}", bg=ACCENT_SOFT, fg=ACCENT_DARK, font=("Microsoft YaHei UI", 9, "bold"), padx=10, pady=3).pack(side="left", padx=(12, 0))
        tk.Label(
            hero_body,
            text="高/中熵合金结构生成、缺陷设计、LAMMPS 输入与运行结果在一个工作台中统一组织。",
            bg=PANEL,
            fg=MUTED,
            font=("Microsoft YaHei UI", 10),
            wraplength=1040,
            justify="left",
        ).pack(anchor="w", pady=(8, 0))

        metrics = ttk.Frame(root, style="App.TFrame")
        metrics.pack(fill="x", pady=(12, 0))
        for column in range(4):
            metrics.columnconfigure(column, weight=1, uniform="metrics")
        self._metric_card(metrics, "版本", APP_VERSION, "单一 VERSION 源", ACCENT).grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self._metric_card(metrics, "验证", "20 tests", "核心逻辑回归", SECONDARY_ACCENT).grid(row=0, column=1, sticky="nsew", padx=8)
        self._metric_card(metrics, "模型库", "9 LMP", "打包资产可读", SUCCESS).grid(row=0, column=2, sticky="nsew", padx=8)
        self._metric_card(metrics, "状态", "Ready", "等待建模任务", WARNING).grid(row=0, column=3, sticky="nsew", padx=(8, 0))

        actions = ttk.Frame(root, style="App.TFrame")
        actions.pack(fill="x", pady=(12, 0))
        for column in range(3):
            actions.columnconfigure(column, weight=1, uniform="actions")
        self._home_action_card(actions, "建模与合金化", "配方、掺杂、单晶/多晶、纳米粉末和裂纹建模。", "进入建模模块", lambda: self.notebook.select(self.tab_modeling), primary=True).grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self._home_action_card(actions, "LAMMPS 工作流", "生成输入脚本、保存预览、启动运行并查看热力学曲线。", "进入 LAMMPS 接口", lambda: self.notebook.select(self.tab_lammps)).grid(row=0, column=1, sticky="nsew", padx=8)
        self._home_action_card(actions, "文档与复现", "查看内置教程、验证命令和发布说明。", "打开教程与帮助", lambda: self.notebook.select(self.tab_about)).grid(row=0, column=2, sticky="nsew", padx=(8, 0))

        lower = ttk.Frame(root, style="App.TFrame")
        lower.pack(fill="both", expand=True, pady=(12, 0))
        lower.columnconfigure(0, weight=3)
        lower.columnconfigure(1, weight=2)
        workflow = self._panel(lower)
        workflow.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        workflow_body = tk.Frame(workflow, bg=PANEL)
        workflow_body.pack(fill="both", expand=True, padx=16, pady=14)
        tk.Label(workflow_body, text="工作流", bg=PANEL, fg=TEXT, font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w")
        steps = ["01 配方设计", "02 掺杂设计", "03 梯度晶粒", "04 单晶/多晶", "05 裂纹处理", "06 输出归档", "07 LAMMPS"]
        step_row = tk.Frame(workflow_body, bg=PANEL)
        step_row.pack(fill="x", pady=(12, 0))
        for index, step in enumerate(steps):
            chip = tk.Label(step_row, text=step, bg=ACCENT_SOFT if index == 0 else PANEL_ALT, fg=ACCENT_DARK if index == 0 else TEXT, font=("Microsoft YaHei UI", 9, "bold"), padx=10, pady=6)
            chip.pack(side="left", padx=(0, 7), pady=(0, 7))
        ttk.Button(workflow_body, text="打开梯度输出", command=lambda: self.notebook.select(self.tab_output)).pack(anchor="w", pady=(10, 0))

        env = self._panel(lower)
        env.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        env_body = tk.Frame(env, bg=PANEL)
        env_body.pack(fill="both", expand=True, padx=16, pady=14)
        tk.Label(env_body, text="环境摘要", bg=PANEL, fg=TEXT, font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w")
        tk.Label(env_body, textvariable=self.home_summary_var, bg=PANEL, fg=TEXT, justify="left", anchor="nw", font=("Consolas", 9), wraplength=440).pack(fill="both", expand=True, pady=(10, 0))
        env_actions = tk.Frame(env_body, bg=PANEL)
        env_actions.pack(fill="x", pady=(12, 0))
        ttk.Button(env_actions, text="打开工作目录", command=self._open_workspace_dir).pack(side="left")
        ttk.Button(env_actions, text="修改工作目录", command=self._open_workspace_settings).pack(side="left", padx=(8, 0))

    def _build_about_tab(self) -> None:
        frame = ttk.Frame(self.tab_about, style="App.TFrame")
        frame.pack(fill="both", expand=True)
        card = ttk.LabelFrame(frame, text="教程与帮助", style="Section.TLabelframe", padding=18)
        card.pack(fill="x")
        tk.Label(card, text="内嵌超级详细教程", bg=PANEL, fg=ACCENT_DARK, font=("Microsoft YaHei UI", 26, "bold")).pack(anchor="w")
        tk.Label(card, text="直接浏览完整操作教程、快速说明和 LAMMPS 参数索引。", bg=PANEL, fg=TEXT, font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w", pady=(4, 0))
        tk.Label(card, textvariable=self.about_summary_var, bg=PANEL, fg=MUTED, justify="left", wraplength=1100, font=("Microsoft YaHei UI", 10)).pack(anchor="w", pady=(10, 0))
        info = ttk.Frame(card)
        info.pack(fill="x", pady=(14, 0))
        ttk.Button(info, text="刷新文档", command=self._refresh_tutorial_view).pack(side="left")
        ttk.Button(info, text="打开使用教程.md", command=lambda: self._open_document(docs_resource_path("使用教程.md"))).pack(side="left", padx=(8, 0))
        ttk.Button(info, text="打开 README_GUI.md", command=lambda: self._open_document(docs_resource_path("README_GUI.md"))).pack(side="left", padx=(8, 0))
        ttk.Button(info, text="进入工作台", command=lambda: self.notebook.select(self.tab_home)).pack(side="left", padx=(8, 0))
        ttk.Button(info, text="进入 LAMMPS 接口", command=lambda: self.notebook.select(self.tab_lammps)).pack(side="left", padx=(8, 0))

        viewer = ttk.LabelFrame(frame, text="可视文档", style="Section.TLabelframe", padding=12)
        viewer.pack(fill="both", expand=True, pady=(12, 0))
        self.tutorial_text = scrolledtext.ScrolledText(
            viewer,
            wrap="word",
            bg="#ffffff",
            fg=TEXT,
            insertbackground=TEXT,
            font=("Microsoft YaHei UI", 10),
            undo=False,
        )
        self.tutorial_text.pack(fill="both", expand=True)
        self._refresh_tutorial_view()

    def _open_document(self, path: Path) -> None:
        if not path.exists():
            messagebox.showinfo("打开文档", f"找不到文档: {path}")
            return
        try:
            os.startfile(str(path))
        except OSError:
            subprocess.Popen(["explorer", str(path)], shell=False)

    def _configure_tutorial_text(self, widget: tk.Text) -> None:
        widget.tag_configure("doc_title", foreground=ACCENT_DARK, font=("Microsoft YaHei UI", 16, "bold"), spacing1=8, spacing3=8)
        widget.tag_configure("doc_path", foreground=MUTED, font=("Microsoft YaHei UI", 9, "italic"), spacing1=0, spacing3=8)
        widget.tag_configure("h1", foreground=ACCENT_DARK, font=("Microsoft YaHei UI", 15, "bold"), spacing1=10, spacing3=6)
        widget.tag_configure("h2", foreground=TEXT, font=("Microsoft YaHei UI", 13, "bold"), spacing1=8, spacing3=4)
        widget.tag_configure("h3", foreground=TEXT, font=("Microsoft YaHei UI", 11, "bold"), spacing1=6, spacing3=3)
        widget.tag_configure("h4", foreground=TEXT, font=("Microsoft YaHei UI", 10, "bold"), spacing1=5, spacing3=2)
        widget.tag_configure("bullet", lmargin1=16, lmargin2=30, spacing1=1)
        widget.tag_configure("table", foreground=TEXT, font=("Consolas", 9), lmargin1=16, lmargin2=16)
        widget.tag_configure("code", foreground=TEXT, background="#f6f8fb", font=("Consolas", 9), lmargin1=16, lmargin2=16, spacing1=4, spacing3=4)
        widget.tag_configure("separator", foreground=BORDER, spacing1=8, spacing3=8)

    def _append_markdown_document(self, widget: tk.Text, title: str, path: Path, *, separator: bool = False) -> None:
        if separator:
            widget.insert("end", "\n" + "=" * 72 + "\n\n", "separator")
        widget.insert("end", f"文档: {title}\n", "doc_title")
        widget.insert("end", f"来源: {path}\n\n", "doc_path")
        if path.exists():
            content = path.read_text(encoding="utf-8", errors="replace")
        else:
            content = f"# {title}\n\n找不到文档: {path}\n"
        in_code = False
        for raw_line in content.splitlines():
            if raw_line.startswith("```"):
                in_code = not in_code
                continue
            start = widget.index("end")
            if in_code:
                widget.insert("end", raw_line + "\n")
                widget.tag_add("code", start, f"{start} lineend")
                continue
            heading = re.match(r"^(#{1,6})\s+(.*)$", raw_line)
            if heading:
                level = min(len(heading.group(1)), 4)
                heading_text = heading.group(2).strip()
                widget.insert("end", heading_text + "\n\n")
                widget.tag_add(f"h{level}", start, f"{start}+{len(heading_text)}c")
                continue
            if raw_line.startswith("|"):
                widget.insert("end", raw_line + "\n")
                widget.tag_add("table", start, f"{start} lineend")
                continue
            bullet = re.match(r"^\s*[-*+]\s+(.*)$", raw_line)
            if bullet:
                bullet_text = f"• {bullet.group(1)}"
                widget.insert("end", bullet_text + "\n")
                widget.tag_add("bullet", start, f"{start} lineend")
                continue
            numbered = re.match(r"^\s*(\d+)\.\s+(.*)$", raw_line)
            if numbered:
                widget.insert("end", f"{numbered.group(1)}. {numbered.group(2)}\n")
                continue
            if not raw_line.strip():
                widget.insert("end", "\n")
                continue
            widget.insert("end", raw_line + "\n")

    def _refresh_tutorial_view(self) -> None:
        tutorial_text = getattr(self, "tutorial_text", None)
        if tutorial_text is None:
            return
        tutorial_text.configure(state="normal")
        tutorial_text.delete("1.0", "end")
        self._configure_tutorial_text(tutorial_text)
        self._append_markdown_document(tutorial_text, "使用教程.md", docs_resource_path("使用教程.md"))
        self._append_markdown_document(tutorial_text, "README_GUI.md", docs_resource_path("README_GUI.md"), separator=True)
        tutorial_text.configure(state="disabled")
        tutorial_text.yview_moveto(0.0)

    def _lammps_scenario_defaults(self, scenario: str) -> dict[str, str]:
        scenario_key = scenario.strip().lower()
        defaults = {
            "nvt relaxation": {
                "timestep": "0.001",
                "steps": "20000",
                "temperature": "300",
                "final_temperature": "300",
                "pressure": "0.0",
                "thermo_every": "100",
                "ensemble": "nvt",
                "force_field": "lj/cut",
                "pair_style_override": "",
                "pair_coeff_override": "",
                "extra": "",
            },
            "npt relaxation": {
                "timestep": "0.001",
                "steps": "30000",
                "temperature": "300",
                "final_temperature": "300",
                "pressure": "0.0",
                "thermo_every": "100",
                "ensemble": "npt",
                "force_field": "lj/cut",
                "pair_style_override": "",
                "pair_coeff_override": "",
                "extra": "",
            },
            "nph relaxation": {
                "timestep": "0.001",
                "steps": "30000",
                "temperature": "300",
                "final_temperature": "300",
                "pressure": "0.0",
                "thermo_every": "100",
                "ensemble": "nph",
                "force_field": "lj/cut",
                "pair_style_override": "",
                "pair_coeff_override": "",
                "extra": "",
            },
            "nve dynamics": {
                "timestep": "0.001",
                "steps": "20000",
                "temperature": "300",
                "final_temperature": "300",
                "pressure": "0.0",
                "thermo_every": "100",
                "ensemble": "nve",
                "force_field": "lj/cut",
                "pair_style_override": "",
                "pair_coeff_override": "",
                "extra": "",
            },
            "energy minimization": {
                "timestep": "0.001",
                "steps": "1000",
                "temperature": "300",
                "final_temperature": "300",
                "pressure": "0.0",
                "thermo_every": "1",
                "ensemble": "minimize",
                "force_field": "lj/cut",
                "pair_style_override": "",
                "pair_coeff_override": "",
                "extra": "",
            },
            "annealing": {
                "timestep": "0.001",
                "steps": "50000",
                "temperature": "1200",
                "final_temperature": "300",
                "pressure": "0.0",
                "thermo_every": "100",
                "ensemble": "nvt",
                "force_field": "lj/cut",
                "pair_style_override": "",
                "pair_coeff_override": "",
                "extra": "",
            },
            "quench cooling": {
                "timestep": "0.001",
                "steps": "50000",
                "temperature": "1500",
                "final_temperature": "300",
                "pressure": "0.0",
                "thermo_every": "100",
                "ensemble": "nvt",
                "force_field": "lj/cut",
                "pair_style_override": "",
                "pair_coeff_override": "",
                "extra": "",
            },
            "uniaxial tension": {
                "timestep": "0.001",
                "steps": "50000",
                "temperature": "300",
                "final_temperature": "300",
                "pressure": "0.0",
                "thermo_every": "100",
                "ensemble": "nvt",
                "force_field": "lj/cut",
                "pair_style_override": "",
                "pair_coeff_override": "",
                "extra": "variable strain_rate equal 1.0e-5",
            },
            "shear deformation": {
                "timestep": "0.001",
                "steps": "50000",
                "temperature": "300",
                "final_temperature": "300",
                "pressure": "0.0",
                "thermo_every": "100",
                "ensemble": "nvt",
                "force_field": "lj/cut",
                "pair_style_override": "",
                "pair_coeff_override": "",
                "extra": "variable shear_rate equal 1.0e-5",
            },
            "nanoindentation": {
                "timestep": "0.001",
                "steps": "40000",
                "temperature": "300",
                "final_temperature": "300",
                "pressure": "0.0",
                "thermo_every": "100",
                "ensemble": "nvt",
                "force_field": "lj/cut",
                "pair_style_override": "",
                "pair_coeff_override": "",
                "extra": "variable indenter_radius equal 20.0",
            },
            "rdf analysis": {
                "timestep": "0.001",
                "steps": "20000",
                "temperature": "300",
                "final_temperature": "300",
                "pressure": "0.0",
                "thermo_every": "100",
                "ensemble": "nvt",
                "force_field": "lj/cut",
                "pair_style_override": "",
                "pair_coeff_override": "",
                "extra": "",
            },
            "custom": {
                "timestep": self.lammps_timestep_var.get(),
                "steps": self.lammps_steps_var.get(),
                "temperature": self.lammps_temperature_var.get(),
                "final_temperature": self.lammps_final_temperature_var.get(),
                "pressure": self.lammps_pressure_var.get(),
                "thermo_every": self.lammps_thermo_every_var.get(),
                "ensemble": self.lammps_ensemble_var.get(),
                "force_field": self.lammps_force_field_var.get(),
                "pair_style_override": self.lammps_pair_style_override_var.get(),
                "pair_coeff_override": self.lammps_pair_coeff_override_var.get(),
                "extra": self.lammps_extra_var.get(),
            },
        }
        return defaults.get(
            scenario_key,
            {
                "timestep": self.lammps_timestep_var.get(),
                "steps": self.lammps_steps_var.get(),
                "temperature": self.lammps_temperature_var.get(),
                "final_temperature": self.lammps_final_temperature_var.get(),
                "pressure": self.lammps_pressure_var.get(),
                "thermo_every": self.lammps_thermo_every_var.get(),
                "ensemble": self.lammps_ensemble_var.get(),
                "force_field": self.lammps_force_field_var.get(),
                "pair_style_override": self.lammps_pair_style_override_var.get(),
                "pair_coeff_override": self.lammps_pair_coeff_override_var.get(),
                "extra": self.lammps_extra_var.get(),
            },
        )

    def _apply_lammps_scenario(self, scenario: str | None = None) -> None:
        selected = scenario or self.lammps_scenario_var.get()
        defaults = self._lammps_scenario_defaults(selected)
        self.lammps_timestep_var.set(defaults["timestep"])
        self.lammps_steps_var.set(defaults["steps"])
        self.lammps_temperature_var.set(defaults["temperature"])
        self.lammps_final_temperature_var.set(defaults["final_temperature"])
        self.lammps_pressure_var.set(defaults["pressure"])
        self.lammps_thermo_every_var.set(defaults["thermo_every"])
        self.lammps_ensemble_var.set(defaults["ensemble"])
        self.lammps_force_field_var.set(defaults["force_field"])
        self.lammps_pair_style_override_var.set(defaults["pair_style_override"])
        self.lammps_pair_coeff_override_var.set(defaults["pair_coeff_override"])
        self.lammps_extra_var.set(defaults["extra"])
        if not self.lammps_data_file_var.get().strip():
            self.lammps_data_file_var.set(self.source_path_var.get())
        self._refresh_home_summary()

    def _sync_lammps_source_from_model(self) -> None:
        self.lammps_data_file_var.set(self.source_path_var.get())
        self.lammps_output_dir_var.set(str(self.workspace_dir))
        self._sync_lammps_output_paths()
        detected = self._auto_detect_lammps_elements(Path(self.lammps_data_file_var.get().strip() or self.source_path_var.get()), update_status=False)
        if detected:
            self.lammps_status_var.set(f"已同步当前建模源文件，已识别原子类型: {' '.join(detected)}")
        else:
            self.lammps_status_var.set("已同步当前建模源文件")

    def _auto_detect_lammps_elements(self, source_path: Path, *, update_status: bool = False) -> list[str]:
        try:
            structure, _resolved_path = self._structure_for_path(source_path)
        except Exception:
            return []
        detected_symbols = detect_lammps_element_symbols(structure)
        atom_type_count = structure.atom_types or max((atom.atom_type for atom in structure.atoms), default=0)
        if detected_symbols and (atom_type_count == 0 or len(detected_symbols) == atom_type_count):
            self.lammps_elements_var.set(" ".join(detected_symbols))
            self.lammps_type_summary_var.set(f"{len(detected_symbols)} 种: {' '.join(detected_symbols)}")
            if update_status:
                self.lammps_status_var.set(f"已识别原子类型: {' '.join(detected_symbols)}")
        elif atom_type_count > 0:
            if detected_symbols:
                self.lammps_type_summary_var.set(f"{len(detected_symbols)}/{atom_type_count} 种: {' '.join(detected_symbols)}")
                if update_status:
                    self.lammps_status_var.set(f"已识别 {len(detected_symbols)}/{atom_type_count} 种原子类型")
            else:
                self.lammps_type_summary_var.set(f"{atom_type_count} 种原子类型（未识别元素名）")
                if update_status:
                    self.lammps_status_var.set(f"已识别 {atom_type_count} 种原子类型")
        else:
            self.lammps_type_summary_var.set("未识别")
        return detected_symbols

    def _lammps_scenario_options(self) -> list[str]:
        return [
            "NVT Relaxation",
            "NPT Relaxation",
            "NPH Relaxation",
            "NVE Dynamics",
            "Energy Minimization",
            "Annealing",
            "Quench Cooling",
            "Uniaxial Tension",
            "Shear Deformation",
            "Nanoindentation",
            "RDF Analysis",
            "Custom",
        ]

    def _lammps_force_field_options(self) -> list[str]:
        return [
            "lj/cut",
            "lj/cut/coul/long",
            "lj/charmm/coul/long",
            "coul/cut",
            "coul/long",
            "buck/coul/long",
            "morse",
            "eam",
            "eam/alloy",
            "eam/fs",
            "eam/cd",
            "eam/cd/old",
            "eam/he",
            "meam",
            "meam/c",
            "meam/ms",
            "tersoff",
            "sw",
            "reax/c",
            "hybrid",
            "hybrid/overlay",
        ]

    def _lammps_core_count(self) -> int:
        text = self.lammps_core_count_var.get().strip()
        if not text:
            return 1
        try:
            return max(1, int(float(text)))
        except ValueError:
            return 1

    def _current_lammps_executable(self) -> Path:
        runtime_text = self.lammps_path_var.get().strip()
        if runtime_text:
            candidate = Path(runtime_text).expanduser()
            try:
                return resolve_lammps_executable(candidate)
            except Exception:
                pass
        return self.lammps_executable

    def _browse_lammps(self) -> None:
        selected = filedialog.askopenfilename(
            title="选择 LAMMPS 可执行文件",
            initialdir=str(DEFAULT_LAMMPS_BIN_DIR if DEFAULT_LAMMPS_BIN_DIR.exists() else ROOT),
            filetypes=[("LAMMPS executable", "*.exe"), ("All files", "*.*")],
        )
        if selected:
            self.lammps_path_var.set(selected)
            self._refresh_lammps_runtime_info()

    def _browse_lammps_directory(self) -> None:
        selected = filedialog.askdirectory(
            title="选择 LAMMPS conda 环境目录",
            initialdir=str(DEFAULT_LAMMPS_BIN_DIR.parent if DEFAULT_LAMMPS_BIN_DIR.exists() else ROOT),
        )
        if selected:
            self.lammps_path_var.set(selected)
            self._refresh_lammps_runtime_info()

    def _refresh_lammps_runtime_info(self) -> None:
        try:
            runtime_info = probe_lammps_runtime(self._current_lammps_executable())
        except Exception as exc:
            self.lammps_runtime_info = None
            self.lammps_runtime_summary_var.set(f"运行时检测失败: {exc}")
            self.lammps_gpu_var.set(False)
            if self.lammps_gpu_checkbox is not None:
                self.lammps_gpu_checkbox.configure(state="disabled")
            self._refresh_home_summary()
            return

        self.lammps_runtime_info = runtime_info
        self.lammps_executable = runtime_info.executable
        self.lammps_path_var.set(str(runtime_info.executable))
        summary_parts: list[str] = []
        if runtime_info.package_dir is not None:
            summary_parts.append("Python 包已配置")
        if runtime_info.supports_mpi:
            summary_parts.append("MPI 可用")
        if runtime_info.supports_openmp:
            summary_parts.append("OpenMP 可用")
        if runtime_info.supports_gpu:
            summary_parts.append("GPU 可用")
        else:
            summary_parts.append("GPU 不可用")
        if runtime_info.supports_kokkos:
            summary_parts.append("KOKKOS 可用")
        if runtime_info.discovery_error:
            summary_parts.append(f"检测提示: {runtime_info.discovery_error}")
        self.lammps_runtime_summary_var.set("；".join(summary_parts) if summary_parts else "未识别运行时能力")
        if self.lammps_gpu_checkbox is not None:
            if runtime_info.supports_gpu:
                self.lammps_gpu_checkbox.configure(state="normal")
            else:
                self.lammps_gpu_var.set(False)
                self.lammps_gpu_checkbox.configure(state="disabled")
        self._refresh_home_summary()

    def _build_lammps_launch_plan(self, executable: Path, config: LammpsInputConfig) -> tuple[list[str], dict[str, str], str]:
        runtime_info = self.lammps_runtime_info or probe_lammps_runtime(executable)
        core_count = self._lammps_core_count()
        env = _runtime_env()
        command: list[str]
        mode_label = "单进程"
        gpu_requested = self.lammps_gpu_var.get() and runtime_info.supports_gpu
        mpi_launcher = shutil.which("mpiexec")

        if gpu_requested:
            if core_count > 1 and runtime_info.supports_mpi and mpi_launcher:
                env["OMP_NUM_THREADS"] = "1"
                command = [mpi_launcher, "-n", str(core_count), str(executable), "-sf", "gpu", "-pk", "gpu", "1"]
                mode_label = f"GPU + MPI × {core_count}"
            else:
                command = [str(executable), "-sf", "gpu", "-pk", "gpu", "1"]
                mode_label = "GPU"
        elif core_count > 1 and runtime_info.supports_mpi and mpi_launcher:
            env["OMP_NUM_THREADS"] = "1"
            command = [mpi_launcher, "-n", str(core_count), str(executable)]
            mode_label = f"MPI × {core_count}"
        elif core_count > 1 and runtime_info.supports_openmp:
            command = [str(executable), "-sf", "omp", "-pk", "omp", str(core_count)]
            env["OMP_NUM_THREADS"] = str(core_count)
            mode_label = f"OpenMP × {core_count}"
        else:
            command = [str(executable)]
            if core_count > 1:
                mode_label = f"单进程（请求 {core_count} 核）"

        command.extend(["-in", str(config.input_script), "-log", str(config.log_file)])
        return command, env, mode_label

    def _set_lammps_template_text(self, text: str) -> None:
        if self.lammps_custom_template_text is None:
            return
        self.lammps_custom_template_text.delete("1.0", "end")
        if text:
            self.lammps_custom_template_text.insert("1.0", text)

    def _get_lammps_template_text(self) -> str:
        if self.lammps_custom_template_text is None:
            return ""
        return self.lammps_custom_template_text.get("1.0", "end").strip()

    def _restore_lammps_template(self) -> None:
        self._set_lammps_template_text(self.input_generator.default_template())

    def _current_lammps_script_path(self) -> Path:
        path_text = self.lammps_script_var.get().strip()
        if path_text:
            return Path(path_text).expanduser()
        return self._current_lammps_output_layout().process_script_file

    def _set_lammps_script_text(self, text: str) -> None:
        if self.lammps_script_preview_text is None:
            return
        self.lammps_script_preview_text.delete("1.0", "end")
        if text:
            self.lammps_script_preview_text.insert("1.0", text)
        try:
            self.lammps_script_preview_text.edit_modified(False)
        except tk.TclError:
            pass

    def _get_lammps_script_text(self) -> str:
        if self.lammps_script_preview_text is None:
            return ""
        return self.lammps_script_preview_text.get("1.0", "end-1c")

    def _refresh_lammps_script_preview(self) -> None:
        try:
            config = self._gather_lammps_input_config()
            script_text = self.input_generator.build_script(config)
        except Exception as exc:
            self.lammps_script_preview_var.set(f"脚本预览失败: {exc}")
            return
        self._set_lammps_script_text(script_text)
        self.lammps_script_preview_var.set(f"脚本预览: {config.input_script}")

    def _load_lammps_script_from_disk(self) -> None:
        path = self._current_lammps_script_path()
        if not path.exists():
            messagebox.showinfo("载入脚本", f"找不到脚本文件: {path}")
            return
        try:
            script_text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            messagebox.showerror("载入脚本失败", str(exc))
            return
        self._set_lammps_script_text(script_text)
        self.lammps_script_preview_var.set(f"已载入脚本: {path}")
        self.lammps_status_var.set(f"已载入 {path.name}")
        self._append_lammps_console(f"[脚本] 已载入: {path}\n")

    def _save_lammps_script_from_editor(self) -> Path | None:
        try:
            script_text = self._get_lammps_script_text().strip()
            if script_text:
                script_text = self._get_lammps_script_text()
            else:
                config = self._gather_lammps_input_config()
                script_text = self.input_generator.build_script(config)
                self._set_lammps_script_text(script_text)
            if not script_text.endswith("\n"):
                script_text += "\n"
            target_path = self._current_lammps_script_path()
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(script_text, encoding="utf-8")
        except Exception as exc:
            messagebox.showerror("保存脚本失败", str(exc))
            return None
        self.lammps_script_preview_var.set(f"脚本已保存: {target_path}")
        self.lammps_status_var.set(f"已保存 {target_path.name}")
        self._append_lammps_console(f"[脚本] 已保存: {target_path}\n")
        return target_path

    def _open_lammps_script_directory(self) -> None:
        directory = self._current_lammps_script_path().parent
        directory.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["explorer", str(directory)], shell=False)

    def _lammps_input_dir(self) -> Path:
        output_dir = Path(self.lammps_output_dir_var.get().strip() or str(self.workspace_dir)).expanduser()
        output_dir.mkdir(parents=True, exist_ok=True)
        layout = build_lammps_output_layout(output_dir)
        for directory in (layout.process_dir, layout.relaxation.directory, layout.production.directory):
            directory.mkdir(parents=True, exist_ok=True)
        return output_dir

    def _current_lammps_output_layout(self) -> LammpsOutputLayout:
        output_dir = self._lammps_input_dir()
        return build_lammps_output_layout(output_dir)

    def _sync_lammps_output_paths(self) -> None:
        layout = self._current_lammps_output_layout()
        self.lammps_script_var.set(str(layout.process_script_file))
        self.lammps_log_var.set(str(layout.process_log_file))
        self.lammps_output_summary_var.set(
            f"process: {layout.process_script_file} / {layout.process_log_file}\n"
            f"relaxation: {layout.relaxation.data_file} / {layout.relaxation.restart_file} / {layout.relaxation.trajectory_file}\n"
            f"md: {layout.production.data_file} / {layout.production.restart_file} / {layout.production.trajectory_file}"
        )

    def _lammps_output_artifacts(self, config: LammpsInputConfig) -> list[Path]:
        layout = self.input_generator._resolve_output_layout(config)
        return [
            layout.process_script_file,
            layout.process_log_file,
            layout.relaxation.data_file,
            layout.relaxation.restart_file,
            layout.relaxation.trajectory_file,
            layout.production.data_file,
            layout.production.restart_file,
            layout.production.trajectory_file,
        ]

    def _cleanup_lammps_output_artifacts(self, config: LammpsInputConfig) -> None:
        for artifact in self._lammps_output_artifacts(config):
            if artifact == config.input_script:
                continue
            try:
                if artifact.exists():
                    artifact.unlink()
            except Exception:
                pass

    def _gather_lammps_input_config(self) -> LammpsInputConfig:
        scenario = self.lammps_scenario_var.get().strip() or "NVT Relaxation"
        data_file = Path(self.lammps_data_file_var.get().strip()).expanduser()
        if not data_file.exists():
            raise FileNotFoundError(f"找不到 LAMMPS 数据文件: {data_file}")
        output_dir = self._lammps_input_dir()
        potential_text = self.lammps_potential_var.get().strip()
        potential_file = Path(potential_text).expanduser() if potential_text else None
        if potential_file is not None and not potential_file.exists():
            raise FileNotFoundError(f"找不到势函数文件: {potential_file}")
        element_list = [item for item in self.lammps_elements_var.get().replace(",", " ").split() if item]
        if not element_list:
            detected_elements = self._auto_detect_lammps_elements(data_file, update_status=True)
            if detected_elements:
                element_list = detected_elements
        if not element_list:
            raise ValueError("请输入至少一个元素符号")

        timestep = parse_positive_float(self.lammps_timestep_var.get(), "步长")
        temperature = parse_positive_float(self.lammps_temperature_var.get(), "温度")
        final_temperature = parse_optional_float_value(self.lammps_final_temperature_var.get(), "终止温度")
        if final_temperature is not None and final_temperature <= 0:
            raise ValueError("终止温度必须大于 0")
        pressure = parse_optional_float_value(self.lammps_pressure_var.get(), "压力")
        force_field = self.lammps_force_field_var.get().strip() or "lj/cut"
        potential_kind = self.input_generator._potential_kind(potential_file)
        if potential_kind in {"meam", "meam/ms"} and force_field.lower() in {"lj", "lj/cut", "eam", "eam/alloy", "eam/fs", "eam/he", "eam/cd", "eam/cd/old", "meam", "meam/c", "meam/ms"}:
            force_field = potential_kind
        elif potential_kind in {"eam", "eam/alloy", "eam/fs", "eam/he", "eam/cd", "eam/cd/old"} and force_field.lower() in {"lj", "lj/cut", "meam", "meam/c", "meam/ms"}:
            force_field = potential_kind

        if not self.lammps_pair_coeff_override_var.get().strip() and potential_kind in {"eam", "eam/alloy", "eam/fs", "eam/he", "eam/cd", "eam/cd/old", "meam", "meam/ms", "tersoff", "sw", "reax/c"}:
            try:
                structure, _resolved_path = self._structure_for_path(data_file)
            except Exception:
                structure = None
            if structure is not None:
                atom_type_count = structure.atom_types or max((atom.atom_type for atom in structure.atoms), default=0)
                if atom_type_count > 0 and len(element_list) < atom_type_count:
                    raise ValueError(
                        f"当前数据文件包含 {atom_type_count} 个原子类型，但元素序列只有 {len(element_list)} 个。"
                        "对 EAM/MEAM/Tersoff/SW/ReaxFF 这类多体势函数，请补齐元素序列，或在 pair_coeff 覆盖中显式写出 NULL 占位。"
                    )

        return LammpsInputConfig(
            scenario=scenario,
            data_file=data_file,
            output_dir=output_dir,
            timestep=timestep,
            run_steps=parse_positive_int(self.lammps_steps_var.get(), "步数"),
            temperature=temperature,
            final_temperature=final_temperature,
            pressure=pressure,
            relax_steps=parse_positive_int(self.lammps_relax_steps_var.get(), "弛豫步数", default=2000),
            ensemble=self.lammps_ensemble_var.get().strip() or "nvt",
            force_field=force_field,
            potential_file=potential_file,
            element_list=element_list,
            seed=int(time.time()) % 1_000_000,
            log_file=Path(self.lammps_log_var.get().strip() or str(output_dir / "process" / "log.lammps")).expanduser(),
            input_script=Path(self.lammps_script_var.get().strip() or str(output_dir / "process" / "in.relax_md.lammps")).expanduser(),
            extra_commands=self.lammps_extra_var.get().strip(),
            pair_style_override=self.lammps_pair_style_override_var.get().strip(),
            pair_coeff_override=self.lammps_pair_coeff_override_var.get().strip(),
            custom_template=self._get_lammps_template_text(),
            thermo_every=parse_positive_int(self.lammps_thermo_every_var.get(), "热输出间隔", default=100),
            dump_every=parse_positive_int(self.lammps_dump_every_var.get(), "轨迹输出间隔", default=100),
            production_data_file=output_dir / "md" / "production.data",
            trajectory_file=output_dir / "md" / "trajectory.lammpstrj",
            restart_file=output_dir / "md" / "production.restart",
        )

    def _build_lammps_tab(self) -> None:
        self.lammps_scrollable_frame = ScrollableFrame(self.tab_lammps)
        self.lammps_scrollable_frame.pack(fill="both", expand=True)
        root = self.lammps_scrollable_frame.content
        root.columnconfigure(0, weight=1)

        header = ttk.LabelFrame(root, text="LAMMPS 接口模块", style="Section.TLabelframe", padding=16)
        header.pack(fill="x")
        tk.Label(header, text="LAMMPS 工作流", bg=PANEL, fg=ACCENT_DARK, font=("Microsoft YaHei UI", 24, "bold")).pack(anchor="w")
        tk.Label(
            header,
            text="选择运行时、数据文件、势函数和预设场景后即可生成 in.lammps，并在后台调用 conda 运行时或本地 lmp.exe 执行。",
            bg=PANEL,
            fg=MUTED,
            font=("Microsoft YaHei UI", 10),
            wraplength=1120,
            justify="left",
        ).pack(anchor="w", pady=(6, 0))
        header_actions = ttk.Frame(header)
        header_actions.pack(anchor="w", pady=(10, 0))
        ttk.Button(header_actions, text="打开教程与帮助", command=lambda: self.notebook.select(self.tab_about)).pack(side="left")
        ttk.Button(header_actions, text="进入工作台", command=lambda: self.notebook.select(self.tab_home)).pack(side="left", padx=(8, 0))

        runtime_card = ttk.LabelFrame(root, text="运行时配置", style="Section.TLabelframe", padding=14)
        runtime_card.pack(fill="x", pady=(12, 0))
        runtime_card.columnconfigure(1, weight=1)
        ttk.Label(runtime_card, text="LAMMPS 环境/程序").grid(row=0, column=0, sticky="w")
        ttk.Entry(runtime_card, textvariable=self.lammps_path_var).grid(row=0, column=1, sticky="ew", padx=(8, 8))
        ttk.Button(runtime_card, text="浏览目录", command=self._browse_lammps_directory).grid(row=0, column=2, sticky="w")
        ttk.Button(runtime_card, text="浏览程序", command=self._browse_lammps).grid(row=0, column=3, sticky="w", padx=(8, 0))
        ttk.Button(runtime_card, text="重新检测", command=self._refresh_lammps_runtime_info).grid(row=0, column=4, sticky="w", padx=(8, 0))
        ttk.Label(runtime_card, text="并行核数").grid(row=1, column=0, sticky="w", pady=(10, 0))
        ttk.Spinbox(runtime_card, from_=1, to=max(1, os.cpu_count() or 1), textvariable=self.lammps_core_count_var, width=10).grid(row=1, column=1, sticky="w", padx=(8, 8), pady=(10, 0))
        self.lammps_gpu_checkbox = ttk.Checkbutton(runtime_card, text="GPU 加速", variable=self.lammps_gpu_var)
        self.lammps_gpu_checkbox.grid(row=1, column=2, columnspan=2, sticky="w", pady=(10, 0))
        ttk.Label(runtime_card, textvariable=self.lammps_runtime_summary_var, foreground=MUTED, wraplength=1120, justify="left").grid(row=2, column=0, columnspan=5, sticky="w", pady=(10, 0))

        input_card = ttk.LabelFrame(root, text="输入生成", style="Section.TLabelframe", padding=14)
        input_card.pack(fill="x", pady=(12, 0))
        for column in range(8):
            input_card.columnconfigure(column, weight=1 if column in {1, 3, 5, 7} else 0)

        ttk.Label(input_card, text="场景").grid(row=0, column=0, sticky="w")
        self.lammps_scenario_combo = ttk.Combobox(
            input_card,
            textvariable=self.lammps_scenario_var,
            values=self._lammps_scenario_options(),
            state="readonly",
            width=22,
        )
        self.lammps_scenario_combo.grid(row=0, column=1, sticky="ew", padx=(8, 12))
        self.lammps_scenario_combo.bind("<<ComboboxSelected>>", lambda _event: self._apply_lammps_scenario())
        ttk.Button(input_card, text="套用场景", command=self._apply_lammps_scenario).grid(row=0, column=2, sticky="w")
        ttk.Button(input_card, text="同步当前模型", command=self._sync_lammps_source_from_model).grid(row=0, column=3, sticky="w", padx=(12, 0))
        ttk.Button(input_card, text="修改工作目录", command=self._open_workspace_settings).grid(row=0, column=4, sticky="w", padx=(12, 0))

        ttk.Label(input_card, text="数据文件").grid(row=1, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(input_card, textvariable=self.lammps_data_file_var).grid(row=1, column=1, columnspan=3, sticky="ew", padx=(8, 8), pady=(10, 0))
        ttk.Button(input_card, text="浏览", command=lambda: self._select_lammps_data_file()).grid(row=1, column=4, sticky="w", pady=(10, 0))
        ttk.Button(input_card, text="导出 data", command=self._export_current_model_data_file).grid(row=1, column=5, sticky="w", padx=(8, 0), pady=(10, 0))

        ttk.Label(input_card, text="输入脚本").grid(row=2, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(input_card, textvariable=self.lammps_script_var).grid(row=2, column=1, columnspan=2, sticky="ew", padx=(8, 8), pady=(10, 0))
        ttk.Label(input_card, text="日志").grid(row=2, column=3, sticky="w", padx=(12, 0), pady=(10, 0))
        ttk.Entry(input_card, textvariable=self.lammps_log_var).grid(row=2, column=4, columnspan=2, sticky="ew", padx=(8, 0), pady=(10, 0))

        ttk.Label(input_card, text="步长").grid(row=3, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(input_card, textvariable=self.lammps_timestep_var, width=12).grid(row=3, column=1, sticky="ew", padx=(8, 12), pady=(10, 0))
        ttk.Label(input_card, text="弛豫步数").grid(row=3, column=2, sticky="w", pady=(10, 0))
        ttk.Entry(input_card, textvariable=self.lammps_relax_steps_var, width=12).grid(row=3, column=3, sticky="ew", padx=(8, 12), pady=(10, 0))
        ttk.Label(input_card, text="步数").grid(row=3, column=4, sticky="w", pady=(10, 0))
        ttk.Entry(input_card, textvariable=self.lammps_steps_var, width=12).grid(row=3, column=5, sticky="ew", padx=(8, 12), pady=(10, 0))
        ttk.Label(input_card, text="温度(K)").grid(row=3, column=6, sticky="w", pady=(10, 0))
        ttk.Entry(input_card, textvariable=self.lammps_temperature_var, width=12).grid(row=3, column=7, sticky="ew", padx=(8, 0), pady=(10, 0))

        ttk.Label(input_card, text="终止温度(K)").grid(row=4, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(input_card, textvariable=self.lammps_final_temperature_var, width=12).grid(row=4, column=1, sticky="ew", padx=(8, 12), pady=(10, 0))
        ttk.Label(input_card, text="压力").grid(row=4, column=2, sticky="w", pady=(10, 0))
        ttk.Entry(input_card, textvariable=self.lammps_pressure_var, width=12).grid(row=4, column=3, sticky="ew", padx=(8, 12), pady=(10, 0))
        ttk.Label(input_card, text="热输出间隔").grid(row=4, column=4, sticky="w", pady=(10, 0))
        ttk.Entry(input_card, textvariable=self.lammps_thermo_every_var, width=12).grid(row=4, column=5, sticky="ew", padx=(8, 12), pady=(10, 0))
        ttk.Label(input_card, text="轨迹输出间隔").grid(row=4, column=6, sticky="w", pady=(10, 0))
        ttk.Entry(input_card, textvariable=self.lammps_dump_every_var, width=12).grid(row=4, column=7, sticky="ew", padx=(8, 0), pady=(10, 0))

        ttk.Label(input_card, text="系综").grid(row=5, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(input_card, textvariable=self.lammps_ensemble_var).grid(row=5, column=1, sticky="ew", padx=(8, 12), pady=(10, 0))
        ttk.Label(input_card, text="力场").grid(row=5, column=2, sticky="w", pady=(10, 0))
        ttk.Combobox(
            input_card,
            textvariable=self.lammps_force_field_var,
            values=self._lammps_force_field_options(),
            state="normal",
        ).grid(row=5, column=3, sticky="ew", padx=(8, 12), pady=(10, 0))
        ttk.Label(input_card, text="势函数文件").grid(row=5, column=4, sticky="w", pady=(10, 0))
        ttk.Entry(input_card, textvariable=self.lammps_potential_var).grid(row=5, column=5, columnspan=2, sticky="ew", padx=(8, 8), pady=(10, 0))
        ttk.Button(input_card, text="浏览", command=self._select_lammps_potential_file).grid(row=5, column=7, sticky="w", padx=(8, 0), pady=(10, 0))

        ttk.Label(input_card, text="元素序列").grid(row=6, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(input_card, textvariable=self.lammps_elements_var).grid(row=6, column=1, columnspan=2, sticky="ew", padx=(8, 12), pady=(10, 0))
        ttk.Label(input_card, text="自动识别").grid(row=6, column=3, sticky="w", pady=(10, 0))
        ttk.Label(input_card, textvariable=self.lammps_type_summary_var, foreground=MUTED).grid(row=6, column=4, columnspan=3, sticky="w", padx=(8, 0), pady=(10, 0))

        ttk.Label(input_card, text="附加命令").grid(row=7, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(input_card, textvariable=self.lammps_extra_var).grid(row=7, column=1, columnspan=6, sticky="ew", padx=(8, 0), pady=(10, 0))

        action_row = ttk.Frame(input_card)
        action_row.grid(row=8, column=0, columnspan=7, sticky="ew", pady=(14, 0))
        ttk.Button(action_row, text="生成输入", style="Accent.TButton", command=self._generate_lammps_input).pack(side="left")
        ttk.Button(action_row, text="开始运行", command=self._start_lammps_run).pack(side="left", padx=(8, 0))
        ttk.Button(action_row, text="停止运行", command=self._stop_lammps_run).pack(side="left", padx=(8, 0))
        ttk.Button(action_row, text="打开工作目录", command=self._open_workspace_dir).pack(side="left", padx=(8, 0))
        ttk.Label(action_row, textvariable=self.lammps_status_var, foreground=TEXT).pack(side="right")

        output_card = ttk.LabelFrame(root, text="输出组织", style="Section.TLabelframe", padding=14)
        output_card.pack(fill="x", pady=(12, 0))
        output_card.columnconfigure(1, weight=1)
        ttk.Label(output_card, text="输出根目录").grid(row=0, column=0, sticky="w")
        ttk.Entry(output_card, textvariable=self.lammps_output_dir_var).grid(row=0, column=1, sticky="ew", padx=(8, 8))
        ttk.Button(output_card, text="同步默认路径", command=self._sync_lammps_output_paths).grid(row=0, column=2, sticky="w")
        ttk.Button(output_card, text="打开输出目录", command=self._open_lammps_output_directory).grid(row=0, column=3, sticky="w", padx=(8, 0))
        ttk.Button(output_card, text="接续弛豫数据", command=lambda: self._adopt_lammps_output_as_source(self._current_lammps_output_layout().relaxation.data_file)).grid(row=0, column=4, sticky="w", padx=(8, 0))
        ttk.Button(output_card, text="接续 MD 数据", command=lambda: self._adopt_lammps_output_as_source(self._current_lammps_output_layout().production.data_file)).grid(row=0, column=5, sticky="w", padx=(8, 0))
        tk.Label(
            output_card,
            textvariable=self.lammps_output_summary_var,
            bg=PANEL,
            fg=MUTED,
            justify="left",
            anchor="w",
            font=("Microsoft YaHei UI", 9),
        ).grid(row=1, column=0, columnspan=6, sticky="ew", pady=(10, 0))

        advanced_card = ttk.LabelFrame(root, text="高级覆盖与模板", style="Section.TLabelframe", padding=14)
        advanced_card.pack(fill="both", pady=(12, 0))
        for column in range(6):
            advanced_card.columnconfigure(column, weight=1 if column in {1, 4} else 0)
        advanced_card.rowconfigure(2, weight=1)

        ttk.Label(advanced_card, text="力场覆盖").grid(row=0, column=0, sticky="w")
        ttk.Entry(advanced_card, textvariable=self.lammps_pair_style_override_var).grid(row=0, column=1, columnspan=2, sticky="ew", padx=(8, 12))
        ttk.Label(advanced_card, text="pair_coeff 覆盖").grid(row=0, column=3, sticky="w")
        ttk.Entry(advanced_card, textvariable=self.lammps_pair_coeff_override_var).grid(row=0, column=4, columnspan=2, sticky="ew", padx=(8, 0))

        ttk.Label(advanced_card, text="自定义模板").grid(row=1, column=0, sticky="w", pady=(12, 0))
        template_buttons = ttk.Frame(advanced_card)
        template_buttons.grid(row=1, column=1, columnspan=5, sticky="e", pady=(12, 0))
        ttk.Button(template_buttons, text="恢复默认模板", command=self._restore_lammps_template).pack(side="left")
        ttk.Button(template_buttons, text="清空模板", command=lambda: self._set_lammps_template_text("")).pack(side="left", padx=(8, 0))
        self.lammps_custom_template_text = scrolledtext.ScrolledText(
            advanced_card,
            height=11,
            wrap="word",
            bg="#ffffff",
            fg=TEXT,
            insertbackground=TEXT,
            font=("Consolas", 9),
        )
        self.lammps_custom_template_text.grid(row=2, column=0, columnspan=6, sticky="nsew", pady=(10, 0))
        self._restore_lammps_template()
        tk.Label(
            advanced_card,
            text="可用占位符：$data_file、$output_dir、$process_dir、$process_script_file、$process_log_file、$relaxation_dir、$relaxation_data_file、$relaxation_trajectory_file、$relaxation_restart_file、$production_dir、$production_data_file、$production_trajectory_file、$production_restart_file、$timestep、$temperature、$final_temperature、$pressure、$pair_section、$scenario_section、$extra_commands、$pair_style、$pair_coeff、$pair_style_override、$pair_coeff_override、$potential_file、$elements、$seed、$thermo_every、$dump_every。自定义场景默认把附加命令放入 scenario_section；标准场景会自动写出 relaxation/relaxed.data 和 md/production.data。",
            bg=PANEL,
            fg=MUTED,
            justify="left",
            wraplength=1180,
            font=("Microsoft YaHei UI", 9),
        ).grid(row=3, column=0, columnspan=6, sticky="w", pady=(10, 0))

        script_card = ttk.LabelFrame(root, text="输入脚本预览与编辑", style="Section.TLabelframe", padding=14)
        script_card.pack(fill="both", pady=(12, 0))
        script_card.columnconfigure(0, weight=1)
        script_card.rowconfigure(2, weight=1)

        script_toolbar = ttk.Frame(script_card)
        script_toolbar.grid(row=0, column=0, sticky="ew")
        ttk.Button(script_toolbar, text="生成并预览", style="Accent.TButton", command=self._generate_lammps_input).pack(side="left")
        ttk.Button(script_toolbar, text="从磁盘载入", command=self._load_lammps_script_from_disk).pack(side="left", padx=(8, 0))
        ttk.Button(script_toolbar, text="保存脚本", command=self._save_lammps_script_from_editor).pack(side="left", padx=(8, 0))
        ttk.Button(script_toolbar, text="保存并运行", style="Accent.TButton", command=self._start_lammps_run).pack(side="left", padx=(8, 0))
        ttk.Button(script_toolbar, text="打开脚本目录", command=self._open_lammps_script_directory).pack(side="left", padx=(8, 0))
        tk.Label(
            script_card,
            textvariable=self.lammps_script_preview_var,
            bg=PANEL,
            fg=MUTED,
            justify="left",
            anchor="w",
            wraplength=1180,
            font=("Microsoft YaHei UI", 9),
        ).grid(row=1, column=0, sticky="ew", pady=(10, 0))

        editor_frame = ttk.Frame(script_card)
        editor_frame.grid(row=2, column=0, sticky="nsew", pady=(10, 0))
        editor_frame.rowconfigure(0, weight=1)
        editor_frame.columnconfigure(0, weight=1)
        self.lammps_script_preview_text = tk.Text(
            editor_frame,
            height=14,
            wrap="none",
            bg="#ffffff",
            fg=TEXT,
            insertbackground=TEXT,
            font=("Consolas", 9),
            undo=True,
            autoseparators=True,
            maxundo=-1,
        )
        script_vscroll = ttk.Scrollbar(editor_frame, orient="vertical", command=self.lammps_script_preview_text.yview)
        script_hscroll = ttk.Scrollbar(editor_frame, orient="horizontal", command=self.lammps_script_preview_text.xview)
        self.lammps_script_preview_text.configure(yscrollcommand=script_vscroll.set, xscrollcommand=script_hscroll.set)
        self.lammps_script_preview_text.grid(row=0, column=0, sticky="nsew")
        script_vscroll.grid(row=0, column=1, sticky="ns")
        script_hscroll.grid(row=1, column=0, sticky="ew")

        lower = ttk.Frame(root)
        lower.pack(fill="both", expand=True, pady=(12, 0))
        lower.columnconfigure(0, weight=1)
        lower.columnconfigure(1, weight=1)

        run_card = ttk.LabelFrame(lower, text="运行控制", style="Section.TLabelframe", padding=14)
        run_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        run_card.rowconfigure(2, weight=1)
        ttk.Progressbar(run_card, mode="indeterminate").grid(row=0, column=0, sticky="ew")
        self.lammps_progress = run_card.grid_slaves(row=0, column=0)[0]
        self.lammps_progress.grid_configure(pady=(0, 10))
        tk.Label(run_card, text="控制台输出", bg=PANEL, fg=TEXT, font=("Microsoft YaHei UI", 10, "bold")).grid(row=1, column=0, sticky="w")
        self.lammps_console = scrolledtext.ScrolledText(run_card, height=18, wrap="word", bg="#ffffff", fg=TEXT, insertbackground=TEXT, font=("Consolas", 9))
        self.lammps_console.grid(row=2, column=0, sticky="nsew", pady=(8, 0))
        self.lammps_console.configure(state="disabled")

        result_card = ttk.LabelFrame(lower, text="结果查看", style="Section.TLabelframe", padding=14)
        result_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        result_card.rowconfigure(1, weight=1)
        self.lammps_result_var = tk.StringVar(value="等待运行结果")
        tk.Label(result_card, textvariable=self.lammps_result_var, bg=PANEL, fg=MUTED, justify="left", wraplength=600, font=("Microsoft YaHei UI", 10)).grid(row=0, column=0, sticky="w")
        self.lammps_figure = Figure(figsize=(6.0, 4.8), dpi=100)
        self.lammps_canvas = FigureCanvasTkAgg(self.lammps_figure, master=result_card)
        self.lammps_canvas_widget = self.lammps_canvas.get_tk_widget()
        self.lammps_canvas_widget.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        self._update_lammps_plot([])
        self._apply_lammps_scenario(self.lammps_scenario_var.get())
        self._auto_detect_lammps_elements(Path(self.lammps_data_file_var.get().strip() or self.source_path_var.get()), update_status=False)
        self._sync_lammps_output_paths()
        self._refresh_lammps_script_preview()
        self.lammps_output_dir_var.trace_add("write", lambda *_args: self._sync_lammps_output_paths())

    def _select_lammps_data_file(self) -> None:
        selected = filedialog.askopenfilename(
            title="选择 LAMMPS 数据文件",
            initialdir=str(self.workspace_dir),
            filetypes=[("LAMMPS data", "*.data *.dat *.lmp"), ("All files", "*.*")],
        )
        if selected:
            selected_path = Path(selected).expanduser()
            self.lammps_data_file_var.set(selected)
            self._auto_detect_lammps_elements(selected_path, update_status=True)

    def _select_lammps_potential_file(self) -> None:
        selected = filedialog.askopenfilename(
            title="选择势函数文件",
            initialdir=str(self.workspace_dir),
            filetypes=[("Potential files", "*.*"), ("All files", "*.*")],
        )
        if selected:
            selected_path = Path(selected).expanduser()
            self.lammps_potential_var.set(selected)
            potential_kind = self.input_generator._potential_kind(selected_path)
            if potential_kind:
                self.lammps_force_field_var.set(potential_kind)
                self.lammps_status_var.set(f"已选择 {selected_path.name}，自动切换到 {potential_kind}")
            else:
                self.lammps_status_var.set(f"已选择 {selected_path.name}")

    def _append_lammps_console(self, text: str) -> None:
        if not hasattr(self, "lammps_console"):
            return
        self.lammps_console.configure(state="normal")
        self.lammps_console.insert("end", text)
        self.lammps_console.see("end")
        self.lammps_console.configure(state="disabled")

    def _generate_lammps_input(self) -> None:
        try:
            config = self._gather_lammps_input_config()
            script_text = self.input_generator.build_script(config)
            config.input_script.parent.mkdir(parents=True, exist_ok=True)
            config.input_script.write_text(script_text, encoding="utf-8")
            self._set_lammps_script_text(script_text)
            self.lammps_script_preview_var.set(f"脚本已生成: {config.input_script}")
        except Exception as exc:
            messagebox.showerror("LAMMPS 输入生成失败", str(exc))
            self.lammps_status_var.set("输入生成失败")
            return
        self.lammps_status_var.set(f"已生成 {config.input_script.name}")
        self._append_lammps_console(f"[输入] 已生成 {config.input_script}\n")

    def _start_lammps_run(self) -> None:
        try:
            config = self._gather_lammps_input_config()
            script_text = self._get_lammps_script_text().strip()
            if script_text:
                script_text = self._get_lammps_script_text()
            else:
                script_text = self.input_generator.build_script(config)
                self._set_lammps_script_text(script_text)
            if not script_text.endswith("\n"):
                script_text += "\n"
            config.input_script.parent.mkdir(parents=True, exist_ok=True)
            config.input_script.write_text(script_text, encoding="utf-8")
            self.lammps_script_preview_var.set(f"脚本已保存: {config.input_script}")
            self._append_lammps_console(f"[脚本] 已保存: {config.input_script}\n")
            self._cleanup_lammps_output_artifacts(config)
            executable = self._current_lammps_executable()
            self.lammps_executable = executable
            self.lammps_path_var.set(str(executable))
            self._refresh_lammps_runtime_info()
            command, env, mode_label = self._build_lammps_launch_plan(executable, config)
            self.lammps_manager.start(command, config.output_dir, config.log_file, env=env)
            self._current_lammps_run_config = config
            self._save_app_settings()
        except Exception as exc:
            messagebox.showerror("LAMMPS 运行失败", str(exc))
            self.lammps_status_var.set("运行失败")
            return
        self.lammps_status_var.set(f"LAMMPS 正在运行（{mode_label}）")
        self._set_banner_status(f"LAMMPS 运行中 ({mode_label})", WARNING)
        self._last_thermo_points = []
        self._update_lammps_plot([])
        self._append_lammps_console(f"[启动] {mode_label}: {subprocess.list2cmdline(command)}\n")
        self.lammps_progress.start(10)
        self._poll_lammps_job = self.after(150, self._poll_lammps_output)

    def _stop_lammps_run(self) -> None:
        self.lammps_manager.terminate()
        self.lammps_status_var.set("已请求停止")
        self._append_lammps_console("[系统] 已请求停止运行\n")

    def _poll_lammps_output(self) -> None:
        lines = self.lammps_manager.poll_output()
        if lines:
            self._append_lammps_console("".join(lines))
        if self.lammps_manager.is_running():
            self._poll_lammps_job = self.after(200, self._poll_lammps_output)
            return
        self.lammps_progress.stop()
        return_code = self.lammps_manager.poll_returncode()
        if return_code is None:
            self._poll_lammps_job = None
            return
        self._poll_lammps_job = None
        log_path = Path(self.lammps_log_var.get().strip() or str(self._lammps_input_dir() / "process" / "log.lammps")).expanduser()
        points = parse_lammps_log(log_path)
        issues = scan_lammps_log_issues(log_path)
        self._last_thermo_points = points
        self._update_lammps_plot(points)
        if issues:
            issue_text = "；".join(issues)
            self._append_lammps_console(f"[诊断] {issue_text}\n")
            current_summary = self.lammps_result_var.get()
            self.lammps_result_var.set(f"{current_summary}\n诊断: {issue_text}" if current_summary else f"诊断: {issue_text}")
        if return_code == 0:
            self.lammps_status_var.set("LAMMPS 运行完成（有诊断提示）" if issues else "LAMMPS 运行完成")
            self._set_banner_status("就绪", SUCCESS)
            self._append_lammps_console(f"[完成] 运行结束，解析到 {len(points)} 组热力学数据\n")
            if self._current_lammps_run_config is not None:
                layout = self.input_generator._resolve_output_layout(self._current_lammps_run_config)
                artifact_paths = self._lammps_output_artifacts(self._current_lammps_run_config)
                existing_artifacts = [artifact for artifact in artifact_paths if artifact.exists()]
                if existing_artifacts:
                    artifact_text = "；".join(str(artifact) for artifact in existing_artifacts)
                    self._append_lammps_console(f"[输出] 已生成: {artifact_text}\n")
                    current_summary = self.lammps_result_var.get()
                    suffix = f"\n输出文件: {artifact_text}"
                    self.lammps_result_var.set(f"{current_summary}{suffix}" if current_summary else f"输出文件: {artifact_text}")
                next_source = layout.production.data_file if layout.production.data_file.exists() else layout.relaxation.data_file
                if next_source.exists():
                    self.source_path_var.set(str(next_source))
                    self.lammps_data_file_var.set(str(next_source))
                    self._load_source_info()
        else:
            self.lammps_status_var.set(f"LAMMPS 退出码 {return_code}（有诊断提示）" if issues else f"LAMMPS 退出码 {return_code}")
            self._set_banner_status("运行失败", DANGER)
            self._append_lammps_console(f"[错误] LAMMPS 退出码 {return_code}\n")

    def _update_lammps_plot(self, points: list[LammpsThermoPoint]) -> None:
        self.lammps_figure.clear()
        if not points:
            ax = self.lammps_figure.add_subplot(111)
            ax.set_title("热力学结果")
            ax.text(0.5, 0.5, "等待 log.lammps", ha="center", va="center", transform=ax.transAxes, color=MUTED)
            ax.set_axis_off()
            self.lammps_canvas.draw_idle()
            self.lammps_result_var.set("尚未解析到热力学结果；完成一次运行后会自动绘图。")
            return

        temperature_points = [(point.step, point.temperature) for point in points if point.temperature is not None]
        energy_points = [(point.step, point.total_energy) for point in points if point.total_energy is not None]

        ax_temp = self.lammps_figure.add_subplot(211)
        if temperature_points:
            ax_temp.plot([step for step, _value in temperature_points], [value for _step, value in temperature_points], color=ACCENT_DARK, linewidth=1.6)
        ax_temp.set_ylabel("Temp (K)")
        ax_temp.grid(True, alpha=0.25)

        ax_energy = self.lammps_figure.add_subplot(212, sharex=ax_temp)
        if energy_points:
            ax_energy.plot([step for step, _value in energy_points], [value for _step, value in energy_points], color="#287f5a", linewidth=1.6)
        ax_energy.set_xlabel("Step")
        ax_energy.set_ylabel("Etot")
        ax_energy.grid(True, alpha=0.25)

        self.lammps_figure.tight_layout()
        self.lammps_canvas.draw_idle()
        self.lammps_result_var.set(
            f"已解析 {len(points)} 组热力学数据。最后一步: {points[-1].step}；最后温度: {temperature_points[-1][1] if temperature_points else 'N/A'}；最后总能量: {energy_points[-1][1] if energy_points else 'N/A'}。"
        )

    def _export_current_model_data_file(self) -> None:
        target_path = filedialog.asksaveasfilename(
            title="导出 LAMMPS data 文件",
            initialdir=str(self.workspace_dir),
            defaultextension=".data",
            filetypes=[("LAMMPS data", "*.data"), ("All files", "*.*")],
        )
        if not target_path:
            return
        output_path = Path(target_path)
        try:
            mode = self.modeling_mode_var.get()
            if mode == "nanopowder":
                config = self._nanopowder_config()
                structure, _particles, _box = build_nanopowder_structure(config)
                self.data_writer.write(output_path, structure, structure.atoms, atom_types_count=structure.atom_types or 1)
            elif mode == "single":
                config = self._single_crystal_config()
                structure, _summary, _box = build_single_crystal_structure(config)
                self.data_writer.write(output_path, structure, structure.atoms, atom_types_count=structure.atom_types or 1)
            else:
                source_path = Path(self.source_path_var.get().strip())
                if not source_path.exists():
                    raise FileNotFoundError(f"找不到当前模型源文件: {source_path}")
                structure, _resolved_path = self._structure_for_path(source_path)
                self.data_writer.write(output_path, structure, structure.atoms, atom_types_count=structure.atom_types or 1)
            self.lammps_status_var.set(f"已导出 {output_path.name}")
            self._append_lammps_console(f"[导出] {output_path}\n")
        except Exception as exc:
            messagebox.showerror("导出 data 失败", str(exc))

    def _show_splash_screen(self) -> tk.Toplevel:
        splash = tk.Toplevel(self)
        splash.title(f"DDOJY v{APP_VERSION}")
        splash.configure(bg=HEADER_BG)
        splash.overrideredirect(True)
        splash.geometry("460x238")
        splash.update_idletasks()
        screen_x = splash.winfo_screenwidth()
        screen_y = splash.winfo_screenheight()
        x = (screen_x - 460) // 2
        y = (screen_y - 238) // 2
        splash.geometry(f"460x238+{x}+{y}")
        frame = tk.Frame(splash, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        frame.pack(fill="both", expand=True)
        tk.Frame(frame, bg=ACCENT, height=5).pack(fill="x")
        body = tk.Frame(frame, bg=PANEL)
        body.pack(fill="both", expand=True, padx=28, pady=24)
        tk.Label(body, text=f"DDOJY v{APP_VERSION}", bg=PANEL, fg=ACCENT_DARK, font=("Microsoft YaHei UI", 26, "bold")).pack(anchor="center", pady=(10, 6))
        tk.Label(body, text="高/中熵合金建模与 LAMMPS 模拟平台", bg=PANEL, fg=TEXT, font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="center")
        tk.Label(body, text=f"工作目录: {self._app_settings.workspace_dir}", bg=PANEL, fg=MUTED, font=("Microsoft YaHei UI", 9), wraplength=390, justify="center").pack(anchor="center", pady=(16, 0))
        tk.Label(body, text="正在初始化工作台...", bg=PANEL, fg=ACCENT_DARK, font=("Microsoft YaHei UI", 9, "bold")).pack(anchor="center", pady=(10, 0))
        splash.update_idletasks()
        splash.update()
        return splash

    def _setup_style(self) -> None:
        self._style.configure("TFrame", background=BACKGROUND)
        self._style.configure("App.TFrame", background=BACKGROUND)
        self._style.configure("Card.TFrame", background=PANEL)
        self._style.configure("App.TLabel", background=BACKGROUND, foreground=TEXT, font=("Microsoft YaHei UI", 10))
        self._style.configure("Title.TLabel", background=BACKGROUND, foreground=TEXT, font=("Microsoft YaHei UI", 16, "bold"))
        self._style.configure("Section.TLabelframe", background=PANEL, foreground=TEXT, borderwidth=1, relief="solid")
        self._style.configure("Section.TLabelframe.Label", background=PANEL, foreground=ACCENT_DARK, font=("Microsoft YaHei UI", 10, "bold"))
        self._style.configure("TNotebook", background=BACKGROUND, borderwidth=0, tabmargins=(4, 6, 4, 0))
        self._style.configure("Workspace.TNotebook", background=BACKGROUND, borderwidth=0, tabmargins=(0, 0, 0, 0))
        try:
            self._style.layout("Workspace.TNotebook.Tab", [])
        except tk.TclError:
            pass
        self._style.configure(
            "TNotebook.Tab",
            padding=(16, 10),
            font=("Microsoft YaHei UI", 10, "bold"),
            background="#e9eef4",
            foreground=TEXT,
        )
        self._style.map(
            "TNotebook.Tab",
            background=[("selected", PANEL), ("active", "#f6f8fb")],
            foreground=[("selected", ACCENT_DARK), ("active", TEXT)],
        )
        self._style.configure("Accent.TButton", font=("Microsoft YaHei UI", 10, "bold"), padding=(12, 8))
        self._style.map(
            "Accent.TButton",
            background=[("active", ACCENT_DARK), ("!disabled", ACCENT)],
            foreground=[("active", "white"), ("!disabled", "white")],
        )
        self._style.configure("TButton", padding=(10, 7), background="#eef2f6", foreground=TEXT)
        self._style.map("TButton", background=[("active", "#e2e8f0")], foreground=[("disabled", MUTED), ("active", TEXT)])
        self._style.configure("TEntry", fieldbackground=PANEL, foreground=TEXT, bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER, padding=(6, 5))
        self._style.configure("TCombobox", fieldbackground=PANEL, foreground=TEXT, bordercolor=BORDER, padding=(6, 5))
        self._style.configure("TCheckbutton", background=BACKGROUND, foreground=TEXT, font=("Microsoft YaHei UI", 10))
        self._style.configure("TRadiobutton", background=BACKGROUND, foreground=TEXT, font=("Microsoft YaHei UI", 10))
        self._style.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor="#e7edf3", bordercolor=BORDER, lightcolor=ACCENT, darkcolor=ACCENT)
        self._style.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=TEXT, rowheight=30, font=("Microsoft YaHei UI", 9), bordercolor=BORDER)
        self._style.configure("Treeview.Heading", background=PANEL_ALT, foreground=TEXT, font=("Microsoft YaHei UI", 9, "bold"))

    def _add_tooltip(self, widget: tk.Widget, text: str, *, delay: int = 350, wraplength: int = 320) -> None:
        self._tooltips.append(HoverTooltip(widget, text, delay=delay, wraplength=wraplength))

    def _build_sidebar(self) -> None:
        self._nav_items: list[tuple[ttk.Frame, tk.Label]] = []
        self._nav_hover: str | None = None

        header = tk.Frame(self.sidebar, bg=SIDEBAR_BG)
        header.pack(fill="x", padx=14, pady=(16, 12))
        tk.Label(header, text="DDOJY", bg=SIDEBAR_BG, fg="white", font=("Microsoft YaHei UI", 20, "bold")).pack(anchor="w")
        tk.Label(header, text="Workflow Console", bg=SIDEBAR_BG, fg=SIDEBAR_MUTED, font=("Microsoft YaHei UI", 9, "bold")).pack(anchor="w", pady=(2, 0))

        nav_items = [
            (self.tab_home, "工作台", "Overview"),
            (self.tab_recipe, "配方设计", "Composition"),
            (self.tab_doping, "掺杂设计", "Doping"),
            (self.tab_geometry, "梯度晶粒", "Gradient"),
            (self.tab_modeling, "单晶/多晶", "Structure"),
            (self.tab_crack, "裂纹处理", "Crack"),
            (self.tab_output, "梯度输出", "Output"),
            (self.tab_lammps, "LAMMPS", "Simulation"),
            (self.tab_about, "教程帮助", "Docs"),
        ]
        for index, (tab, title, subtitle) in enumerate(nav_items):
            item = tk.Label(
                self.sidebar,
                text=f"{index}  {title}\n   {subtitle}",
                bg=SIDEBAR_BG,
                fg=SIDEBAR_TEXT,
                activebackground=SIDEBAR_HOVER,
                activeforeground="white",
                font=("Microsoft YaHei UI", 10, "bold"),
                justify="left",
                anchor="w",
                padx=14,
                pady=8,
                cursor="hand2",
            )
            item.pack(fill="x", padx=10, pady=(0, 4))
            item.bind("<Button-1>", lambda _event, target=tab: self._select_workspace_tab(target))
            item.bind("<Enter>", lambda _event, target=tab: self._set_nav_hover(target, True))
            item.bind("<Leave>", lambda _event, target=tab: self._set_nav_hover(target, False))
            self._nav_items.append((tab, item))

        footer = tk.Frame(self.sidebar, bg=SIDEBAR_BG)
        footer.pack(side="bottom", fill="x", padx=14, pady=14)
        tk.Label(footer, text=f"v{APP_VERSION}", bg=SIDEBAR_BG, fg=SIDEBAR_MUTED, font=("Microsoft YaHei UI", 9, "bold")).pack(anchor="w")
        tk.Label(footer, text="Verified release build", bg=SIDEBAR_BG, fg=SIDEBAR_MUTED, font=("Microsoft YaHei UI", 8)).pack(anchor="w", pady=(2, 0))

    def _select_workspace_tab(self, tab: ttk.Frame) -> None:
        self.notebook.select(tab)
        self._update_navigation()

    def _set_nav_hover(self, tab: ttk.Frame, hovering: bool) -> None:
        current_tab = str(tab)
        self._nav_hover = current_tab if hovering else None
        self._update_navigation()

    def _update_navigation(self, _event: tk.Event | None = None) -> None:
        if not hasattr(self, "_nav_items"):
            return
        selected = self.notebook.select() if hasattr(self, "notebook") else ""
        for tab, item in self._nav_items:
            tab_id = str(tab)
            is_selected = selected == tab_id
            is_hover = self._nav_hover == tab_id
            if is_selected:
                item.configure(bg=SIDEBAR_ACTIVE, fg="white")
            elif is_hover:
                item.configure(bg=SIDEBAR_HOVER, fg="white")
            else:
                item.configure(bg=SIDEBAR_BG, fg=SIDEBAR_TEXT)

    def _set_banner_status(self, text: str, color: str = TEXT) -> None:
        header_color = "#e5efff" if color == TEXT else color
        self.banner_status.configure(text=text, fg=header_color)
        if hasattr(self, "footer_status"):
            self.footer_status.configure(text=f"状态: {text}", fg=color if color != TEXT else TEXT)

    def _build_ui(self) -> None:
        banner = tk.Frame(self, bg=HEADER_BG, height=96)
        banner.pack(fill="x", side="top")
        banner.pack_propagate(False)
        tk.Frame(banner, bg=ACCENT, height=4).pack(fill="x", side="bottom")
        left = tk.Frame(banner, bg=HEADER_BG)
        left.pack(side="left", padx=28, pady=15)
        tk.Label(left, text=APP_TITLE, bg=HEADER_BG, fg="white", font=("Microsoft YaHei UI", 18, "bold")).pack(anchor="w")
        tk.Label(
            left,
            text="Composition | Doping | Polycrystal | LAMMPS workflow",
            bg=HEADER_BG,
            fg="#cbd5e1",
            font=("Microsoft YaHei UI", 10),
        ).pack(anchor="w", pady=(4, 0))
        right = tk.Frame(banner, bg=HEADER_BG)
        right.pack(side="right", padx=28, pady=18)
        tk.Label(right, text=f"版本 {APP_VERSION}", bg=HEADER_SUBTLE, fg="#e5edf5", font=("Microsoft YaHei UI", 9, "bold"), padx=12, pady=4).pack(anchor="e")
        self.banner_status = tk.Label(right, text="就绪", bg=HEADER_BG, fg="#d9f1ef", font=("Microsoft YaHei UI", 10, "bold"))
        self.banner_status.pack(anchor="e", pady=(8, 0))

        status_bar = tk.Frame(self, bg=PANEL, height=30, highlightbackground=BORDER, highlightthickness=1)
        status_bar.pack(fill="x", side="bottom")
        status_bar.pack_propagate(False)
        self.footer_status = tk.Label(status_bar, text="状态: 就绪", bg=PANEL, fg=TEXT, font=("Microsoft YaHei UI", 9, "bold"))
        self.footer_status.pack(side="left", padx=14)
        self.footer_workspace = tk.Label(status_bar, text=f"工作目录: {self.workspace_dir}", bg=PANEL, fg=MUTED, font=("Microsoft YaHei UI", 9))
        self.footer_workspace.pack(side="right", padx=14)

        main = ttk.Frame(self, style="App.TFrame", padding=(16, 14, 16, 12))
        main.pack(fill="both", expand=True)
        main.rowconfigure(0, weight=1)
        main.columnconfigure(0, weight=0)
        main.columnconfigure(1, weight=1)

        self.sidebar = tk.Frame(main, bg=SIDEBAR_BG, width=224, highlightbackground="#0b1220", highlightthickness=1)
        self.sidebar.grid(row=0, column=0, sticky="nsw", padx=(0, 14))
        self.sidebar.grid_propagate(False)

        workspace = ttk.Frame(main, style="App.TFrame")
        workspace.grid(row=0, column=1, sticky="nsew")
        workspace.rowconfigure(0, weight=1)
        workspace.columnconfigure(0, weight=1)

        self.notebook = ttk.Notebook(workspace, style="Workspace.TNotebook")
        self.notebook.grid(row=0, column=0, sticky="nsew")

        self.tab_home = ttk.Frame(self.notebook, style="App.TFrame", padding=12)
        self.tab_recipe = ttk.Frame(self.notebook, style="App.TFrame", padding=12)
        self.tab_doping = ttk.Frame(self.notebook, style="App.TFrame", padding=12)
        self.tab_geometry = ttk.Frame(self.notebook, style="App.TFrame", padding=12)
        self.tab_modeling = ttk.Frame(self.notebook, style="App.TFrame", padding=12)
        self.tab_crack = ttk.Frame(self.notebook, style="App.TFrame", padding=12)
        self.tab_output = ttk.Frame(self.notebook, style="App.TFrame", padding=12)
        self.tab_lammps = ttk.Frame(self.notebook, style="App.TFrame", padding=12)
        self.tab_about = ttk.Frame(self.notebook, style="App.TFrame", padding=12)
        self.notebook.add(self.tab_home, text="0 工作台")
        self.notebook.add(self.tab_recipe, text="1 配方设计")
        self.notebook.add(self.tab_doping, text="2 掺杂设计")
        self.notebook.add(self.tab_geometry, text="3 梯度晶粒")
        self.notebook.add(self.tab_modeling, text="4 单晶/多晶建模")
        self.notebook.add(self.tab_crack, text="5 裂纹处理")
        self.notebook.add(self.tab_output, text="6 梯度输出")
        self.notebook.add(self.tab_lammps, text="7 LAMMPS接口")
        self.notebook.add(self.tab_about, text="8 教程与帮助")
        self.notebook.bind("<<NotebookTabChanged>>", self._update_navigation, add="+")
        self._build_sidebar()

        self._build_home_tab()
        self._build_recipe_tab()
        self._build_doping_tab()
        self._build_geometry_tab()
        self._build_modeling_tab()
        self._build_crack_tab()
        self._build_output_tab()
        self._build_lammps_tab()
        self._build_about_tab()
        self._build_log_panel(workspace)
        self._update_navigation()

    def _build_recipe_tab(self) -> None:
        scrollable = ScrollableFrame(self.tab_recipe)
        scrollable.pack(fill="both", expand=True)
        root = scrollable.content

        card = ttk.LabelFrame(root, text="摩尔分数配方", style="Section.TLabelframe", padding=12)
        card.pack(fill="x")
        card.columnconfigure(1, weight=1)
        ttk.Label(card, text="直接输入").grid(row=0, column=0, sticky="w")
        recipe_entry = ttk.Entry(card, textvariable=self.recipe_var)
        recipe_entry.grid(row=0, column=1, sticky="ew", padx=(8, 8))
        ttk.Button(card, text="解析配方", command=self._parse_recipe_to_rows).grid(row=0, column=2, sticky="e")
        ttk.Button(card, text="3 元预设", command=lambda: self._apply_recipe_text(DEFAULT_PRESET_3)).grid(row=0, column=3, padx=(8, 0))
        ttk.Button(card, text="5 元预设", command=lambda: self._apply_recipe_text(DEFAULT_PRESET_5)).grid(row=0, column=4, padx=(8, 0))
        ttk.Button(card, text="7 元预设", command=lambda: self._apply_recipe_text(DEFAULT_PRESET_7)).grid(row=0, column=5, padx=(8, 0))
        tk.Label(
            card,
            text="支持直接输入如 Fe20Co20Ni20Cr20Mn20，程序会自动归一化；输入比例可以是份额或摩尔分数。",
            bg=PANEL,
            fg=MUTED,
            font=("Microsoft YaHei UI", 9),
        ).grid(row=1, column=0, columnspan=6, sticky="w", pady=(8, 0))

        table = ttk.LabelFrame(root, text="元素表", style="Section.TLabelframe", padding=12)
        table.pack(fill="x", pady=(12, 0))
        header = ttk.Frame(table)
        header.pack(fill="x", pady=(0, 6))
        ttk.Label(header, text="色块", width=6).grid(row=0, column=0, padx=(0, 8), sticky="w")
        ttk.Label(header, text="元素", width=12).grid(row=0, column=1, padx=(0, 8), sticky="w")
        ttk.Label(header, text="权重/摩尔分数", width=16).grid(row=0, column=2, padx=(0, 8), sticky="w")
        ttk.Label(header, text="质量", width=14).grid(row=0, column=3, padx=(0, 8), sticky="w")
        ttk.Label(header, text="操作", width=8).grid(row=0, column=4, padx=(0, 8), sticky="w")
        self.composition_rows: list[CompositionRow] = []
        for index in range(10):
            row = CompositionRow(
                table,
                index,
                on_change=self._schedule_refresh,
                on_clear=lambda idx=index: self._clear_composition_row(idx),
            )
            row.frame.pack(fill="x", pady=2)
            self.composition_rows.append(row)
        control = ttk.Frame(root)
        control.pack(fill="x", pady=(12, 0))
        ttk.Button(control, text="按比例降序", command=lambda: self._sort_composition("weight")).pack(side="left")
        ttk.Button(control, text="按元素序", command=lambda: self._sort_composition("element")).pack(side="left", padx=(8, 0))
        ttk.Button(control, text="清空全部", command=self._clear_all_composition).pack(side="left", padx=(8, 0))
        tk.Label(control, textvariable=self._composition_status_var(), bg=BACKGROUND, fg=MUTED, font=("Microsoft YaHei UI", 9)).pack(side="right")

        preview = ttk.LabelFrame(root, text="配方预览", style="Section.TLabelframe", padding=12)
        preview.pack(fill="both", expand=True, pady=(12, 0))
        columns = ("元素", "输入权重", "归一化%", "预计原子数", "质量")
        self.composition_tree = ttk.Treeview(preview, columns=columns, show="headings", height=8)
        for column in columns:
            self.composition_tree.heading(column, text=column)
        self.composition_tree.column("元素", width=100, anchor="center")
        self.composition_tree.column("输入权重", width=120, anchor="center")
        self.composition_tree.column("归一化%", width=120, anchor="center")
        self.composition_tree.column("预计原子数", width=120, anchor="center")
        self.composition_tree.column("质量", width=120, anchor="center")
        scroll = ttk.Scrollbar(preview, orient="vertical", command=self.composition_tree.yview)
        self.composition_tree.configure(yscrollcommand=scroll.set)
        self.composition_tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

    def _build_doping_tab(self) -> None:
        scrollable = ScrollableFrame(self.tab_doping)
        scrollable.pack(fill="both", expand=True)
        root = scrollable.content

        template_card = ttk.LabelFrame(root, text="掺杂模板", style="Section.TLabelframe", padding=12)
        template_card.pack(fill="x")
        template_card.columnconfigure(1, weight=1)
        ttk.Label(template_card, text="模板").grid(row=0, column=0, sticky="w")
        self.doping_preset_combo = ttk.Combobox(
            template_card,
            textvariable=self.doping_preset_var,
            values=self._doping_preset_values(),
            width=24,
            state="readonly",
        )
        self.doping_preset_combo.grid(row=0, column=1, sticky="ew", padx=(8, 8))
        self.doping_preset_combo.bind("<<ComboboxSelected>>", lambda _event: self._apply_doping_preset(self.doping_preset_var.get()))
        ttk.Button(template_card, text="套用模板", command=lambda: self._apply_doping_preset(self.doping_preset_var.get())).grid(row=0, column=2, sticky="w")
        ttk.Checkbutton(template_card, text="启用掺杂", variable=self.doping_enabled_var, command=self._schedule_refresh).grid(row=0, column=3, sticky="w", padx=(12, 0))
        tk.Label(
            template_card,
            text="支持 H/O/Si/Cu 等元素的置换、空位、表面吸附和间隙插入；控制参数在吸附时表示表面距离，在界面带中表示带宽。",
            bg=PANEL,
            fg=MUTED,
            font=("Microsoft YaHei UI", 9),
        ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(8, 0))

        table = ttk.LabelFrame(root, text="掺杂表", style="Section.TLabelframe", padding=12)
        table.pack(fill="x", pady=(12, 0))
        header = ttk.Frame(table)
        header.pack(fill="x", pady=(0, 6))
        ttk.Label(header, text="色块", width=6).grid(row=0, column=0, padx=(0, 8), sticky="w")
        ttk.Label(header, text="元素", width=12).grid(row=0, column=1, padx=(0, 8), sticky="w")
        ttk.Label(header, text="操作", width=10).grid(row=0, column=2, padx=(0, 8), sticky="w")
        ttk.Label(header, text="区域", width=12).grid(row=0, column=3, padx=(0, 8), sticky="w")
        ttk.Label(header, text="数量", width=10).grid(row=0, column=4, padx=(0, 8), sticky="w")
        ttk.Label(header, text="单位", width=10).grid(row=0, column=5, padx=(0, 8), sticky="w")
        ttk.Label(header, text="控制参数", width=10).grid(row=0, column=6, padx=(0, 8), sticky="w")
        ttk.Label(header, text="操作", width=8).grid(row=0, column=7, padx=(0, 8), sticky="w")
        self.doping_rows: list[DopingRow] = []
        for index in range(8):
            row = DopingRow(
                table,
                index,
                on_change=self._schedule_refresh,
                on_clear=lambda idx=index: self._clear_doping_row(idx),
            )
            row.frame.pack(fill="x", pady=2)
            self.doping_rows.append(row)
        control = ttk.Frame(root)
        control.pack(fill="x", pady=(12, 0))
        ttk.Button(control, text="按元素序", command=lambda: self._sort_doping_rows("element")).pack(side="left")
        ttk.Button(control, text="按区域序", command=lambda: self._sort_doping_rows("region")).pack(side="left", padx=(8, 0))
        ttk.Button(control, text="清空全部", command=self._clear_all_doping).pack(side="left", padx=(8, 0))
        tk.Label(control, textvariable=self._doping_status, bg=BACKGROUND, fg=MUTED, font=("Microsoft YaHei UI", 9)).pack(side="right")

        preview = ttk.LabelFrame(root, text="掺杂预览", style="Section.TLabelframe", padding=12)
        preview.pack(fill="both", expand=True, pady=(12, 0))
        columns = ("元素", "操作", "区域", "数量", "单位", "控制参数", "预估变更")
        self.doping_tree = ttk.Treeview(preview, columns=columns, show="headings", height=8)
        for column in columns:
            self.doping_tree.heading(column, text=column)
        self.doping_tree.column("元素", width=90, anchor="center")
        self.doping_tree.column("操作", width=90, anchor="center")
        self.doping_tree.column("区域", width=100, anchor="center")
        self.doping_tree.column("数量", width=90, anchor="center")
        self.doping_tree.column("单位", width=90, anchor="center")
        self.doping_tree.column("控制参数", width=100, anchor="center")
        self.doping_tree.column("预估变更", width=110, anchor="center")
        doping_scroll = ttk.Scrollbar(preview, orient="vertical", command=self.doping_tree.yview)
        self.doping_tree.configure(yscrollcommand=doping_scroll.set)
        self.doping_tree.pack(side="left", fill="both", expand=True)
        doping_scroll.pack(side="right", fill="y")

    def _build_geometry_tab(self) -> None:
        geometry_split = ttk.Panedwindow(self.tab_geometry, orient="horizontal")
        geometry_split.pack(fill="both", expand=True)

        controls_panel = ttk.Frame(geometry_split, style="App.TFrame")
        preview_panel = ttk.Frame(geometry_split, style="App.TFrame")
        geometry_split.add(controls_panel, weight=3)
        geometry_split.add(preview_panel, weight=7)

        top = ttk.Frame(controls_panel, style="App.TFrame")
        top.pack(fill="both", expand=True)
        preset_card = ttk.LabelFrame(top, text="模板参数", style="Section.TLabelframe", padding=12)
        preset_card.pack(fill="x")
        preset_card.columnconfigure(1, weight=1)
        preset_label = ttk.Label(preset_card, text="几何模板")
        preset_label.grid(row=0, column=0, sticky="w")
        self.geometry_preset_combo = ttk.Combobox(
            preset_card,
            textvariable=self.geometry_preset_var,
            values=self._geometry_preset_values(),
            width=22,
            state="readonly",
        )
        self.geometry_preset_combo.grid(row=0, column=1, sticky="ew", padx=(8, 8))
        self.geometry_preset_combo.bind("<<ComboboxSelected>>", lambda _event: self._apply_geometry_preset(self.geometry_preset_var.get()))
        preset_apply_button = ttk.Button(preset_card, text="套用模板", command=lambda: self._apply_geometry_preset(self.geometry_preset_var.get()))
        preset_apply_button.grid(row=0, column=2, sticky="w")

        size_card = ttk.LabelFrame(top, text="模型尺寸", style="Section.TLabelframe", padding=12)
        size_card.pack(fill="x", pady=(12, 0))
        for column in range(6):
            size_card.columnconfigure(column, weight=1)
        ttk.Label(size_card, text="宽度 (Å)").grid(row=0, column=0, sticky="w")
        width_entry = ttk.Entry(size_card, textvariable=self.model_width_var, width=12)
        width_entry.grid(row=0, column=1, sticky="w", padx=(8, 24))
        ttk.Label(size_card, text="高度 (Å)").grid(row=0, column=2, sticky="w")
        height_entry = ttk.Entry(size_card, textvariable=self.model_height_var, width=12)
        height_entry.grid(row=0, column=3, sticky="w", padx=(8, 24))
        sync_button = ttk.Button(size_card, text="从源文件同步", command=self._sync_geometry_from_source)
        sync_button.grid(row=0, column=4, sticky="w")

        grain_card = ttk.LabelFrame(top, text="晶粒控制", style="Section.TLabelframe", padding=12)
        grain_card.pack(fill="x", pady=(12, 0))
        for column in range(8):
            grain_card.columnconfigure(column, weight=1)
        ttk.Label(grain_card, text="第一层晶粒数").grid(row=0, column=0, sticky="w")
        first_layer_entry = ttk.Entry(grain_card, textvariable=self.first_layer_count_var, width=10)
        first_layer_entry.grid(row=0, column=1, sticky="w", padx=(8, 18))
        ttk.Label(grain_card, text="目标晶粒尺寸 (Å)").grid(row=0, column=2, sticky="w")
        target_size_entry = ttk.Entry(grain_card, textvariable=self.target_grain_size_var, width=10)
        target_size_entry.grid(row=0, column=3, sticky="w", padx=(8, 18))
        ttk.Label(grain_card, text="层间变化").grid(row=0, column=4, sticky="w")
        delta_entry = ttk.Entry(grain_card, textvariable=self.delta_var, width=10)
        delta_entry.grid(row=0, column=5, sticky="w", padx=(8, 18))
        ttk.Label(grain_card, text="层数").grid(row=0, column=6, sticky="w")
        layers_entry = ttk.Entry(grain_card, textvariable=self.layers_var, width=10)
        layers_entry.grid(row=0, column=7, sticky="w", padx=(8, 0))
        ttk.Label(grain_card, text="种晶晶体结构").grid(row=1, column=0, sticky="w", pady=(8, 0))
        crystal_combo = ttk.Combobox(grain_card, textvariable=self.crystal_structure_var, values=CRYSTAL_STRUCTURE_CHOICES, width=10, state="readonly")
        crystal_combo.grid(row=1, column=1, sticky="w", padx=(8, 18), pady=(8, 0))
        crystal_combo.bind("<<ComboboxSelected>>", lambda _event: self._apply_crystal_structure_defaults())
        ttk.Label(grain_card, text="种晶晶格常数 (Å)").grid(row=1, column=2, sticky="w", pady=(8, 0))
        lattice_entry = ttk.Entry(grain_card, textvariable=self.lattice_param_var, width=10)
        lattice_entry.grid(row=1, column=3, sticky="w", padx=(8, 18), pady=(8, 0))
        ttk.Label(grain_card, text="随机扰动").grid(row=1, column=4, sticky="w", pady=(8, 0))
        chaos_entry = ttk.Entry(grain_card, textvariable=self.chaos_var, width=10)
        chaos_entry.grid(row=1, column=5, sticky="w", padx=(8, 18), pady=(8, 0))
        ttk.Label(grain_card, text="HCP c/a").grid(row=1, column=6, sticky="w", pady=(8, 0))
        hcp_ca_entry = ttk.Entry(grain_card, textvariable=self.hcp_c_over_a_var, width=10)
        hcp_ca_entry.grid(row=1, column=7, sticky="w", padx=(8, 0), pady=(8, 0))
        ttk.Label(grain_card, text="排布方式").grid(row=2, column=0, sticky="w", pady=(8, 0))
        layout_combo = ttk.Combobox(grain_card, textvariable=self.layout_mode_var, values=["layered", "hexagonal"], width=12, state="readonly")
        layout_combo.grid(row=2, column=1, sticky="w", padx=(8, 18), pady=(8, 0))
        layout_combo.bind("<<ComboboxSelected>>", lambda _event: self._schedule_refresh())
        periodic_check = ttk.Checkbutton(grain_card, text="周期结构", variable=self.periodic_var, command=self._schedule_refresh)
        periodic_check.grid(row=2, column=2, sticky="w", pady=(8, 0))
        ttk.Label(grain_card, text="随机种子").grid(row=2, column=4, sticky="w", pady=(8, 0))
        seed_entry = ttk.Entry(grain_card, textvariable=self.seed_var, width=10)
        seed_entry.grid(row=2, column=5, sticky="w", padx=(8, 18), pady=(8, 0))
        ttk.Label(grain_card, text="多核线程").grid(row=2, column=6, sticky="w", pady=(8, 0))
        workers_entry = ttk.Entry(grain_card, textvariable=self.parallel_workers_var, width=8)
        workers_entry.grid(row=2, column=7, sticky="w", padx=(8, 0), pady=(8, 0))
        refresh_button = ttk.Button(grain_card, text="刷新预览", command=self._refresh_geometry_preview)
        refresh_button.grid(row=3, column=7, sticky="e", pady=(8, 0))

        research_card = ttk.LabelFrame(top, text="科研工具", style="Section.TLabelframe", padding=12)
        research_card.pack(fill="x", pady=(12, 0))
        research_card.columnconfigure(3, weight=1)
        copy_button = ttk.Button(research_card, text="复制摘要", command=self._copy_geometry_summary)
        copy_button.grid(row=0, column=0, sticky="w")
        export_nodes_button = ttk.Button(research_card, text="导出节点CSV", command=self._export_geometry_nodes_csv)
        export_nodes_button.grid(row=0, column=1, sticky="w", padx=(8, 0))
        export_report_button = ttk.Button(research_card, text="导出研究报告", command=self._export_geometry_report)
        export_report_button.grid(row=0, column=2, sticky="w", padx=(8, 0))
        tk.Label(
            research_card,
            text="用于论文复现、批量记录和结果对比；导出内容包含摘要、层级信息和节点坐标。",
            bg=PANEL,
            fg=MUTED,
            justify="left",
            wraplength=680,
            font=("Microsoft YaHei UI", 9),
        ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(8, 0))

        preview_card = ttk.LabelFrame(preview_panel, text="几何预览", style="Section.TLabelframe", padding=12)
        preview_card.pack(fill="both", expand=True, pady=(12, 0))
        preview_content = ttk.Panedwindow(preview_card, orient="horizontal")
        preview_content.pack(fill="both", expand=True)
        left_panel = ttk.Frame(preview_content, style="App.TFrame")
        right_panel = ttk.Frame(preview_content, style="App.TFrame")
        preview_content.add(left_panel, weight=2)
        preview_content.add(right_panel, weight=5)
        self.geometry_preview_tree = ttk.Treeview(left_panel, columns=("层", "晶粒数", "晶粒尺寸", "中心 Y"), show="headings", height=10)
        for column in ("层", "晶粒数", "晶粒尺寸", "中心 Y"):
            self.geometry_preview_tree.heading(column, text=column)
        self.geometry_preview_tree.column("层", width=60, anchor="center")
        self.geometry_preview_tree.column("晶粒数", width=80, anchor="center")
        self.geometry_preview_tree.column("晶粒尺寸", width=120, anchor="center")
        self.geometry_preview_tree.column("中心 Y", width=120, anchor="center")
        geo_scroll = ttk.Scrollbar(left_panel, orient="vertical", command=self.geometry_preview_tree.yview)
        self.geometry_preview_tree.configure(yscrollcommand=geo_scroll.set)
        self.geometry_preview_tree.pack(side="left", fill="both", expand=True)
        geo_scroll.pack(side="right", fill="y")
        right_panel.columnconfigure(0, weight=1)
        right_panel.rowconfigure(1, weight=1)
        tk.Label(right_panel, text="模型几何预览", bg=PANEL, fg=TEXT, font=("Microsoft YaHei UI", 11, "bold")).grid(row=0, column=0, sticky="w")
        self.geometry_canvas = tk.Canvas(right_panel, width=720, height=420, bg="#f8fcff", highlightthickness=1, highlightbackground=BORDER)
        self.geometry_canvas.grid(row=1, column=0, sticky="nsew", pady=(8, 8))
        self.geometry_summary = tk.Label(right_panel, text="", bg=PANEL, fg=TEXT, justify="left", anchor="nw", wraplength=660, font=("Microsoft YaHei UI", 10))
        self.geometry_summary.grid(row=2, column=0, sticky="nsew")
        self._add_tooltip(preset_card, "快速套用晶粒模板：参考 final.lmp、Fortran 默认 5 层、无周期对照、细晶模板和六角错位对照。")
        self._add_tooltip(self.geometry_preset_combo, "选择模板后会自动回填模型宽高、层数、扰动、周期和随机种子。")
        self._add_tooltip(preset_apply_button, "按当前模板值重新填充几何参数。")
        self._add_tooltip(size_card, "宽度和高度决定最终几何盒子尺寸。")
        self._add_tooltip(width_entry, "最终模型在 x 方向的长度，单位 Å。")
        self._add_tooltip(height_entry, "最终模型在 y 方向的长度，单位 Å。")
        self._add_tooltip(sync_button, "从当前源文件同步宽高到几何页。")
        self._add_tooltip(grain_card, "这些参数决定分层 Voronoi 的节点分布、周期衔接和多核执行。")
        self._add_tooltip(first_layer_entry, "第一层的晶粒数量。")
        self._add_tooltip(target_size_entry, "给出后会按目标晶粒尺寸反推第一层晶粒数。")
        self._add_tooltip(delta_entry, "每一层相对上一层增加或减少的晶粒数。")
        self._add_tooltip(layers_entry, "总层数。")
        self._add_tooltip(lattice_entry, "种晶的晶格常数。")
        self._add_tooltip(chaos_entry, "节点随机扰动强度。")
        self._add_tooltip(layout_combo, "layered 为分层直列，hexagonal 为错位对照。")
        self._add_tooltip(periodic_check, "启用上下边界周期衔接，生成更接近参考 final.lmp 的布局。")
        self._add_tooltip(seed_entry, "随机种子；留空时使用系统默认随机态。")
        self._add_tooltip(workers_entry, "传给 Atomsk/OpenMP 的并行线程数。")
        self._add_tooltip(refresh_button, "立即刷新几何预览。")
        self._add_tooltip(research_card, "把当前晶粒参数和节点数据导出，方便论文复现和批量记录。")
        self._add_tooltip(copy_button, "把当前几何摘要复制到剪贴板。")
        self._add_tooltip(export_nodes_button, "导出当前节点坐标到 CSV 文件。")
        self._add_tooltip(export_report_button, "导出包含摘要和层级明细的研究报告。")
        self._add_tooltip(preview_card, "左侧表格展示每层参数，右侧实时显示几何分布。")
        self._add_tooltip(self.geometry_preview_tree, "按层查看晶粒数、晶粒尺寸和中心位置。")
        self._add_tooltip(self.geometry_canvas, "实时显示 Voronoi 几何预览。")
        self._add_tooltip(self.geometry_summary, "当前几何参数摘要。")
        self.after_idle(lambda: self._stabilize_geometry_tab_layout(geometry_split))
        self.after_idle(lambda: self._stabilize_geometry_preview_layout(preview_content))

    def _build_modeling_tab(self) -> None:
        scrollable = ScrollableFrame(self.tab_modeling)
        scrollable.pack(fill="both", expand=True)
        body = scrollable.content

        mode_card = ttk.LabelFrame(body, text="建模模式", style="Section.TLabelframe", padding=12)
        mode_card.pack(fill="x")
        mode_card.columnconfigure(7, weight=1)
        ttk.Label(mode_card, text="模式").grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(mode_card, text="三维多晶", value="polycrystal", variable=self.modeling_mode_var, command=self._on_modeling_mode_changed).grid(row=0, column=1, sticky="w", padx=(8, 0))
        ttk.Radiobutton(mode_card, text="纳米粉末", value="powder", variable=self.modeling_mode_var, command=self._on_modeling_mode_changed).grid(row=0, column=2, sticky="w", padx=(8, 0))
        ttk.Radiobutton(mode_card, text="单晶", value="single", variable=self.modeling_mode_var, command=self._on_modeling_mode_changed).grid(row=0, column=3, sticky="w", padx=(8, 0))
        ttk.Label(mode_card, text="随机种子").grid(row=0, column=4, sticky="w", padx=(18, 0))
        seed_entry = ttk.Entry(mode_card, textvariable=self.seed_var, width=12)
        seed_entry.grid(row=0, column=5, sticky="w", padx=(8, 0))
        inherit_check = ttk.Checkbutton(mode_card, text="继承上一步结果", variable=self.inherit_previous_var, command=self._schedule_refresh)
        inherit_check.grid(row=0, column=6, sticky="w", padx=(16, 0))
        tk.Label(
            mode_card,
            text="默认继承上一阶段的配方与掺杂；如果取消勾选，就只生成当前结构模板，不叠加上一阶段的化学流程。",
            bg=PANEL,
            fg=MUTED,
            justify="left",
            wraplength=920,
            font=("Microsoft YaHei UI", 9),
        ).grid(row=1, column=0, columnspan=7, sticky="w", pady=(8, 0))

        content = ttk.Panedwindow(body, orient="horizontal")
        content.pack(fill="both", expand=True, pady=(12, 0))
        left_panel = ttk.Frame(content, style="App.TFrame")
        right_panel = ttk.Frame(content, style="App.TFrame")
        content.add(left_panel, weight=1)
        content.add(right_panel, weight=7)

        left_panel.columnconfigure(0, weight=1)
        left_panel.rowconfigure(0, weight=1)
        self.modeling_controls_stack = ttk.Frame(left_panel, style="App.TFrame")
        self.modeling_controls_stack.grid(row=0, column=0, sticky="nsew")
        self.modeling_controls_stack.columnconfigure(0, weight=1)
        self.modeling_controls_stack.rowconfigure(0, weight=1)

        self.poly_controls_frame = ttk.LabelFrame(self.modeling_controls_stack, text="三维多晶参数", style="Section.TLabelframe", padding=12)
        self.poly_controls_frame.grid(row=0, column=0, sticky="nsew")
        self.poly_controls_frame.columnconfigure(0, weight=1)

        poly_size_card = ttk.LabelFrame(self.poly_controls_frame, text="尺寸", style="Section.TLabelframe", padding=12)
        poly_size_card.pack(fill="x")
        poly_size_card.columnconfigure(1, weight=1)
        ttk.Label(poly_size_card, text="长度 (Å)").grid(row=0, column=0, sticky="w")
        poly_length_entry = ttk.Entry(poly_size_card, textvariable=self.poly_length_var, width=10)
        poly_length_entry.grid(row=0, column=1, sticky="w", padx=(8, 18))
        ttk.Label(poly_size_card, text="宽度 (Å)").grid(row=0, column=2, sticky="w")
        poly_width_entry = ttk.Entry(poly_size_card, textvariable=self.poly_width_var, width=10)
        poly_width_entry.grid(row=0, column=3, sticky="w", padx=(8, 18))
        ttk.Label(poly_size_card, text="高度 (Å)").grid(row=0, column=4, sticky="w")
        poly_height_entry = ttk.Entry(poly_size_card, textvariable=self.poly_height_var, width=10)
        poly_height_entry.grid(row=0, column=5, sticky="w", padx=(8, 0))

        poly_layout_card = ttk.LabelFrame(self.poly_controls_frame, text="布局", style="Section.TLabelframe", padding=12)
        poly_layout_card.pack(fill="x", pady=(12, 0))
        poly_layout_card.columnconfigure(1, weight=1)
        ttk.Label(poly_layout_card, text="布局模式").grid(row=0, column=0, sticky="w")
        poly_layout_combo = ttk.Combobox(poly_layout_card, textvariable=self.poly_layout_var, values=list(POLYCRYSTAL_LAYOUT_MODES), width=14, state="readonly")
        poly_layout_combo.grid(row=0, column=1, sticky="w", padx=(8, 0))
        tk.Label(
            poly_layout_card,
            text="grid 保持规则网格种子；random 会在每个网格单元内随机播种，更接近 Atomsk 随机多晶的感觉。",
            bg=PANEL,
            fg=MUTED,
            justify="left",
            wraplength=360,
            font=("Microsoft YaHei UI", 9),
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))

        poly_action_row = ttk.Frame(self.poly_controls_frame)
        poly_action_row.pack(fill="x", pady=(12, 0))
        poly_preview_button = ttk.Button(poly_action_row, text="刷新预览", command=self._refresh_simple_polycrystal_preview)
        poly_preview_button.grid(row=0, column=0, sticky="w")
        poly_generate_button = ttk.Button(poly_action_row, text="生成多晶", style="Accent.TButton", command=self._generate_simple_polycrystal)
        poly_generate_button.grid(row=0, column=1, sticky="w", padx=(8, 0))
        poly_export_button = ttk.Button(poly_action_row, text="导出 data", command=self._export_current_model_data_file)
        poly_export_button.grid(row=0, column=2, sticky="w", padx=(8, 0))

        self.powder_controls_frame = ttk.LabelFrame(self.modeling_controls_stack, text="高熵合金纳米粉末参数", style="Section.TLabelframe", padding=12)
        self.powder_controls_frame.grid(row=0, column=0, sticky="nsew")
        self.powder_controls_frame.columnconfigure(0, weight=1)

        powder_size_card = ttk.LabelFrame(self.powder_controls_frame, text="尺寸和形状", style="Section.TLabelframe", padding=12)
        powder_size_card.pack(fill="x")
        powder_size_card.columnconfigure(1, weight=1)
        ttk.Label(powder_size_card, text="粉末大小 (Å)").grid(row=0, column=0, sticky="w")
        powder_size_entry = ttk.Entry(powder_size_card, textvariable=self.powder_size_var, width=10)
        powder_size_entry.grid(row=0, column=1, sticky="w", padx=(8, 18))
        ttk.Label(powder_size_card, text="个数").grid(row=0, column=2, sticky="w")
        powder_count_entry = ttk.Entry(powder_size_card, textvariable=self.powder_count_var, width=10)
        powder_count_entry.grid(row=0, column=3, sticky="w", padx=(8, 18))
        ttk.Label(powder_size_card, text="形状").grid(row=0, column=4, sticky="w")
        powder_shape_combo = ttk.Combobox(powder_size_card, textvariable=self.powder_shape_var, values=list(POWDER_SHAPE_PRESETS), width=14, state="readonly")
        powder_shape_combo.grid(row=0, column=5, sticky="w", padx=(8, 0))
        tk.Label(
            powder_size_card,
            text="新增 cylinder 和 octahedron 形状；这些预设会直接参与原子筛选和预览。",
            bg=PANEL,
            fg=MUTED,
            justify="left",
            wraplength=360,
            font=("Microsoft YaHei UI", 9),
        ).grid(row=1, column=0, columnspan=6, sticky="w", pady=(8, 0))

        powder_action_row = ttk.Frame(self.powder_controls_frame)
        powder_action_row.pack(fill="x", pady=(12, 0))
        powder_preview_button = ttk.Button(powder_action_row, text="刷新预览", command=self._refresh_nanopowder_preview)
        powder_preview_button.grid(row=0, column=0, sticky="w")
        powder_generate_button = ttk.Button(powder_action_row, text="生成粉末", style="Accent.TButton", command=self._generate_nanopowder)
        powder_generate_button.grid(row=0, column=1, sticky="w", padx=(8, 0))
        powder_export_button = ttk.Button(powder_action_row, text="导出 data", command=self._export_current_model_data_file)
        powder_export_button.grid(row=0, column=2, sticky="w", padx=(8, 0))

        self.single_controls_frame = ttk.LabelFrame(self.modeling_controls_stack, text="单晶/缺陷参数", style="Section.TLabelframe", padding=12)
        self.single_controls_frame.grid(row=0, column=0, sticky="nsew")
        self.single_controls_frame.columnconfigure(0, weight=1)

        single_size_card = ttk.LabelFrame(self.single_controls_frame, text="尺寸", style="Section.TLabelframe", padding=12)
        single_size_card.pack(fill="x")
        single_size_card.columnconfigure(1, weight=1)
        ttk.Label(single_size_card, text="长度 (Å)").grid(row=0, column=0, sticky="w")
        single_length_entry = ttk.Entry(single_size_card, textvariable=self.single_length_var, width=10)
        single_length_entry.grid(row=0, column=1, sticky="w", padx=(8, 18))
        ttk.Label(single_size_card, text="宽度 (Å)").grid(row=0, column=2, sticky="w")
        single_width_entry = ttk.Entry(single_size_card, textvariable=self.single_width_var, width=10)
        single_width_entry.grid(row=0, column=3, sticky="w", padx=(8, 18))
        ttk.Label(single_size_card, text="高度 (Å)").grid(row=0, column=4, sticky="w")
        single_height_entry = ttk.Entry(single_size_card, textvariable=self.single_height_var, width=10)
        single_height_entry.grid(row=0, column=5, sticky="w", padx=(8, 0))
        tk.Label(
            single_size_card,
            text="单晶默认尺寸比多晶更适合先从 100~150 Å 开始；过大时预览会自动采样。",
            bg=PANEL,
            fg=MUTED,
            justify="left",
            wraplength=360,
            font=("Microsoft YaHei UI", 9),
        ).grid(row=1, column=0, columnspan=6, sticky="w", pady=(8, 0))

        single_face_card = ttk.LabelFrame(self.single_controls_frame, text="晶面与取向", style="Section.TLabelframe", padding=12)
        single_face_card.pack(fill="x", pady=(12, 0))
        single_face_card.columnconfigure(1, weight=1)
        ttk.Label(single_face_card, text="晶面取向").grid(row=0, column=0, sticky="w")
        single_orientation_combo = ttk.Combobox(single_face_card, textvariable=self.single_orientation_var, values=list(SINGLE_CRYSTAL_ORIENTATIONS), width=14, state="readonly")
        single_orientation_combo.grid(row=0, column=1, sticky="w", padx=(8, 0))
        tk.Label(
            single_face_card,
            text="这里决定晶面朝向，也就是后续做表面、台阶和切面研究时的基底方向。",
            bg=PANEL,
            fg=MUTED,
            justify="left",
            wraplength=360,
            font=("Microsoft YaHei UI", 9),
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))

        single_defect_card = ttk.LabelFrame(self.single_controls_frame, text="缺陷模板", style="Section.TLabelframe", padding=12)
        single_defect_card.pack(fill="x", pady=(12, 0))
        single_defect_card.columnconfigure(1, weight=1)
        ttk.Label(single_defect_card, text="缺陷类型").grid(row=0, column=0, sticky="w")
        single_defect_combo = ttk.Combobox(single_defect_card, textvariable=self.single_defect_var, values=list(SINGLE_CRYSTAL_DEFECT_MODES), width=18, state="readonly")
        single_defect_combo.grid(row=0, column=1, sticky="w", padx=(8, 0))
        ttk.Label(single_defect_card, text="缺陷角度 (°)").grid(row=1, column=0, sticky="w", pady=(10, 0))
        single_defect_angle_entry = ttk.Entry(single_defect_card, textvariable=self.single_defect_angle_var, width=10)
        single_defect_angle_entry.grid(row=1, column=1, sticky="w", padx=(8, 0), pady=(10, 0))
        ttk.Label(single_defect_card, text="核半径 (Å)").grid(row=1, column=2, sticky="w", padx=(18, 0), pady=(10, 0))
        single_defect_core_entry = ttk.Entry(single_defect_card, textvariable=self.single_defect_core_var, width=10)
        single_defect_core_entry.grid(row=1, column=3, sticky="w", padx=(8, 0), pady=(10, 0))
        tk.Label(
            single_defect_card,
            text="晶界双晶会按角度分成两侧；位错模板会根据核半径删去核心原子并施加位移场。",
            bg=PANEL,
            fg=MUTED,
            justify="left",
            wraplength=360,
            font=("Microsoft YaHei UI", 9),
        ).grid(row=2, column=0, columnspan=4, sticky="w", pady=(8, 0))

        single_action_row = ttk.Frame(self.single_controls_frame)
        single_action_row.pack(fill="x", pady=(12, 0))
        single_preview_button = ttk.Button(single_action_row, text="刷新预览", command=self._refresh_single_crystal_preview)
        single_preview_button.grid(row=0, column=0, sticky="w")
        single_generate_button = ttk.Button(single_action_row, text="生成单晶", style="Accent.TButton", command=self._generate_single_crystal)
        single_generate_button.grid(row=0, column=1, sticky="w", padx=(8, 0))
        single_export_button = ttk.Button(single_action_row, text="导出 data", command=self._export_current_model_data_file)
        single_export_button.grid(row=0, column=2, sticky="w", padx=(8, 0))

        atomsk_advanced_card = ttk.LabelFrame(body, text="Atomsk 高级构型后处理", style="Section.TLabelframe", padding=12)
        atomsk_advanced_card.pack(fill="x", pady=(12, 0))
        for column in (1, 7):
            atomsk_advanced_card.columnconfigure(column, weight=1)
        ttk.Label(atomsk_advanced_card, text="操作").grid(row=0, column=0, sticky="w")
        atomsk_operation_combo = ttk.Combobox(atomsk_advanced_card, textvariable=self.atomsk_operation_var, values=list(ATOMSK_OPERATION_CHOICES), width=20, state="readonly")
        atomsk_operation_combo.grid(row=0, column=1, sticky="w", padx=(8, 18))
        ttk.Label(atomsk_advanced_card, text="复制").grid(row=0, column=2, sticky="w")
        atomsk_dup_x_entry = ttk.Entry(atomsk_advanced_card, textvariable=self.atomsk_duplicate_x_var, width=5)
        atomsk_dup_x_entry.grid(row=0, column=3, sticky="w", padx=(8, 4))
        atomsk_dup_y_entry = ttk.Entry(atomsk_advanced_card, textvariable=self.atomsk_duplicate_y_var, width=5)
        atomsk_dup_y_entry.grid(row=0, column=4, sticky="w", padx=(4, 4))
        atomsk_dup_z_entry = ttk.Entry(atomsk_advanced_card, textvariable=self.atomsk_duplicate_z_var, width=5)
        atomsk_dup_z_entry.grid(row=0, column=5, sticky="w", padx=(4, 18))
        ttk.Label(atomsk_advanced_card, text="镜像轴").grid(row=0, column=6, sticky="w")
        atomsk_axis_combo = ttk.Combobox(atomsk_advanced_card, textvariable=self.atomsk_mirror_axis_var, values=["X", "Y", "Z"], width=5, state="readonly")
        atomsk_axis_combo.grid(row=0, column=7, sticky="w", padx=(8, 0))
        ttk.Label(atomsk_advanced_card, text="Atomsk").grid(row=1, column=0, sticky="w", pady=(10, 0))
        atomsk_path_entry = ttk.Entry(atomsk_advanced_card, textvariable=self.atomsk_path_var)
        atomsk_path_entry.grid(row=1, column=1, columnspan=6, sticky="ew", padx=(8, 8), pady=(10, 0))
        atomsk_browse_button = ttk.Button(atomsk_advanced_card, text="浏览", command=self._browse_atomsk)
        atomsk_browse_button.grid(row=1, column=7, sticky="w", pady=(10, 0))
        ttk.Label(atomsk_advanced_card, text="输出").grid(row=2, column=0, sticky="w", pady=(10, 0))
        atomsk_output_entry = ttk.Entry(atomsk_advanced_card, textvariable=self.atomsk_output_var)
        atomsk_output_entry.grid(row=2, column=1, columnspan=6, sticky="ew", padx=(8, 8), pady=(10, 0))
        atomsk_output_button = ttk.Button(atomsk_advanced_card, text="浏览", command=self._browse_atomsk_postprocess_output)
        atomsk_output_button.grid(row=2, column=7, sticky="w", pady=(10, 0))
        atomsk_preview_label = tk.Label(
            atomsk_advanced_card,
            textvariable=self.atomsk_command_preview_var,
            bg=PANEL,
            fg=MUTED,
            justify="left",
            wraplength=980,
            font=("Consolas", 9),
        )
        atomsk_preview_label.grid(row=3, column=0, columnspan=8, sticky="ew", pady=(10, 0))
        atomsk_action_row = ttk.Frame(atomsk_advanced_card)
        atomsk_action_row.grid(row=4, column=0, columnspan=8, sticky="ew", pady=(10, 0))
        atomsk_refresh_button = ttk.Button(atomsk_action_row, text="预览命令", command=self._refresh_atomsk_command_preview)
        atomsk_refresh_button.pack(side="left")
        atomsk_run_button = ttk.Button(atomsk_action_row, text="执行 Atomsk 后处理", style="Accent.TButton", command=self._run_atomsk_postprocess)
        atomsk_run_button.pack(side="left", padx=(8, 0))
        tk.Label(
            atomsk_action_row,
            text="当前源文件来自右侧/工作流当前模型；执行后会切换为新的输出模型并写入 .atomsk.txt 复现报告。",
            bg=BACKGROUND,
            fg=MUTED,
            font=("Microsoft YaHei UI", 9),
        ).pack(side="left", padx=(14, 0))
        atomsk_operation_combo.bind("<<ComboboxSelected>>", lambda _event: self._refresh_atomsk_command_preview())
        atomsk_axis_combo.bind("<<ComboboxSelected>>", lambda _event: self._refresh_atomsk_command_preview())
        for entry in (atomsk_dup_x_entry, atomsk_dup_y_entry, atomsk_dup_z_entry, atomsk_path_entry, atomsk_output_entry):
            entry.bind("<KeyRelease>", lambda _event: self._refresh_atomsk_command_preview())

        right_panel.columnconfigure(0, weight=1)
        right_panel.rowconfigure(0, weight=1)
        preview_card = ttk.LabelFrame(right_panel, text="预览窗口", style="Section.TLabelframe", padding=12)
        preview_card.pack(fill="both", expand=True)
        preview_card.columnconfigure(0, weight=1)
        preview_card.rowconfigure(1, weight=8)
        preview_card.rowconfigure(2, weight=1)
        preview_card.rowconfigure(3, weight=3)
        self.modeling_preview_title = tk.Label(preview_card, text="", bg=PANEL, fg=TEXT, font=("Microsoft YaHei UI", 11, "bold"))
        self.modeling_preview_title.grid(row=0, column=0, sticky="w")
        self.modeling_preview_canvas = tk.Canvas(preview_card, width=760, height=460, bg="#f8fcff", highlightthickness=1, highlightbackground=BORDER)
        self.modeling_preview_canvas.grid(row=1, column=0, sticky="nsew", pady=(8, 8))
        self.modeling_preview_summary = tk.Label(preview_card, text="", bg=PANEL, fg=TEXT, justify="left", anchor="nw", wraplength=700, font=("Microsoft YaHei UI", 10))
        self.modeling_preview_summary.grid(row=2, column=0, sticky="nsew")

        detail_card = ttk.LabelFrame(preview_card, text="详细数据", style="Section.TLabelframe", padding=12)
        detail_card.grid(row=3, column=0, sticky="nsew", pady=(12, 0))
        detail_card.columnconfigure(0, weight=1)
        detail_card.rowconfigure(1, weight=1)
        self.modeling_detail_title = tk.Label(detail_card, text="", bg=PANEL, fg=TEXT, font=("Microsoft YaHei UI", 10, "bold"))
        self.modeling_detail_title.grid(row=0, column=0, sticky="w")
        detail_tree_wrap = ttk.Frame(detail_card)
        detail_tree_wrap.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        detail_tree_wrap.columnconfigure(0, weight=1)
        detail_tree_wrap.rowconfigure(0, weight=1)
        self.modeling_detail_tree = ttk.Treeview(detail_tree_wrap, columns=(), show="headings", height=5)
        detail_scroll = ttk.Scrollbar(detail_tree_wrap, orient="vertical", command=self.modeling_detail_tree.yview)
        self.modeling_detail_tree.configure(yscrollcommand=detail_scroll.set)
        self.modeling_detail_tree.grid(row=0, column=0, sticky="nsew")
        detail_scroll.grid(row=0, column=1, sticky="ns")

        self._add_tooltip(mode_card, "三维多晶、纳米粉末和单晶都共用当前配方和掺杂结果。")
        self._add_tooltip(inherit_check, "默认开启时会把当前配方和掺杂流程带到新生成的结构里。")
        self._add_tooltip(seed_entry, "随机种子会同时影响多晶播种、粉末分布和后续配方分配。")
        self._add_tooltip(self.poly_controls_frame, "只控制长宽高和布局模式的三维多晶建模。")
        self._add_tooltip(poly_length_entry, "三维多晶的 x 向长度。")
        self._add_tooltip(poly_width_entry, "三维多晶的 y 向宽度。")
        self._add_tooltip(poly_height_entry, "三维多晶的 z 向高度。")
        self._add_tooltip(poly_layout_combo, "grid 会维持规则网格；random 会在每个单元里随机偏移种子位置。")
        self._add_tooltip(poly_preview_button, "根据当前三维多晶参数刷新预览。")
        self._add_tooltip(poly_generate_button, "生成三维多晶源文件，并自动继承当前配方与掺杂。")
        self._add_tooltip(self.powder_controls_frame, "高熵合金纳米粉末建模，可控粉末大小、个数和形状。")
        self._add_tooltip(powder_size_entry, "单个粉末颗粒的尺度，球形/圆柱时可视作直径，立方时可视作边长。")
        self._add_tooltip(powder_count_entry, "粉末颗粒个数。")
        self._add_tooltip(powder_shape_combo, "可选 sphere、cube、ellipsoid、cylinder、octahedron。")
        self._add_tooltip(powder_preview_button, "根据当前粉末参数刷新预览。")
        self._add_tooltip(powder_generate_button, "生成纳米粉末源文件，并自动继承当前配方与掺杂。")
        self._add_tooltip(self.single_controls_frame, "单晶模式用于晶面、晶界和位错示意模型。")
        self._add_tooltip(single_length_entry, "单晶的 x 向长度。")
        self._add_tooltip(single_width_entry, "单晶的 y 向宽度。")
        self._add_tooltip(single_height_entry, "单晶的 z 向高度。")
        self._add_tooltip(single_orientation_combo, "选择晶面朝向，决定后续表面与切面的基准方向。")
        self._add_tooltip(single_defect_combo, "完美单晶、晶界双晶、边位错和螺位错模板。")
        self._add_tooltip(single_defect_angle_entry, "晶界双晶的旋转角度，单位为度。")
        self._add_tooltip(single_defect_core_entry, "位错核心区域的删减半径，单位为 Å。")
        self._add_tooltip(single_preview_button, "根据当前单晶参数刷新预览。")
        self._add_tooltip(single_generate_button, "生成单晶源文件，并自动继承当前配方与掺杂。")
        self._add_tooltip(atomsk_advanced_card, "对当前模型执行 Atomsk 后处理，适合超胞放大、镜像孪晶和双层界面构建。")
        self._add_tooltip(atomsk_operation_combo, "standardize 只做格式标准化和 wrap；duplicate 复制超胞；mirror 做镜像；mirror_merge 会镜像后沿指定轴合并。")
        self._add_tooltip(atomsk_dup_x_entry, "X 方向复制倍数，仅复制超胞操作使用。")
        self._add_tooltip(atomsk_dup_y_entry, "Y 方向复制倍数，仅复制超胞操作使用。")
        self._add_tooltip(atomsk_dup_z_entry, "Z 方向复制倍数，仅复制超胞操作使用。")
        self._add_tooltip(atomsk_axis_combo, "镜像与镜像合并操作使用的轴向。")
        self._add_tooltip(atomsk_path_entry, "Atomsk 可执行文件路径；可直接浏览 atomsk.exe。")
        self._add_tooltip(atomsk_browse_button, "选择 atomsk.exe。")
        self._add_tooltip(atomsk_output_entry, "建议输出为 .lmp，便于直接接入后续配方、裂纹和 LAMMPS 流程。")
        self._add_tooltip(atomsk_refresh_button, "预览将要执行的 Atomsk 命令。")
        self._add_tooltip(atomsk_run_button, "执行 Atomsk 命令，并把结果作为当前模型源文件。")
        self._add_tooltip(self.modeling_preview_title, "当前模式的主预览标题。")
        self._add_tooltip(self.modeling_preview_canvas, "显示当前建模模式的几何投影。")
        self._add_tooltip(self.modeling_preview_summary, "显示当前建模参数摘要。")
        self._add_tooltip(self.modeling_detail_tree, "显示当前建模模式的种子或颗粒明细。")

        self._sync_modeling_mode_panels()
        self._refresh_atomsk_command_preview()
        self.after_idle(self._refresh_modeling_previews)

    def _current_modeling_mode(self) -> str:
        mode = self.modeling_mode_var.get().strip().lower()
        if mode not in {"polycrystal", "powder", "single"}:
            mode = "polycrystal"
            self.modeling_mode_var.set(mode)
        return mode

    def _on_modeling_mode_changed(self) -> None:
        self._sync_modeling_mode_panels()
        self._refresh_modeling_previews()

    def _sync_modeling_mode_panels(self) -> None:
        mode = self._current_modeling_mode()
        has_poly = hasattr(self, "poly_controls_frame") and self.poly_controls_frame.winfo_exists()
        has_powder = hasattr(self, "powder_controls_frame") and self.powder_controls_frame.winfo_exists()
        has_single = hasattr(self, "single_controls_frame") and self.single_controls_frame.winfo_exists()
        if has_poly:
            if mode == "polycrystal":
                self.poly_controls_frame.grid()
                if has_powder:
                    self.powder_controls_frame.grid_remove()
                if has_single:
                    self.single_controls_frame.grid_remove()
            else:
                self.poly_controls_frame.grid_remove()
        if has_powder:
            if mode == "powder":
                self.powder_controls_frame.grid()
                if has_single:
                    self.single_controls_frame.grid_remove()
            else:
                self.powder_controls_frame.grid_remove()
        if has_single:
            if mode == "single":
                self.single_controls_frame.grid()
            else:
                self.single_controls_frame.grid_remove()
        if hasattr(self, "modeling_preview_title") and self.modeling_preview_title.winfo_exists():
            if mode == "polycrystal":
                self.modeling_preview_title.configure(text="三维多晶预览")
            elif mode == "powder":
                self.modeling_preview_title.configure(text="纳米粉末预览")
            else:
                self.modeling_preview_title.configure(text="单晶预览")
        if hasattr(self, "modeling_detail_title") and self.modeling_detail_title.winfo_exists():
            if mode == "polycrystal":
                self.modeling_detail_title.configure(text="种子布局")
            elif mode == "powder":
                self.modeling_detail_title.configure(text="颗粒布局")
            else:
                self.modeling_detail_title.configure(text="晶向与缺陷")

    def _modeling_preview_widgets_ready(self) -> bool:
        return bool(
            hasattr(self, "modeling_preview_canvas")
            and hasattr(self, "modeling_preview_summary")
            and hasattr(self, "modeling_detail_tree")
            and self.modeling_preview_canvas.winfo_exists()
            and self.modeling_preview_summary.winfo_exists()
            and self.modeling_detail_tree.winfo_exists()
        )

    def _configure_modeling_detail_tree(self, columns: list[str], widths: list[int]) -> None:
        tree = self.modeling_detail_tree
        tree.configure(columns=columns, show="headings")
        for item in tree.get_children():
            tree.delete(item)
        for index, column in enumerate(columns):
            width = widths[index] if index < len(widths) else 100
            tree.heading(column, text=column)
            tree.column(column, width=width, anchor="center")

    def _simple_polycrystal_config(self) -> SimplePolycrystalConfig:
        atomsk_path = find_atomsk_exe(self.atomsk_path_var.get())
        length = parse_float(self.poly_length_var.get(), "多晶长度")
        width = parse_float(self.poly_width_var.get(), "多晶宽度")
        height = parse_float(self.poly_height_var.get(), "多晶高度")
        if length <= 0 or width <= 0 or height <= 0:
            raise ValueError("多晶长宽高必须大于 0")
        layout_mode = self.poly_layout_var.get().strip().lower()
        if layout_mode not in POLYCRYSTAL_LAYOUT_MODES:
            raise ValueError("三维多晶布局模式只支持 grid 或 random")
        seed_text = self.seed_var.get().strip()
        seed = int(seed_text) if seed_text else None
        crystal_structure = normalize_crystal_structure(self.crystal_structure_var.get())
        hcp_c_over_a = parse_optional_float(self.hcp_c_over_a_var.get()) if crystal_structure == "hcp" else None
        return SimplePolycrystalConfig(
            atomsk_path=atomsk_path,
            length=length,
            width=width,
            height=height,
            crystal_structure=crystal_structure,
            lattice_parameter=parse_float(self.lattice_param_var.get(), "种晶晶格常数"),
            hcp_c_over_a=hcp_c_over_a if hcp_c_over_a is not None else (DEFAULT_HCP_C_OVER_A if crystal_structure == "hcp" else None),
            seed=seed,
            layout_mode=layout_mode,
        )

    def _default_atomsk_postprocess_output(self) -> Path:
        return WORK_DIR / "atomsk_advanced" / "atomsk_model.lmp"

    def _atomsk_postprocess_config(self) -> AtomskPostprocessConfig:
        atomsk_path = find_atomsk_exe(self.atomsk_path_var.get())
        source_text = self.source_path_var.get().strip()
        if not source_text:
            raise ValueError("当前模型源文件为空，请先生成或选择一个模型")
        source_path = Path(source_text).expanduser()
        output_text = self.atomsk_output_var.get().strip()
        output_path = Path(output_text).expanduser() if output_text else self._default_atomsk_postprocess_output()
        operation = normalize_atomsk_operation(self.atomsk_operation_var.get())
        duplicate = parse_atomsk_duplicate_factors(
            self.atomsk_duplicate_x_var.get(),
            self.atomsk_duplicate_y_var.get(),
            self.atomsk_duplicate_z_var.get(),
        )
        mirror_axis = normalize_atomsk_axis(self.atomsk_mirror_axis_var.get())
        return AtomskPostprocessConfig(
            atomsk_path=atomsk_path,
            source_path=source_path,
            output_path=output_path,
            operation=operation,
            duplicate=duplicate,
            mirror_axis=mirror_axis,
        )

    def _refresh_atomsk_command_preview(self) -> None:
        if not hasattr(self, "atomsk_command_preview_var"):
            return
        try:
            config = self._atomsk_postprocess_config()
            plan = build_atomsk_postprocess_plan(config)
            command_lines = [subprocess.list2cmdline([str(part) for part in command]) for command in plan.commands]
            self.atomsk_command_preview_var.set(f"{plan.description}\n" + "\n".join(command_lines))
        except Exception as exc:
            self.atomsk_command_preview_var.set(f"Atomsk 命令预览失败: {exc}")

    def _browse_atomsk_postprocess_output(self) -> None:
        initial = Path(self.atomsk_output_var.get().strip() or str(self._default_atomsk_postprocess_output())).expanduser()
        selected = filedialog.asksaveasfilename(
            title="选择 Atomsk 输出文件",
            initialdir=str(initial.parent if initial.parent.exists() else WORK_DIR),
            initialfile=initial.name,
            defaultextension=".lmp",
            filetypes=[("LAMMPS data", "*.lmp *.data"), ("CFG/XSF", "*.cfg *.xsf"), ("All files", "*.*")],
        )
        if selected:
            self.atomsk_output_var.set(selected)
            self._refresh_atomsk_command_preview()

    def _run_atomsk_postprocess(self) -> None:
        try:
            config = self._atomsk_postprocess_config()
            output_path, report_path = run_atomsk_postprocess(config, env=self._subprocess_env())
            self._invalidate_structure_cache()
            self.source_path_var.set(str(output_path))
            self.lammps_data_file_var.set(str(output_path))
            self._load_source_info()
            self._refresh_all()
            self._refresh_modeling_previews()
            self._refresh_atomsk_command_preview()
            self._set_status("Atomsk 后处理完成", SUCCESS)
            self._log(f"Atomsk 后处理完成: {output_path}; 报告: {report_path}")
        except Exception as exc:
            messagebox.showerror("Atomsk 后处理失败", str(exc))
            self._log(f"Atomsk 后处理失败: {exc}")

    def _refresh_simple_polycrystal_preview(self) -> None:
        if not self._modeling_preview_widgets_ready():
            return
        try:
            config = self._simple_polycrystal_config()
            seeds, grid, cells, grain_scale = build_uniform_polycrystal_layout(config)
        except Exception as exc:
            self.modeling_preview_title.configure(text="三维多晶预览")
            self.modeling_detail_title.configure(text="提示")
            self.modeling_preview_summary.configure(text=f"预览失败: {exc}")
            self._configure_modeling_detail_tree(["提示"], [300])
            self.modeling_detail_tree.insert("", "end", values=(f"预览失败: {exc}",))
            self.modeling_preview_canvas.delete("all")
            self.modeling_preview_canvas.create_text(180, 110, text=f"预览失败: {exc}", fill=DANGER, font=("Microsoft YaHei UI", 10), anchor="center")
            return
        self.modeling_preview_title.configure(text=f"三维多晶预览 · {polycrystal_layout_label(config.layout_mode)}")
        self.modeling_detail_title.configure(text="种子布局")
        self._configure_modeling_detail_tree(["格点", "X", "Y", "Z"], [80, 110, 110, 110])
        for seed in seeds:
            self.modeling_detail_tree.insert("", "end", values=(f"{seed.ix + 1}-{seed.iy + 1}-{seed.iz + 1}", f"{seed.x:.3f}", f"{seed.y:.3f}", f"{seed.z:.3f}"))
        summary_text = [
            f"长宽高: {config.length:.3f} x {config.width:.3f} x {config.height:.3f} Å",
            f"布局模式: {polycrystal_layout_label(config.layout_mode)}",
            f"默认晶粒尺度: {grain_scale:.3f} Å",
            f"三维网格: {grid[0]} x {grid[1]} x {grid[2]}",
            f"种子数: {len(seeds)}",
            f"单元尺寸: {cells[0]:.3f} x {cells[1]:.3f} x {cells[2]:.3f} Å",
        ]
        self.modeling_preview_summary.configure(text="\n".join(summary_text))
        self._render_volume_seed_canvas(self.modeling_preview_canvas, seeds, config.length, config.width, config.height)

    def _render_volume_seed_canvas(self, canvas: tk.Canvas, seeds: list[VolumeSeed], length: float, width: float, height: float) -> None:
        canvas.delete("all")
        canvas_width = int(canvas.winfo_width() or canvas.cget("width"))
        canvas_height = int(canvas.winfo_height() or canvas.cget("height"))
        canvas_width = max(canvas_width, 360)
        canvas_height = max(canvas_height, 220)
        canvas.config(width=canvas_width, height=canvas_height)
        canvas.create_rectangle(0, 0, canvas_width, canvas_height, fill="#f8fcff", outline=BORDER)
        if not seeds or length <= 0 or width <= 0 or height <= 0:
            canvas.create_text(canvas_width / 2, canvas_height / 2, text="三维多晶预览等待有效参数", fill=MUTED, font=("Microsoft YaHei UI", 10))
            return
        padding = 14
        inner_w = max(1.0, canvas_width - 2 * padding)
        inner_h = max(1.0, canvas_height - 2 * padding)
        projected = [
            (
                padding + (seed.x / length) * inner_w,
                padding + (seed.y / width) * inner_h,
                seed.z / height,
            )
            for seed in seeds
        ]
        for seed_x, seed_y, seed_z in projected:
            red, green, blue = colorsys.hls_to_rgb((seed_z * 0.65) % 1.0, 0.62, 0.70)
            color = "#{:02x}{:02x}{:02x}".format(int(red * 255), int(green * 255), int(blue * 255))
            canvas.create_oval(seed_x - 3, seed_y - 3, seed_x + 3, seed_y + 3, fill=color, outline="#0f2f4f", width=1)
        canvas.create_text(16, 12, text=f"种子数 {len(seeds)}", fill=TEXT, anchor="w", font=("Microsoft YaHei UI", 9, "bold"))

    def _generate_simple_polycrystal(self) -> None:
        try:
            config = self._simple_polycrystal_config()
            base_output = WORK_DIR / "simple_polycrystal" / "base.lmp"
            final_output = WORK_DIR / "simple_polycrystal" / "final.lmp"
            seeds, grid, cells, grain_scale = generate_uniform_polycrystal(config.atomsk_path, config, base_output, env=self._subprocess_env())
            self._invalidate_structure_cache()
            if self.inherit_previous_var.get():
                result = self._assign_alloy(base_output, final_output)
                final_path = result.final_path
            else:
                shutil.copyfile(base_output, final_output)
                self._invalidate_structure_cache()
                final_path = final_output
            self.source_path_var.set(str(final_path))
            self.lammps_data_file_var.set(str(final_path))
            self._load_source_info()
            self._refresh_all()
            self._refresh_modeling_previews()
            self._set_status("三维多晶已生成", SUCCESS)
            inherit_note = "已继承当前配方/掺杂" if self.inherit_previous_var.get() else "未继承配方/掺杂"
            self._log(
                f"三维多晶已生成: {final_path}; 布局 {polycrystal_layout_label(config.layout_mode)}; 网格 {grid[0]} x {grid[1]} x {grid[2]}; 种子数 {len(seeds)}; 默认晶粒尺度 {grain_scale:.3f} Å; {inherit_note}"
            )
        except Exception as exc:
            messagebox.showerror("生成多晶失败", str(exc))
            self._log(f"生成三维多晶失败: {exc}")

    def _nanopowder_config(self) -> NanopowderConfig:
        size = parse_float(self.powder_size_var.get(), "粉末大小")
        count = parse_int(self.powder_count_var.get(), "粉末个数")
        if size <= 0:
            raise ValueError("粉末大小必须大于 0")
        if count <= 0:
            raise ValueError("粉末个数必须大于 0")
        shape = self.powder_shape_var.get().strip().lower()
        if shape not in set(POWDER_SHAPE_PRESETS):
            raise ValueError(f"不支持的粉末形状: {self.powder_shape_var.get()}")
        seed_text = self.seed_var.get().strip()
        seed = int(seed_text) if seed_text else None
        return NanopowderConfig(particle_size=size, particle_count=count, shape=shape, seed=seed)

    def _refresh_nanopowder_preview(self) -> None:
        if not self._modeling_preview_widgets_ready():
            return
        try:
            config = self._nanopowder_config()
            structure, particles, box = build_nanopowder_structure(config)
        except Exception as exc:
            self.modeling_preview_title.configure(text="纳米粉末预览")
            self.modeling_detail_title.configure(text="提示")
            self.modeling_preview_summary.configure(text=f"预览失败: {exc}")
            self._configure_modeling_detail_tree(["提示"], [300])
            self.modeling_detail_tree.insert("", "end", values=(f"预览失败: {exc}",))
            self.modeling_preview_canvas.delete("all")
            self.modeling_preview_canvas.create_text(180, 110, text=f"预览失败: {exc}", fill=DANGER, font=("Microsoft YaHei UI", 10), anchor="center")
            return
        self.modeling_preview_title.configure(text=f"纳米粉末预览 · {config.shape}")
        self.modeling_detail_title.configure(text="颗粒布局")
        self._configure_modeling_detail_tree(["编号", "中心X", "中心Y", "中心Z", "形状", "原子数"], [70, 100, 100, 100, 100, 90])
        for particle in particles:
            self.modeling_detail_tree.insert(
                "",
                "end",
                values=(particle.index, f"{particle.center_x:.3f}", f"{particle.center_y:.3f}", f"{particle.center_z:.3f}", particle.shape, particle.atom_count),
            )
        summary_text = [
            f"粉末大小: {config.particle_size:.3f} Å",
            f"粉末个数: {config.particle_count}",
            f"形状: {config.shape}",
            f"容器尺寸: {box.width:.3f} x {box.height:.3f} x {box.depth:.3f} Å",
            f"总原子数: {len(structure.atoms)}",
        ]
        self.modeling_preview_summary.configure(text="\n".join(summary_text))
        self._render_powder_canvas(self.modeling_preview_canvas, particles, box)

    def _render_powder_canvas(self, canvas: tk.Canvas, particles: list[PowderParticle], box: BoxBounds) -> None:
        canvas.delete("all")
        canvas_width = int(canvas.winfo_width() or canvas.cget("width"))
        canvas_height = int(canvas.winfo_height() or canvas.cget("height"))
        canvas_width = max(canvas_width, 360)
        canvas_height = max(canvas_height, 220)
        canvas.config(width=canvas_width, height=canvas_height)
        canvas.create_rectangle(0, 0, canvas_width, canvas_height, fill="#f8fcff", outline=BORDER)
        if not particles or box.width <= 0 or box.height <= 0:
            canvas.create_text(canvas_width / 2, canvas_height / 2, text="纳米粉末预览等待有效参数", fill=MUTED, font=("Microsoft YaHei UI", 10))
            return
        padding = 14
        inner_w = max(1.0, canvas_width - 2 * padding)
        inner_h = max(1.0, canvas_height - 2 * padding)
        for particle in particles:
            cx = padding + (particle.center_x / box.width) * inner_w
            cy = padding + (particle.center_y / box.height) * inner_h
            red, green, blue = colorsys.hls_to_rgb(((particle.index - 1) * 0.61803398875) % 1.0, 0.62, 0.75)
            color = "#{:02x}{:02x}{:02x}".format(int(red * 255), int(green * 255), int(blue * 255))
            if particle.shape == "sphere":
                radius = 0.5 * particle.size / box.width * inner_w
                canvas.create_oval(cx - radius, cy - radius, cx + radius, cy + radius, outline=color, width=2)
            elif particle.shape == "cube":
                half = 0.5 * particle.size / box.width * inner_w
                canvas.create_rectangle(cx - half, cy - half, cx + half, cy + half, outline=color, width=2)
            elif particle.shape == "ellipsoid":
                axes_x = 0.5 * particle.size / box.width * inner_w
                axes_y = 0.36 * particle.size / box.height * inner_h
                canvas.create_oval(cx - axes_x, cy - axes_y, cx + axes_x, cy + axes_y, outline=color, width=2)
            elif particle.shape == "cylinder":
                radius = 0.5 * particle.size / box.width * inner_w
                canvas.create_oval(cx - radius, cy - radius, cx + radius, cy + radius, outline=color, width=2)
            elif particle.shape == "octahedron":
                radius_x = 0.5 * particle.size / box.width * inner_w
                radius_y = 0.5 * particle.size / box.height * inner_h
                canvas.create_polygon(
                    cx,
                    cy - radius_y,
                    cx + radius_x,
                    cy,
                    cx,
                    cy + radius_y,
                    cx - radius_x,
                    cy,
                    outline=color,
                    fill="",
                    width=2,
                )
            else:
                radius = 0.5 * particle.size / box.width * inner_w
                canvas.create_oval(cx - radius, cy - radius, cx + radius, cy + radius, outline=color, width=2)
            canvas.create_oval(cx - 2, cy - 2, cx + 2, cy + 2, fill="#17324a", outline="#17324a")
        canvas.create_text(16, 12, text=f"颗粒数 {len(particles)}", fill=TEXT, anchor="w", font=("Microsoft YaHei UI", 9, "bold"))

    def _generate_nanopowder(self) -> None:
        try:
            config = self._nanopowder_config()
            base_output = WORK_DIR / "nanopowder" / "base.lmp"
            final_output = WORK_DIR / "nanopowder" / "final.lmp"
            structure, particles, box = build_nanopowder_structure(config)
            base_output.parent.mkdir(parents=True, exist_ok=True)
            write_lammps_structure(base_output, structure, structure.atoms, atom_types_count=1)
            self._invalidate_structure_cache()
            if self.inherit_previous_var.get():
                result = self._assign_alloy(base_output, final_output)
                final_path = result.final_path
            else:
                write_lammps_structure(final_output, structure, structure.atoms, atom_types_count=1)
                self._invalidate_structure_cache()
                final_path = final_output
            self.source_path_var.set(str(final_path))
            self.lammps_data_file_var.set(str(final_path))
            self._load_source_info()
            self._refresh_all()
            self._refresh_modeling_previews()
            self._set_status("纳米粉末已生成", SUCCESS)
            inherit_note = "已继承当前配方/掺杂" if self.inherit_previous_var.get() else "未继承配方/掺杂"
            self._log(f"纳米粉末已生成: {final_path}; 颗粒数 {len(particles)}; 总原子数 {len(structure.atoms)}; 容器 {box.width:.3f} x {box.height:.3f} x {box.depth:.3f} Å; {inherit_note}")
        except Exception as exc:
            messagebox.showerror("生成粉末失败", str(exc))
            self._log(f"生成纳米粉末失败: {exc}")

    def _single_crystal_config(self) -> SingleCrystalConfig:
        length = parse_float(self.single_length_var.get(), "单晶长度")
        width = parse_float(self.single_width_var.get(), "单晶宽度")
        height = parse_float(self.single_height_var.get(), "单晶高度")
        if length <= 0 or width <= 0 or height <= 0:
            raise ValueError("单晶长宽高必须大于 0")
        orientation = self.single_orientation_var.get().strip().lower()
        defect_mode = self.single_defect_var.get().strip().lower()
        if orientation not in SINGLE_CRYSTAL_ORIENTATIONS:
            raise ValueError("单晶晶面取向只支持 100、110、111")
        if defect_mode not in SINGLE_CRYSTAL_DEFECT_MODES:
            raise ValueError("单晶缺陷类型无效")
        defect_angle = parse_float(self.single_defect_angle_var.get(), "缺陷角度")
        defect_core_radius = parse_float(self.single_defect_core_var.get(), "核半径")
        if defect_angle < 0:
            raise ValueError("缺陷角度不能小于 0")
        if defect_core_radius <= 0:
            raise ValueError("核半径必须大于 0")
        seed_text = self.seed_var.get().strip()
        seed = int(seed_text) if seed_text else None
        return SingleCrystalConfig(
            length=length,
            width=width,
            height=height,
            orientation=orientation,
            defect_mode=defect_mode,
            defect_angle=defect_angle,
            defect_core_radius=defect_core_radius,
            seed=seed,
        )

    def _refresh_single_crystal_preview(self) -> None:
        if not self._modeling_preview_widgets_ready():
            return
        try:
            config = self._single_crystal_config()
            structure, summary, box = build_single_crystal_structure(config)
        except Exception as exc:
            self.modeling_preview_title.configure(text="单晶预览")
            self.modeling_detail_title.configure(text="提示")
            self.modeling_preview_summary.configure(text=f"预览失败: {exc}")
            self._configure_modeling_detail_tree(["提示"], [300])
            self.modeling_detail_tree.insert("", "end", values=(f"预览失败: {exc}",))
            self.modeling_preview_canvas.delete("all")
            self.modeling_preview_canvas.create_text(180, 110, text=f"预览失败: {exc}", fill=DANGER, font=("Microsoft YaHei UI", 10), anchor="center")
            return
        self.modeling_preview_title.configure(text=f"单晶预览 · {single_crystal_orientation_label(config.orientation)}")
        self.modeling_detail_title.configure(text="晶向与缺陷")
        self._configure_modeling_detail_tree(["项目", "值"], [160, 260])
        for label, value in [
            ("晶向", single_crystal_orientation_label(config.orientation)),
            ("缺陷", single_crystal_defect_label(config.defect_mode)),
            ("缺陷角度", f"{config.defect_angle:.3f}°"),
            ("核半径", f"{config.defect_core_radius:.3f} Å"),
            ("原子数", f"{len(structure.atoms)}"),
            ("盒子", f"{box.width:.3f} x {box.height:.3f} x {box.depth:.3f} Å"),
        ]:
            self.modeling_detail_tree.insert("", "end", values=(label, value))
        self.modeling_preview_summary.configure(text="\n".join(summary))
        self._render_single_crystal_canvas(self.modeling_preview_canvas, structure.atoms, box, config.defect_mode)

    def _render_single_crystal_canvas(self, canvas: tk.Canvas, atoms: list[AtomRecord], box: BoxBounds, defect_mode: str) -> None:
        canvas.delete("all")
        canvas_width = int(canvas.winfo_width() or canvas.cget("width"))
        canvas_height = int(canvas.winfo_height() or canvas.cget("height"))
        canvas_width = max(canvas_width, 420)
        canvas_height = max(canvas_height, 280)
        canvas.config(width=canvas_width, height=canvas_height)
        canvas.create_rectangle(0, 0, canvas_width, canvas_height, fill="#f8fcff", outline=BORDER)
        if not atoms or box.width <= 0 or box.height <= 0:
            canvas.create_text(canvas_width / 2, canvas_height / 2, text="单晶预览等待有效参数", fill=MUTED, font=("Microsoft YaHei UI", 10))
            return
        padding = 16
        inner_w = max(1.0, canvas_width - 2 * padding)
        inner_h = max(1.0, canvas_height - 2 * padding)
        sample_limit = 4500
        if len(atoms) > sample_limit:
            step = max(1, len(atoms) // sample_limit)
            atoms_to_draw = atoms[::step]
        else:
            atoms_to_draw = atoms
        center_x = 0.5 * (box.xlo + box.xhi)
        center_y = 0.5 * (box.ylo + box.yhi)
        for atom in atoms_to_draw:
            px = padding + ((atom.x - box.xlo) / max(box.width, 1e-9)) * inner_w
            py = padding + ((atom.y - box.ylo) / max(box.height, 1e-9)) * inner_h
            if defect_mode == "grain_boundary":
                hue = 0.08 if atom.x < center_x else 0.58
            elif defect_mode in {"edge_dislocation", "screw_dislocation"}:
                hue = (((atom.z - box.zlo) / max(box.depth, 1e-9)) * 0.7 + 0.1) % 1.0
            else:
                hue = (((atom.z - box.zlo) / max(box.depth, 1e-9)) * 0.7) % 1.0
            red, green, blue = colorsys.hls_to_rgb(hue, 0.62, 0.74)
            color = "#{:02x}{:02x}{:02x}".format(int(red * 255), int(green * 255), int(blue * 255))
            canvas.create_oval(px - 2, py - 2, px + 2, py + 2, fill=color, outline=color)
        if defect_mode == "grain_boundary":
            boundary_x = padding + 0.5 * inner_w
            canvas.create_line(boundary_x, padding, boundary_x, canvas_height - padding, fill="#3b6f95", width=2, dash=(5, 3))
            canvas.create_text(boundary_x + 12, padding + 10, text="晶界", fill="#3b6f95", anchor="w", font=("Microsoft YaHei UI", 9, "bold"))
        elif defect_mode in {"edge_dislocation", "screw_dislocation"}:
            core_x = padding + 0.5 * inner_w
            core_y = padding + 0.5 * inner_h
            canvas.create_oval(core_x - 6, core_y - 6, core_x + 6, core_y + 6, outline="#c05b2f", width=2)
            canvas.create_text(core_x + 10, core_y + 8, text="位错核", fill="#c05b2f", anchor="w", font=("Microsoft YaHei UI", 9, "bold"))
        canvas.create_text(16, 12, text=f"显示原子 {len(atoms_to_draw)} / {len(atoms)}", fill=TEXT, anchor="w", font=("Microsoft YaHei UI", 9, "bold"))

    def _generate_single_crystal(self) -> None:
        try:
            config = self._single_crystal_config()
            base_output = WORK_DIR / "single_crystal" / "base.lmp"
            final_output = WORK_DIR / "single_crystal" / "final.lmp"
            structure, summary, box = build_single_crystal_structure(config)
            base_output.parent.mkdir(parents=True, exist_ok=True)
            write_lammps_structure(base_output, structure, structure.atoms, atom_types_count=1)
            self._invalidate_structure_cache()
            if self.inherit_previous_var.get():
                result = self._assign_alloy(base_output, final_output)
                final_path = result.final_path
            else:
                write_lammps_structure(final_output, structure, structure.atoms, atom_types_count=1)
                self._invalidate_structure_cache()
                final_path = final_output
            self.source_path_var.set(str(final_path))
            self.lammps_data_file_var.set(str(final_path))
            self._load_source_info()
            self._refresh_all()
            self._refresh_modeling_previews()
            self._set_status("单晶已生成", SUCCESS)
            inherit_note = "已继承当前配方/掺杂" if self.inherit_previous_var.get() else "未继承配方/掺杂"
            self._log(
                f"单晶已生成: {final_path}; 晶向 {single_crystal_orientation_label(config.orientation)}; 缺陷 {single_crystal_defect_label(config.defect_mode)}; 原子数 {len(structure.atoms)}; 盒子 {box.width:.3f} x {box.height:.3f} x {box.depth:.3f} Å; {inherit_note}"
            )
        except Exception as exc:
            messagebox.showerror("生成单晶失败", str(exc))
            self._log(f"生成单晶失败: {exc}")

    def _refresh_modeling_previews(self) -> None:
        if not self._modeling_preview_widgets_ready():
            return
        mode = self._current_modeling_mode()
        if mode == "polycrystal":
            self._refresh_simple_polycrystal_preview()
        elif mode == "powder":
            self._refresh_nanopowder_preview()
        else:
            self._refresh_single_crystal_preview()

    def _build_crack_tab(self) -> None:
        cfg = ttk.LabelFrame(self.tab_crack, text="预裂纹设置", style="Section.TLabelframe", padding=12)
        cfg.pack(fill="x")
        ttk.Label(cfg, text="裂纹模式").grid(row=0, column=0, sticky="w")
        modes = [("无", "none"), ("中心裂纹", "center"), ("边缘裂纹", "edge")]
        for column, (label, value) in enumerate(modes, start=1):
            ttk.Radiobutton(cfg, text=label, value=value, variable=self.crack_mode_var, command=self._on_crack_mode_changed).grid(row=0, column=column, sticky="w", padx=(8, 0))
        ttk.Label(cfg, text="方向").grid(row=1, column=0, sticky="w", pady=(10, 0))
        ttk.Radiobutton(cfg, text="水平", value="horizontal", variable=self.crack_orientation_var, command=self._on_crack_orientation_changed).grid(row=1, column=1, sticky="w", padx=(8, 0), pady=(10, 0))
        ttk.Radiobutton(cfg, text="垂直", value="vertical", variable=self.crack_orientation_var, command=self._on_crack_orientation_changed).grid(row=1, column=2, sticky="w", padx=(8, 0), pady=(10, 0))
        
        ttk.Label(cfg, text="形状").grid(row=1, column=3, sticky="w", pady=(10, 0), padx=(8, 0))
        ttk.Radiobutton(cfg, text="矩形", value="rectangle", variable=self.crack_shape_var, command=self._on_crack_shape_changed).grid(row=1, column=4, sticky="w", padx=(8, 0), pady=(10, 0))
        ttk.Radiobutton(cfg, text="椭圆/圆", value="ellipse", variable=self.crack_shape_var, command=self._on_crack_shape_changed).grid(row=1, column=5, sticky="w", padx=(8, 0), pady=(10, 0))

        ttk.Label(cfg, text="边缘方向").grid(row=2, column=0, sticky="w", pady=(10, 0))
        self.edge_side_combo = ttk.Combobox(cfg, textvariable=self.crack_side_var, values=["left", "right"], width=12, state="readonly")
        self.edge_side_combo.grid(row=2, column=1, sticky="w", padx=(8, 0), pady=(10, 0))
        self.crack_length_label_var = tk.StringVar(value="裂纹长度 (Å)")
        ttk.Label(cfg, textvariable=self.crack_length_label_var).grid(row=2, column=2, sticky="w", pady=(10, 0))
        ttk.Entry(cfg, textvariable=self.crack_length_var, width=10).grid(row=2, column=3, sticky="w", padx=(8, 0), pady=(10, 0))
        self.crack_opening_label_var = tk.StringVar(value="开口宽度 (Å)")
        ttk.Label(cfg, textvariable=self.crack_opening_label_var).grid(row=2, column=4, sticky="w", pady=(10, 0))
        ttk.Entry(cfg, textvariable=self.crack_opening_var, width=10).grid(row=2, column=5, sticky="w", padx=(8, 0), pady=(10, 0))
        tk.Label(cfg, text="说明：中心/边缘裂纹支持矩形和椭圆/圆两种形状；椭圆模式下两项数值分别控制长轴和短轴，设成相同值就是圆。", bg=PANEL, fg=MUTED, font=("Microsoft YaHei UI", 9)).grid(row=3, column=0, columnspan=6, sticky="w", pady=(10, 0))

        preview = ttk.LabelFrame(self.tab_crack, text="裂纹预览", style="Section.TLabelframe", padding=12)
        preview.pack(fill="both", expand=True, pady=(12, 0))
        self.crack_canvas = tk.Canvas(preview, width=360, height=260, bg="white", highlightthickness=1, highlightbackground=BORDER)
        self.crack_canvas.pack(side="left", padx=(0, 16))
        self.crack_summary = tk.Label(preview, text="", bg=PANEL, fg=TEXT, justify="left", font=("Microsoft YaHei UI", 10), wraplength=520)
        self.crack_summary.pack(side="left", fill="both", expand=True)
        self._on_crack_shape_changed()

    def _build_output_tab(self) -> None:
        model_card = ttk.LabelFrame(self.tab_output, text="梯度输出模型库", style="Section.TLabelframe", padding=12)
        model_card.pack(fill="x")
        model_card.columnconfigure(1, weight=1)
        ttk.Label(model_card, text="模型模板").grid(row=0, column=0, sticky="w")
        self.model_library_combo = ttk.Combobox(
            model_card,
            textvariable=self.model_preset_var,
            values=self._model_library_values(),
            state="readonly",
        )
        self.model_library_combo.grid(row=0, column=1, sticky="ew", padx=(8, 8))
        self.model_library_combo.bind("<<ComboboxSelected>>", lambda _event: self._apply_model_library_selection())
        ttk.Button(model_card, text="载入模型", command=self._apply_model_library_selection).grid(row=0, column=2, sticky="w")
        tk.Label(
            model_card,
            textvariable=self.model_info_var,
            bg=PANEL,
            fg=MUTED,
            justify="left",
            wraplength=980,
            font=("Microsoft YaHei UI", 9),
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 0))

        cfg = ttk.LabelFrame(self.tab_output, text="输入与输出路径", style="Section.TLabelframe", padding=12)
        cfg.pack(fill="x", pady=(12, 0))
        cfg.columnconfigure(1, weight=1)
        cfg.columnconfigure(4, weight=1)
        ttk.Label(cfg, text="Atomsk 路径").grid(row=0, column=0, sticky="w")
        ttk.Entry(cfg, textvariable=self.atomsk_path_var).grid(row=0, column=1, sticky="ew", padx=(8, 8))
        ttk.Button(cfg, text="浏览", command=self._browse_atomsk).grid(row=0, column=2, sticky="w")
        ttk.Label(cfg, text="源文件").grid(row=0, column=3, sticky="e", padx=(18, 0))
        ttk.Entry(cfg, textvariable=self.source_path_var).grid(row=0, column=4, sticky="ew", padx=(8, 8))
        ttk.Button(cfg, text="浏览", command=self._browse_source).grid(row=0, column=5, sticky="w")
        ttk.Label(cfg, text="输出文件").grid(row=1, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(cfg, textvariable=self.output_path_var).grid(row=1, column=1, sticky="ew", padx=(8, 8), pady=(10, 0))
        ttk.Button(cfg, text="浏览", command=self._browse_output).grid(row=1, column=2, sticky="w", pady=(10, 0))
        ttk.Button(cfg, text="打开输出目录", command=self._open_output_dir).grid(row=1, column=5, sticky="e", pady=(10, 0))
        tk.Label(
            cfg,
            text="支持 .lmp / .data / .cfg / .xsf；选择 CFG 或 XSF 时，程序会先用 Atomsk 转成临时 LAMMPS 再继续后续流程。",
            bg=PANEL,
            fg=MUTED,
            font=("Microsoft YaHei UI", 9),
        ).grid(row=2, column=0, columnspan=6, sticky="w", pady=(8, 0))

        actions = ttk.LabelFrame(self.tab_output, text="流程输出", style="Section.TLabelframe", padding=12)
        actions.pack(fill="x", pady=(12, 0))
        ttk.Button(actions, text="仅生成几何", style="Accent.TButton", command=self._generate_geometry_only).pack(side="left")
        ttk.Button(actions, text="仅应用裂纹", command=self._apply_crack_only).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="仅生成合金", command=self._generate_alloy_only).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="一键生成全部", style="Accent.TButton", command=self._generate_full_pipeline).pack(side="right")

        info = ttk.LabelFrame(self.tab_output, text="当前梯度源文件信息", style="Section.TLabelframe", padding=12)
        info.pack(fill="both", expand=True, pady=(12, 0))
        self.source_summary_text = scrolledtext.ScrolledText(info, height=8, wrap="word", bg=PANEL, fg=TEXT, font=("Microsoft YaHei UI", 10), state="disabled", relief="flat")
        self.source_summary_text.pack(fill="both", expand=True)

    def _build_log_panel(self, parent: ttk.Frame) -> None:
        log_frame = ttk.LabelFrame(parent, text="日志", style="Section.TLabelframe", padding=12)
        log_frame.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        parent.rowconfigure(1, weight=0)
        self.log_box = scrolledtext.ScrolledText(log_frame, height=10, wrap="word", font=("Consolas", 10))
        self.log_box.pack(fill="both", expand=True)
        self.log_box.insert("end", "程序已启动。\n")
        for pending_text in self._pending_log_messages:
            self.log_box.insert("end", pending_text)
        self._pending_log_messages.clear()
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _composition_status_var(self) -> tk.StringVar:
        if not hasattr(self, "_composition_status"):
            self._composition_status = tk.StringVar(value="准备就绪")
        return self._composition_status

    def _set_status(self, text: str, color: str = TEXT) -> None:
        self._set_banner_status(text, color)
        self._composition_status_var().set(text)

    def _log(self, text: str) -> None:
        if not text.endswith("\n"):
            text += "\n"
        log_box = getattr(self, "log_box", None)
        if log_box is None:
            self._pending_log_messages.append(text)
            return
        try:
            log_box.configure(state="normal")
            log_box.insert("end", text)
            log_box.see("end")
            log_box.configure(state="disabled")
        except tk.TclError:
            self._pending_log_messages.append(text)

    def _schedule_refresh(self) -> None:
        if self._refresh_job is not None:
            try:
                self.after_cancel(self._refresh_job)
            except tk.TclError:
                pass
        self._refresh_scheduled = True
        self._refresh_job = self.after(140, self._refresh_all)

    def _refresh_all(self) -> None:
        self._refresh_scheduled = False
        self._refresh_job = None
        self._refresh_composition_preview()
        self._refresh_doping_preview()
        self._refresh_geometry_preview()
        self._refresh_crack_preview()
        self._refresh_source_summary()
        self._refresh_home_summary()

    def _geometry_preset_values(self) -> list[str]:
        return list(GEOMETRY_PRESETS.keys())

    def _geometry_preset_by_name(self, name: str) -> GeometryPreset | None:
        return GEOMETRY_PRESETS.get(name)
    def _parallel_worker_count(self) -> int:
        try:
            value = int(self.parallel_workers_var.get().strip())
        except ValueError:
            value = 1
        cpu_count = os.cpu_count() or 1
        return max(1, min(value, cpu_count))

    def _subprocess_env(self) -> dict[str, str]:
        return build_parallel_env(self._parallel_worker_count())

    def _apply_crystal_structure_defaults(self) -> None:
        try:
            structure = normalize_crystal_structure(self.crystal_structure_var.get())
        except ValueError as exc:
            messagebox.showerror("结构设置失败", str(exc))
            return
        lattice_parameter, hcp_c_over_a = crystal_structure_defaults(structure)
        self.lattice_param_var.set(f"{lattice_parameter:.3f}")
        if structure == "hcp" and hcp_c_over_a is not None:
            self.hcp_c_over_a_var.set(f"{hcp_c_over_a:.3f}")
        self._schedule_refresh()

    def _apply_geometry_preset(self, name: str, *, log: bool = True) -> None:
        preset = self._geometry_preset_by_name(name)
        if preset is None:
            messagebox.showerror("模板应用失败", f"找不到几何模板: {name}")
            return
        self.geometry_preset_var.set(name)
        self.model_width_var.set(f"{preset.width:g}")
        self.model_height_var.set(f"{preset.height:g}")
        self.first_layer_count_var.set(str(preset.first_layer_count))
        self.delta_var.set(str(preset.delta))
        self.layers_var.set(str(preset.layers))
        self.periodic_var.set(preset.periodic)
        self.boundary_padding_var.set(preset.boundary_padding)
        self.chaos_var.set(f"{preset.chaos:g}")
        self.layout_mode_var.set(preset.layout_mode)
        if preset.seed is None:
            self.seed_var.set("")
        else:
            self.seed_var.set(str(preset.seed))
        if preset.target_grain_size is None:
            self.target_grain_size_var.set("")
        else:
            self.target_grain_size_var.set(f"{preset.target_grain_size:g}")
        self._schedule_refresh()
        if log:
            self._log(f"已套用几何模板: {preset.name}")

    def _render_geometry_canvas(self, nodes: list[GrainNode], width: float, height: float) -> None:
        canvas = self.geometry_canvas
        canvas.delete("all")
        canvas_width = int(canvas.winfo_width() or canvas.cget("width"))
        canvas_height = int(canvas.winfo_height() or canvas.cget("height"))
        canvas_width = max(canvas_width, 360)
        canvas_height = max(canvas_height, 260)
        canvas.config(width=canvas_width, height=canvas_height)
        canvas.create_rectangle(0, 0, canvas_width, canvas_height, fill="#f8fcff", outline=BORDER)
        if not nodes or width <= 0 or height <= 0:
            canvas.create_text(canvas_width / 2, canvas_height / 2, text="几何预览等待有效参数", fill=MUTED, font=("Microsoft YaHei UI", 10))
            return
        padding = 14
        inner_w = max(1.0, canvas_width - 2 * padding)
        inner_h = max(1.0, canvas_height - 2 * padding)
        palette: list[str] = []
        for index, _node in enumerate(nodes):
            hue = (index * 0.61803398875) % 1.0
            red, green, blue = colorsys.hls_to_rgb(hue, 0.58, 0.82)
            palette.append("#{:02x}{:02x}{:02x}".format(int(red * 255), int(green * 255), int(blue * 255)))
        scaled_nodes = [
            (
                padding + (node.x / width) * inner_w,
                padding + (node.y / height) * inner_h,
            )
            for node in nodes
        ]
        cell_size = 8
        cols = max(1, int(inner_w / cell_size))
        rows = max(1, int(inner_h / cell_size))
        dx = inner_w / cols
        dy = inner_h / rows
        for row in range(rows):
            y = padding + (row + 0.5) * dy
            y0 = padding + row * dy
            y1 = y0 + dy + 1
            for col in range(cols):
                x = padding + (col + 0.5) * dx
                x0 = padding + col * dx
                x1 = x0 + dx + 1
                nearest_index = 0
                nearest_distance = float("inf")
                for index, (node_x, node_y) in enumerate(scaled_nodes):
                    distance = (node_x - x) ** 2 + (node_y - y) ** 2
                    if distance < nearest_distance:
                        nearest_distance = distance
                        nearest_index = index
                canvas.create_rectangle(x0, y0, x1, y1, outline="", fill=palette[nearest_index])
        for node_x, node_y in scaled_nodes:
            canvas.create_oval(node_x - 3, node_y - 3, node_x + 3, node_y + 3, fill="#111111", outline="#ffffff", width=1)
        canvas.create_text(16, 12, text=f"节点数 {len(nodes)}", fill=TEXT, anchor="w", font=("Microsoft YaHei UI", 9, "bold"))

    def _available_model_presets(self) -> list[ModelPreset]:
        return [preset for preset in MODEL_LIBRARY if preset.path.exists()]

    def _model_library_values(self) -> list[str]:
        return [preset.name for preset in self._available_model_presets()] + ["自定义源文件"]

    def _model_preset_by_name(self, name: str) -> ModelPreset | None:
        for preset in self._available_model_presets():
            if preset.name == name:
                return preset
        return None

    def _sync_model_library_selection(self) -> None:
        source_path = self._source_path()
        preset: ModelPreset | None = None
        if source_path.exists():
            try:
                resolved_source = source_path.resolve()
            except OSError:
                resolved_source = source_path
            for candidate in self._available_model_presets():
                try:
                    candidate_path = candidate.path.resolve()
                except OSError:
                    candidate_path = candidate.path
                if candidate_path == resolved_source:
                    preset = candidate
                    break
        if preset is None:
            self.model_preset_var.set("自定义源文件")
            self.model_info_var.set(
                f"自定义源文件：{source_path}。如果是 CFG 或 XSF，程序会先用 Atomsk 转成临时 LAMMPS。"
            )
            return
        self.model_preset_var.set(preset.name)
        self.model_info_var.set(f"{preset.name}：{preset.basis}。{preset.description} 源文件：{preset.path}")

    def _apply_model_library_selection(self) -> None:
        name = self.model_preset_var.get()
        if name == "自定义源文件":
            self.model_info_var.set("自定义源文件：请在“源文件”里浏览你的结构；CFG/XSF 会自动转成临时 LAMMPS。")
            return
        preset = self._model_preset_by_name(name)
        if preset is None:
            messagebox.showerror("模型加载失败", f"找不到模型模板: {name}")
            return
        self.source_path_var.set(str(preset.path))
        if self._sync_geometry_from_source():
            self._log(f"已加载模型模板: {preset.name}")

    def _selected_entries(self) -> list[CompositionEntry]:
        entries: list[CompositionEntry] = []
        for row in self.composition_rows:
            row.update_color()
            symbol = normalize_symbol(row.symbol_var.get())
            if not symbol:
                continue
            entry = row.get_entry()
            if entry is not None:
                entries.append(entry)
        return entries

    def _fill_rows_from_entries(self, entries: list[CompositionEntry]) -> None:
        for row in self.composition_rows:
            row.clear()
        for row, entry in zip(self.composition_rows, entries):
            row.load_entry(entry)
        self._refresh_composition_preview()

    def _doping_preset_values(self) -> list[str]:
        return [DOPING_PRESET_PLACEHOLDER, *DOPING_PRESETS.keys()]

    def _doping_preset_by_name(self, name: str) -> list[DopingEntry] | None:
        return DOPING_PRESETS.get(name)

    def _selected_doping_entries(self, *, strict: bool = True) -> list[DopingEntry]:
        entries: list[DopingEntry] = []
        for row in self.doping_rows:
            row.update_color()
            if row.is_blank():
                continue
            amount_text = row.amount_var.get().strip()
            symbol_text = row.symbol_var.get().strip()
            operation_text = normalize_doping_operation(row.operation_var.get())
            if not strict and (not amount_text or (operation_text != "vacancy" and not symbol_text)):
                continue
            try:
                entry = row.get_entry()
            except Exception as exc:
                if strict:
                    raise
                self._doping_status.set(str(exc))
                return []
            if entry is not None:
                entries.append(entry)
        return entries

    def _fill_doping_rows_from_entries(self, entries: list[DopingEntry]) -> None:
        for row in self.doping_rows:
            row.clear()
        for row, entry in zip(self.doping_rows, entries):
            row.load_entry(entry)
        self._refresh_doping_preview()

    def _clear_doping_row(self, index: int) -> None:
        self.doping_rows[index].clear()
        self._refresh_all()

    def _clear_all_doping(self) -> None:
        for row in self.doping_rows:
            row.clear()
        self.doping_preset_var.set(DOPING_PRESET_PLACEHOLDER)
        self.doping_enabled_var.set(False)
        self._refresh_all()

    def _apply_doping_preset(self, name: str) -> None:
        if not name or name == DOPING_PRESET_PLACEHOLDER:
            self._doping_status.set("请选择一个掺杂模板")
            return
        entries = self._doping_preset_by_name(name)
        if entries is None:
            messagebox.showerror("模板应用失败", f"找不到掺杂模板: {name}")
            return
        self.doping_preset_var.set(name)
        self.doping_enabled_var.set(True)
        self._fill_doping_rows_from_entries(entries)
        self._log(f"已加载掺杂模板: {name}")

    def _sort_doping_rows(self, mode: str) -> None:
        try:
            entries = self._selected_doping_entries()
            if not entries:
                return
            if mode == "element":
                entries = sorted(entries, key=lambda item: element_number(item.symbol) if item.symbol else 0)
            elif mode == "region":
                entries = sorted(entries, key=lambda item: (item.region, item.operation, item.symbol))
            else:
                entries = sorted(entries, key=lambda item: (item.operation, item.symbol))
            self._fill_doping_rows_from_entries(entries)
            self._log(f"已按 {mode} 排序掺杂方案。")
        except Exception as exc:
            messagebox.showerror("排序失败", str(exc))
        self._refresh_all()

    def _estimate_doping_change(self, structure: LammpsStructure, entry: DopingEntry) -> str:
        operation = normalize_doping_operation(entry.operation)
        region = normalize_doping_region(entry.region)
        amount_mode = normalize_doping_amount_mode(entry.amount_mode)
        region_indices = select_doping_region_indices(structure.atoms, structure.box, region, entry.control)
        if not region_indices:
            return "0"
        target_count = resolve_doping_target_count(entry.amount, amount_mode, len(region_indices))
        if operation == "vacancy":
            return f"-{min(target_count, len(region_indices))}"
        if operation == "substitution":
            return f"≈{min(target_count, len(region_indices))}"
        if operation in {"adsorption", "interstitial"}:
            return f"+{target_count}"
        return "0"

    def _refresh_doping_preview(self) -> None:
        for item in self.doping_tree.get_children():
            self.doping_tree.delete(item)
        has_rows = any(not row.is_blank() for row in self.doping_rows)
        if not has_rows:
            self._doping_status.set("当前未设置掺杂")
            return
        previous_status = self._doping_status.get()
        try:
            entries = self._selected_doping_entries(strict=False)
            if not entries:
                if self._doping_status.get() == previous_status:
                    self._doping_status.set("掺杂行未填写完整")
                return
            structure, _resolved_path = self._structure_for_path(self._source_path())
        except Exception as exc:
            self._doping_status.set(f"掺杂预览失败: {exc}")
            return

        for entry in entries:
            symbol = entry.symbol if entry.symbol else "空位"
            operation = DOPING_OPERATION_LABELS.get(entry.operation, entry.operation)
            region = DOPING_REGION_LABELS.get(entry.region, entry.region)
            amount_mode = DOPING_AMOUNT_LABELS.get(entry.amount_mode, entry.amount_mode)
            predicted = self._estimate_doping_change(structure, entry)
            self.doping_tree.insert(
                "",
                "end",
                values=(symbol, operation, region, f"{entry.amount:g}", amount_mode, f"{entry.control:g}", predicted),
                tags=(entry.symbol or "vacancy",),
            )
            if entry.symbol:
                color = element_color(entry.symbol)
                foreground = choose_foreground(color)
                self.doping_tree.tag_configure(entry.symbol, background=color, foreground=foreground)

        current_atoms = len(structure.atoms)
        enabled = "启用" if self.doping_enabled_var.get() else "未启用"
        self._doping_status.set(f"已设置 {len(entries)} 条掺杂方案，当前{enabled}掺杂，源文件原子数 {current_atoms}")

    def _clear_composition_row(self, index: int) -> None:
        self.composition_rows[index].clear()
        self._refresh_all()

    def _clear_all_composition(self) -> None:
        for row in self.composition_rows:
            row.clear()
        self._refresh_all()

    def _apply_recipe_text(self, recipe_text: str) -> None:
        self.recipe_var.set(recipe_text)
        self._parse_recipe_to_rows()

    def _parse_recipe_to_rows(self) -> None:
        try:
            entries = parse_recipe_text(self.recipe_var.get())
            if not entries:
                raise ValueError("配方不能为空")
        except Exception as exc:
            messagebox.showerror("配方解析失败", str(exc))
            self._log(f"配方解析失败: {exc}")
            return
        self._fill_rows_from_entries(entries)
        self._log(f"已解析配方: {format_formula(entries)}")
        self._refresh_all()

    def _sort_composition(self, mode: str) -> None:
        try:
            entries = self._selected_entries()
            if not entries:
                return
            if mode == "weight":
                entries = sorted(entries, key=lambda item: item.weight, reverse=True)
            elif mode == "element":
                entries = sorted(entries, key=lambda item: element_number(item.symbol))
            else:
                entries = sorted(entries, key=lambda item: item.symbol)
            self._fill_rows_from_entries(entries)
            self.recipe_var.set(format_formula(entries))
            self._log(f"已按 {mode} 排序配方。")
        except Exception as exc:
            messagebox.showerror("排序失败", str(exc))
        self._refresh_all()

    def _refresh_composition_preview(self) -> None:
        for item in self.composition_tree.get_children():
            self.composition_tree.delete(item)
        entries = self._selected_entries()
        if not entries:
            self._composition_status_var().set("当前未填写配方")
            return
        normalized = normalize_entries(entries)
        try:
            current_atoms = self._current_atom_count()
        except Exception:
            current_atoms = None
        counts = []
        if current_atoms is not None:
            counts = largest_remainder_counts([entry.weight for entry in normalized], current_atoms)
        else:
            counts = [0 for _ in normalized]
        for entry, normalized_entry, count in zip(entries, normalized, counts):
            mass_text = f"{entry.mass:.8f}" if entry.mass is not None else "自填"
            preview = f"{normalized_entry.weight * 100:.4f}"
            count_text = str(count) if current_atoms is not None else "-"
            self.composition_tree.insert("", "end", values=(entry.symbol, f"{entry.weight:g}", preview, count_text, mass_text), tags=(entry.symbol,))
            color = element_color(entry.symbol)
            foreground = choose_foreground(color)
            self.composition_tree.tag_configure(entry.symbol, background=color, foreground=foreground)
        if current_atoms is not None:
            self._composition_status_var().set(f"配方已填入 {len(entries)} 个元素，当前源文件共有 {current_atoms} 个原子")
        else:
            self._composition_status_var().set(f"配方已填入 {len(entries)} 个元素")
        self.recipe_var.set(format_formula(entries))

    def _geometry_config(self) -> GeometryConfig:
        atomsk_path = find_atomsk_exe(self.atomsk_path_var.get())
        width = parse_float(self.model_width_var.get(), "模型宽度")
        height = parse_float(self.model_height_var.get(), "模型高度")
        lattice = parse_float(self.lattice_param_var.get(), "种晶晶格常数")
        first_count = parse_int(self.first_layer_count_var.get(), "第一层晶粒数")
        target_size = parse_optional_float(self.target_grain_size_var.get())
        delta = parse_int(self.delta_var.get(), "层间变化")
        layers = parse_int(self.layers_var.get(), "层数")
        chaos = parse_float(self.chaos_var.get(), "随机扰动")
        if width <= 0 or height <= 0:
            raise ValueError("模型宽度和高度必须大于 0")
        if lattice <= 0:
            raise ValueError("晶格常数必须大于 0")
        if layers <= 0:
            raise ValueError("层数必须大于 0")
        if chaos < 0:
            raise ValueError("随机扰动不能小于 0")
        seed_text = self.seed_var.get().strip()
        seed = int(seed_text) if seed_text else None
        crystal_structure = normalize_crystal_structure(self.crystal_structure_var.get())
        hcp_c_over_a = parse_optional_float(self.hcp_c_over_a_var.get()) if crystal_structure == "hcp" else None
        return GeometryConfig(
            atomsk_path=atomsk_path,
            width=width,
            height=height,
            crystal_structure=crystal_structure,
            lattice_parameter=lattice,
            hcp_c_over_a=hcp_c_over_a if hcp_c_over_a is not None else (DEFAULT_HCP_C_OVER_A if crystal_structure == "hcp" else None),
            first_layer_count=first_count,
            target_grain_size=target_size,
            delta=delta,
            layers=layers,
            periodic=self.periodic_var.get(),
            boundary_padding=self.boundary_padding_var.get(),
            chaos=chaos,
            seed=seed,
            layout_mode=self.layout_mode_var.get(),
        )

    def _geometry_preview(self) -> tuple[str, list[GeometryLayerPreview], int, float]:
        config = self._geometry_config()
        text, previews, node_count, height = generate_gradient_text(config)
        return text, previews, node_count, height

    def _geometry_layout(self) -> tuple[list[GrainNode], list[GeometryLayerPreview], int, float]:
        config = self._geometry_config()
        return build_geometry_layout(config)

    def _geometry_summary_lines(self, previews: list[GeometryLayerPreview], nodes: list[GrainNode], node_count: int, height: float) -> list[str]:
        first_count = derive_first_layer_count(
            parse_float(self.model_width_var.get(), "模型宽度"),
            parse_int(self.first_layer_count_var.get(), "第一层晶粒数"),
            parse_optional_float(self.target_grain_size_var.get()),
        )
        grain_sizes = [preview.grain_size for preview in previews]
        x_values = [node.x for node in nodes]
        y_values = [node.y for node in nodes]
        summary_text = [
            f"第一层晶粒数: {first_count}",
            f"层数: {len(previews)}",
            f"总节点数: {node_count}",
            f"目标高度: {height:.3f} Å",
            f"排布方式: {'六角错位' if self.layout_mode_var.get() == 'hexagonal' else '分层直列'}",
            f"周期结构: {'是' if self.periodic_var.get() else '否'}",
            f"边界补点: {'是' if self.boundary_padding_var.get() else '否'}",
            f"随机扰动: {self.chaos_var.get()}",
        ]
        if grain_sizes:
            summary_text.extend(
                [
                    f"晶粒尺寸范围: {min(grain_sizes):.3f} ~ {max(grain_sizes):.3f} Å",
                    f"平均晶粒尺寸: {sum(grain_sizes) / len(grain_sizes):.3f} Å",
                ]
            )
        if x_values and y_values:
            summary_text.extend(
                [
                    f"节点范围 X: {min(x_values):.3f} ~ {max(x_values):.3f} Å",
                    f"节点范围 Y: {min(y_values):.3f} ~ {max(y_values):.3f} Å",
                ]
            )
        return summary_text

    def _geometry_report_text(self, previews: list[GeometryLayerPreview], nodes: list[GrainNode], node_count: int, height: float) -> str:
        lines = [
            "几何研究报告",
            f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            *self._geometry_summary_lines(previews, nodes, node_count, height),
            "",
            "层级数据:",
            "层\t晶粒数\t晶粒尺寸(Å)\t中心Y(Å)",
        ]
        for preview in previews:
            lines.append(f"{preview.layer}\t{preview.grains}\t{preview.grain_size:.6f}\t{preview.center_y:.6f}")
        lines.extend([
            "",
            "节点数据:",
            "序号\t层\tX(Å)\tY(Å)",
        ])
        for index, node in enumerate(nodes, start=1):
            lines.append(f"{index}\t{node.layer}\t{node.x:.6f}\t{node.y:.6f}")
        return "\n".join(lines) + "\n"

    def _geometry_export_dir(self) -> Path:
        export_dir = WORK_DIR / "research_exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        return export_dir

    def _copy_geometry_summary(self) -> None:
        try:
            nodes, previews, node_count, height = self._geometry_layout()
            summary_text = "\n".join(self._geometry_summary_lines(previews, nodes, node_count, height))
        except Exception as exc:
            messagebox.showerror("复制失败", str(exc))
            self._log(f"复制几何摘要失败: {exc}")
            return
        self.clipboard_clear()
        self.clipboard_append(summary_text)
        try:
            self.update()
        except tk.TclError:
            pass
        self._log("已复制几何摘要到剪贴板。")

    def _export_geometry_nodes_csv(self) -> None:
        try:
            nodes, previews, node_count, height = self._geometry_layout()
        except Exception as exc:
            messagebox.showerror("导出失败", str(exc))
            self._log(f"导出节点CSV失败: {exc}")
            return
        export_dir = self._geometry_export_dir()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = export_dir / f"geometry_nodes_{timestamp}.csv"
        with output_path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(["index", "layer", "x_angstrom", "y_angstrom"])
            for index, node in enumerate(nodes, start=1):
                writer.writerow([index, node.layer, f"{node.x:.6f}", f"{node.y:.6f}"])
        self._log(f"已导出几何节点CSV: {output_path}")
        self._set_status("几何节点CSV已导出", SUCCESS)

    def _export_geometry_report(self) -> None:
        try:
            nodes, previews, node_count, height = self._geometry_layout()
        except Exception as exc:
            messagebox.showerror("导出失败", str(exc))
            self._log(f"导出研究报告失败: {exc}")
            return
        export_dir = self._geometry_export_dir()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = export_dir / f"geometry_report_{timestamp}.txt"
        output_path.write_text(self._geometry_report_text(previews, nodes, node_count, height), encoding="utf-8")
        self._log(f"已导出几何研究报告: {output_path}")
        self._set_status("几何研究报告已导出", SUCCESS)

    def _refresh_geometry_preview(self) -> None:
        for item in self.geometry_preview_tree.get_children():
            self.geometry_preview_tree.delete(item)
        try:
            nodes, previews, node_count, height = self._geometry_layout()
        except Exception as exc:
            self.geometry_summary.configure(text=f"预览失败: {exc}")
            self.geometry_canvas.delete("all")
            self.geometry_canvas.create_text(180, 120, text=f"预览失败: {exc}", fill=DANGER, font=("Microsoft YaHei UI", 10), anchor="center")
            return
        for preview in previews:
            self.geometry_preview_tree.insert(
                "",
                "end",
                values=(preview.layer, preview.grains, f"{preview.grain_size:.3f}", f"{preview.center_y:.3f}"),
            )
        summary_text = self._geometry_summary_lines(previews, nodes, node_count, height)
        summary_text.append("")
        summary_text.append("每层的晶粒数和尺寸会在左侧表格中显示。")
        self.geometry_summary.configure(text="\n".join(summary_text))
        self.current_geometry_preview = previews
        self.current_geometry_nodes = nodes
        self.current_geometry_node_count = node_count
        self.current_geometry_height = height
        self._render_geometry_canvas(nodes, parse_float(self.model_width_var.get(), "模型宽度"), height)

    def _stabilize_geometry_preview_layout(self, preview_content: ttk.Panedwindow) -> None:
        if not preview_content.winfo_exists():
            return
        width = preview_content.winfo_width()
        if width < 800:
            preview_content.after(60, lambda: self._stabilize_geometry_preview_layout(preview_content))
            return
        target = max(360, min(width - 480, int(width * 0.38)))
        try:
            preview_content.sashpos(0, target)
            preview_content.after_idle(self._refresh_geometry_preview)
        except tk.TclError:
            pass

    def _stabilize_geometry_tab_layout(self, geometry_split: ttk.Panedwindow) -> None:
        if not geometry_split.winfo_exists():
            return
        width = geometry_split.winfo_width()
        if width < 900:
            geometry_split.after(60, lambda: self._stabilize_geometry_tab_layout(geometry_split))
            return
        target = max(320, min(width - 560, int(width * 0.36)))
        try:
            geometry_split.sashpos(0, target)
            geometry_split.after_idle(self._refresh_geometry_preview)
        except tk.TclError:
            pass

    def _on_crack_mode_changed(self) -> None:
        self._update_edge_side_options()
        self._refresh_crack_preview()

    def _on_crack_orientation_changed(self) -> None:
        self._update_edge_side_options()
        self._refresh_crack_preview()

    def _on_crack_shape_changed(self) -> None:
        if self.crack_shape_var.get() == "ellipse":
            self.crack_length_label_var.set("椭圆长轴 (Å)")
            self.crack_opening_label_var.set("椭圆短轴 (Å)")
        else:
            self.crack_length_label_var.set("裂纹长度 (Å)")
            self.crack_opening_label_var.set("开口宽度 (Å)")
        self._refresh_crack_preview()

    def _update_edge_side_options(self) -> None:
        orientation = self.crack_orientation_var.get()
        if orientation == "horizontal":
            values = ["left", "right"]
            if self.crack_side_var.get() not in values:
                self.crack_side_var.set("left")
        else:
            values = ["bottom", "top"]
            if self.crack_side_var.get() not in values:
                self.crack_side_var.set("left" if self.crack_side_var.get() in {"left", "right"} else "bottom")
        self.edge_side_combo.configure(values=values)
        if self.crack_side_var.get() not in values:
            self.crack_side_var.set(values[0])

    def _crack_config(self) -> CrackConfig:
        return CrackConfig(
            mode=self.crack_mode_var.get(),
            shape=self.crack_shape_var.get(),
            orientation=self.crack_orientation_var.get(),
            edge_side=self.crack_side_var.get(),
            length=parse_float(self.crack_length_var.get(), "裂纹长度"),
            opening=parse_float(self.crack_opening_var.get(), "裂纹开口宽度"),
        )

    def _refresh_crack_preview(self) -> None:
        self.crack_canvas.delete("all")
        self.crack_canvas.create_rectangle(24, 24, 336, 236, outline=BORDER, width=2)
        try:
            config = self._crack_config()
        except Exception as exc:
            self.crack_summary.configure(text=f"裂纹参数无效: {exc}")
            return
        mode = config.mode
        if mode == "none":
            self.crack_summary.configure(text="当前未启用裂纹。可以选择中心裂纹或边缘裂纹，并调整长度与开口宽度。")
            return
        is_ellipse = config.shape == "ellipse"
        shape_label = "椭圆/圆" if is_ellipse else "矩形"
        orientation = config.orientation
        if orientation == "horizontal":
            x0, x1 = 96, 264
            y_center = 130
            if config.mode == "edge":
                if config.edge_side == "left":
                    x0, x1 = 24, 126
                else:
                    x0, x1 = 234, 336
            y0, y1 = y_center - 16, y_center + 16
            if is_ellipse:
                self.crack_canvas.create_oval(x0, y0, x1, y1, fill="#e11d48", outline="#991b1b")
            else:
                self.crack_canvas.create_rectangle(x0, y0, x1, y1, fill="#e11d48", outline="#991b1b")
            self.crack_canvas.create_text(180, 252, text=f"水平{shape_label}示意", fill=TEXT)
        else:
            y0, y1 = 96, 164
            x_center = 180
            if config.mode == "edge":
                if config.edge_side == "bottom":
                    y0, y1 = 24, 126
                else:
                    y0, y1 = 134, 236
            x0, x1 = x_center - 16, x_center + 16
            if is_ellipse:
                self.crack_canvas.create_oval(x0, y0, x1, y1, fill="#e11d48", outline="#991b1b")
            else:
                self.crack_canvas.create_rectangle(x0, y0, x1, y1, fill="#e11d48", outline="#991b1b")
            self.crack_canvas.create_text(180, 252, text=f"垂直{shape_label}示意", fill=TEXT)
        if mode == "center":
            title = "中心裂纹"
        else:
            title = f"边缘裂纹 ({config.edge_side})"
        size_text = (
            f"椭圆长轴: {config.length:g} Å\n"
            f"椭圆短轴: {config.opening:g} Å\n"
        ) if is_ellipse else (
            f"裂纹长度: {config.length:g} Å\n"
            f"裂纹开口宽度: {config.opening:g} Å\n"
        )
        self.crack_summary.configure(
            text=(
                f"裂纹类型: {title}\n"
                f"裂纹形状: {shape_label}\n"
                f"方向: {'水平' if orientation == 'horizontal' else '垂直'}\n"
                f"{size_text}"
                f"说明: 这里生成的是几何预裂纹，会直接删除裂纹区域内的原子。"
            )
        )

    def _source_path(self) -> Path:
        return Path(self.source_path_var.get()).expanduser()

    def _output_path(self) -> Path:
        return Path(self.output_path_var.get()).expanduser()

    def _browse_source(self) -> None:
        selected = filedialog.askopenfilename(
            title="选择源 LAMMPS 文件",
            initialdir=str(ROOT),
            filetypes=[("结构文件", "*.lmp *.data *.cfg *.xsf"), ("LAMMPS data", "*.lmp *.data"), ("Atomsk 文件", "*.cfg *.xsf"), ("All files", "*.*")],
        )
        if selected:
            self.source_path_var.set(selected)
            self._load_source_info()
            self._refresh_all()
            self._refresh_atomsk_command_preview()

    def _browse_output(self) -> None:
        selected = filedialog.asksaveasfilename(
            title="选择输出文件",
            initialdir=str(ROOT),
            defaultextension=".lmp",
            filetypes=[("LAMMPS data", "*.lmp"), ("All files", "*.*")],
        )
        if selected:
            self.output_path_var.set(selected)

    def _browse_atomsk(self) -> None:
        selected = filedialog.askopenfilename(
            title="选择 atomsk.exe",
            initialdir=str(ROOT),
            filetypes=[("atomsk.exe", "atomsk.exe"), ("All files", "*.*")],
        )
        if selected:
            self.atomsk_path_var.set(selected)
            self._refresh_atomsk_command_preview()

    def _open_output_dir(self) -> None:
        path = self._output_path()
        directory = path.parent if path.suffix else path
        directory.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["explorer", str(directory)], shell=False)

    def _invalidate_structure_cache(self) -> None:
        self._structure_cache_key = None
        self._structure_cache_value = None

    def _structure_for_path(self, source_path: Path) -> tuple[LammpsStructure, Path]:
        if not source_path.exists():
            raise FileNotFoundError(f"找不到源文件: {source_path}")
        resolved_source = source_path.resolve()
        cache_mtime = source_path.stat().st_mtime_ns
        atomsk_key = self.atomsk_path_var.get().strip()
        cache_key = (str(resolved_source), cache_mtime, atomsk_key)
        if self._structure_cache_key == cache_key and self._structure_cache_value is not None:
            return self._structure_cache_value
        if source_path.suffix.lower() in SUPPORTED_SOURCE_SUFFIXES:
            resolved_value = read_lammps_structure(source_path), source_path
            self._structure_cache_key = cache_key
            self._structure_cache_value = resolved_value
            return resolved_value
        atomsk = find_atomsk_exe(self.atomsk_path_var.get())
        resolved_path = convert_source_to_lammps(atomsk, source_path, env=self._subprocess_env())
        resolved_value = read_lammps_structure(resolved_path), resolved_path
        self._structure_cache_key = cache_key
        self._structure_cache_value = resolved_value
        return resolved_value

    def _load_source_info(self) -> None:
        source_path = self._source_path()
        try:
            structure, _resolved_path = self._structure_for_path(source_path)
            self.current_atom_count = len(structure.atoms)
            self.current_box = structure.box
            if not self.model_width_var.get().strip() or source_path == DEFAULT_SOURCE:
                self.model_width_var.set(f"{structure.box.width:g}")
            if not self.model_height_var.get().strip() or source_path == DEFAULT_SOURCE:
                self.model_height_var.set(f"{structure.box.height:g}")
        except Exception:
            self.current_atom_count = None
            self.current_box = None
        self._sync_model_library_selection()

    def _sync_geometry_from_source(self) -> bool:
        try:
            structure, _resolved_path = self._structure_for_path(self._source_path())
            self.model_width_var.set(f"{structure.box.width:g}")
            self.model_height_var.set(f"{structure.box.height:g}")
            self.current_atom_count = len(structure.atoms)
            self.current_box = structure.box
            self._sync_model_library_selection()
            self._refresh_all()
            self._log(f"已从源文件同步尺寸: {structure.box.width:g} x {structure.box.height:g} Å")
            return True
        except Exception as exc:
            messagebox.showerror("同步失败", str(exc))
            return False

    def _current_atom_count(self) -> int:
        if self.current_atom_count is not None:
            return self.current_atom_count
        structure, _resolved_path = self._structure_for_path(self._source_path())
        self.current_atom_count = len(structure.atoms)
        self.current_box = structure.box
        return self.current_atom_count

    def _apply_geometry(self, target_path: Path) -> Path:
        config = self._geometry_config()
        atomsk = config.atomsk_path
        env = self._subprocess_env()
        WORK_DIR.mkdir(parents=True, exist_ok=True)
        seed_path = DEFAULT_SEED
        gradient_path = DEFAULT_GRADIENT
        seed_name = seed_path.name
        gradient_name = gradient_path.name
        output_name = target_path.name
        seed_path.parent.mkdir(parents=True, exist_ok=True)
        if seed_path.exists():
            seed_path.unlink()
        if target_path.exists():
            target_path.unlink()
        seed_command = build_atomsk_create_command(
            atomsk,
            config.crystal_structure,
            config.lattice_parameter,
            seed_name,
            hcp_c_over_a=config.hcp_c_over_a,
        )
        self._log("开始生成种晶...")
        result = subprocess.run(seed_command, cwd=WORK_DIR, capture_output=True, text=True, env=env)
        if result.stdout:
            self._log(result.stdout.strip())
        if result.stderr:
            self._log(result.stderr.strip())
        if result.returncode != 0:
            raise RuntimeError(result.stderr or result.stdout or "生成种晶失败")
        gradient_text, previews, node_count, height = generate_gradient_text(config)
        gradient_path.write_text(gradient_text, encoding="utf-8")
        self.current_geometry_preview = previews
        self.current_geometry_node_count = node_count
        self.current_geometry_height = height
        self.current_geometry_nodes, _, _, _ = build_geometry_layout(config)
        self._log(f"已写入梯度文件: {gradient_path}")
        poly_command = [str(atomsk), "--polycrystal", seed_name, gradient_name, output_name, "-wrap"]
        self._log("开始生成多晶结构...")
        result = subprocess.run(poly_command, cwd=WORK_DIR, capture_output=True, text=True, env=env)
        if result.stdout:
            self._log(result.stdout.strip())
        if result.stderr:
            self._log(result.stderr.strip())
        if result.returncode != 0:
            raise RuntimeError(result.stderr or result.stdout or "生成多晶失败")
        if not target_path.exists():
            candidate = WORK_DIR / output_name
            if candidate.exists():
                target_path = candidate
            else:
                details = "\n".join(part for part in (result.stdout.strip(), result.stderr.strip()) if part)
                message = f"Atomsk 未生成几何文件: {target_path}"
                if details:
                    message = f"{message}\nAtomsk 输出:\n{details}"
                raise RuntimeError(message)
        self._invalidate_structure_cache()
        self.source_path_var.set(str(target_path))
        self._load_source_info()
        self._refresh_all()
        return target_path

    def _apply_crack_to_source(self, source_path: Path, target_path: Path) -> tuple[Path, int, str]:
        structure, _resolved_path = self._structure_for_path(source_path)
        crack = self._crack_config()
        atoms, removed, description = apply_slit_crack(structure, crack)
        if target_path.exists():
            target_path.unlink()
        atom_types_count = structure.atom_types or max((atom.atom_type for atom in atoms), default=1)
        write_lammps_structure(target_path, structure, atoms, mass_entries=None, atom_types_count=atom_types_count)
        self._invalidate_structure_cache()
        return target_path, removed, description

    def _entries_for_final_write(self) -> list[CompositionEntry]:
        entries = self._selected_entries()
        if not entries:
            raise ValueError("请先填写至少一个元素配方")
        return entries

    def _assign_alloy(self, source_path: Path, target_path: Path) -> PipelineResult:
        structure, _resolved_path = self._structure_for_path(source_path)
        entries = self._entries_for_final_write()
        counts, normalized_entries = count_assignments(len(structure.atoms), normalize_entries(entries))
        mass_entries = list(normalized_entries)
        assignments = [type_id for type_id, count in enumerate(counts, start=1) for _ in range(count)]
        random.Random(parse_int(self.seed_var.get().strip() or "0", "随机种子")).shuffle(assignments)
        atoms = [AtomRecord(atom_id=index, atom_type=type_id, x=atom.x, y=atom.y, z=atom.z) for index, (atom, type_id) in enumerate(zip(structure.atoms, assignments), start=1)]
        atoms, assignments, removed_close_contacts, minimum_distance = prune_close_contact_atoms(
            atoms,
            structure.box,
            type_assignments=assignments,
            threshold=0.8,
        )
        if removed_close_contacts > 0:
            self._log(
                f"近距离原子清理: 删除 {removed_close_contacts} 个原子；最小间距约 {minimum_distance:.3f} Å"
            )
        doping_entries = self._selected_doping_entries() if self.doping_enabled_var.get() else []
        atoms, assignments, mass_entries, box_override, doping_logs = apply_doping_entries(
            structure,
            atoms,
            assignments,
            mass_entries,
            doping_entries,
            enabled=self.doping_enabled_var.get(),
            seed=parse_int(self.seed_var.get().strip() or "0", "随机种子"),
        )
        write_lammps_structure(
            target_path,
            structure,
            atoms,
            mass_entries=mass_entries,
            atom_types_count=len(mass_entries),
            type_assignments=assignments,
            box_override=box_override,
        )
        self._invalidate_structure_cache()
        for message in doping_logs:
            self._log(message)
        return PipelineResult(source_path=source_path, final_path=target_path, atom_count=len(atoms), atom_types=len(mass_entries), removed_atoms=removed_close_contacts)

    def _generate_geometry_only(self) -> None:
        try:
            target = DEFAULT_GEOMETRY
            self._apply_geometry(target)
            self._set_status(f"几何已生成: {target.name}", SUCCESS)
            self._log(f"几何已生成到 {target}")
        except Exception as exc:
            messagebox.showerror("生成几何失败", str(exc))
            self._log(f"生成几何失败: {exc}")

    def _apply_crack_only(self) -> None:
        try:
            source = self._source_path()
            cracked = DEFAULT_GEOMETRY_CRACK
            target, removed, description = self._apply_crack_to_source(source, cracked)
            self.source_path_var.set(str(target))
            self._load_source_info()
            self._refresh_all()
            self._set_status("裂纹已应用", SUCCESS)
            self._log(f"{description}，删除原子数: {removed}，输出到 {target}")
        except Exception as exc:
            messagebox.showerror("应用裂纹失败", str(exc))
            self._log(f"应用裂纹失败: {exc}")

    def _generate_alloy_only(self) -> None:
        try:
            source = self._source_path()
            output = self._output_path()
            result = self._assign_alloy(source, output)
            cleanup_note = f"；已清理近距离原子 {result.removed_atoms} 个" if result.removed_atoms else ""
            self.source_path_var.set(str(output))
            self._load_source_info()
            self._refresh_all()
            self._set_status(f"合金已生成: {output.name}{cleanup_note}", SUCCESS)
            self._log(f"合金已生成: {result.final_path}{cleanup_note}")
        except Exception as exc:
            messagebox.showerror("生成合金失败", str(exc))
            self._log(f"生成合金失败: {exc}")

    def _generate_full_pipeline(self) -> None:
        try:
            geometry_path = DEFAULT_GEOMETRY
            crack_path = DEFAULT_GEOMETRY_CRACK
            final_path = self._output_path()
            geometry_source = self._apply_geometry(geometry_path)
            cracked_source = geometry_source
            removed = 0
            description = "未启用裂纹"
            if self.crack_mode_var.get() != "none":
                cracked_source, removed, description = self._apply_crack_to_source(geometry_source, crack_path)
            result = self._assign_alloy(cracked_source, final_path)
            cleanup_note = f"；已清理近距离原子 {result.removed_atoms} 个" if result.removed_atoms else ""
            self.source_path_var.set(str(final_path))
            self._load_source_info()
            self._refresh_all()
            self._set_status("全部生成完成", SUCCESS)
            self._log(
                f"一键生成完成: {geometry_source} -> {cracked_source} -> {final_path}; {description}; 删除原子数 {removed}{cleanup_note}"
            )
            messagebox.showinfo("完成", f"已生成最终模型:\n{final_path}")
        except Exception as exc:
            messagebox.showerror("一键生成失败", str(exc))
            self._log(f"一键生成失败: {exc}")

    def _refresh_source_summary(self) -> None:
        path = self._source_path()
        self.source_summary_text.configure(state="normal")
        self.source_summary_text.delete("1.0", "end")
        
        if not path.exists():
            self.source_summary_text.insert("end", f"源文件不存在: {path}")
            self.source_summary_text.configure(state="disabled")
            self.current_atom_count = None
            self.current_box = None
            return
        
        try:
            structure, resolved_path = self._structure_for_path(path)
        except Exception as exc:
            self.source_summary_text.insert("end", f"无法解析源文件: {exc}")
            self.source_summary_text.configure(state="disabled")
            self.current_atom_count = None
            self.current_box = None
            return
            
        summary = [
            f"文件: {structure.path}",
            f"原子数: {len(structure.atoms)}",
            f"原子类型数: {structure.atom_types or '-'}",
            f"盒子尺寸: {structure.box.width:.3f} x {structure.box.height:.3f} x {structure.box.depth:.3f} Å",
            f"X 范围: {structure.box.xlo:.3f} ~ {structure.box.xhi:.3f}",
            f"Y 范围: {structure.box.ylo:.3f} ~ {structure.box.yhi:.3f}",
            f"Z 范围: {structure.box.zlo:.3f} ~ {structure.box.zhi:.3f}",
        ]
        if resolved_path != path:
            summary.append(f"转换后文件: {resolved_path}")
        preset = self._model_preset_by_name(self.model_preset_var.get())
        if preset is not None:
            summary.extend([f"模型来源: {preset.name}", f"模型依据: {preset.basis}", f"模型说明: {preset.description}"])
        else:
            summary.append("模型来源: 自定义源文件")
            
        self.source_summary_text.insert("end", "\n".join(summary))
        self.source_summary_text.configure(state="disabled")
        self.current_atom_count = len(structure.atoms)
        self.current_box = structure.box

    def _load_default_geometry_from_source(self) -> None:
        self._load_source_info()
        if self.current_box is not None:
            self.model_width_var.set(f"{self.current_box.width:g}")
            self.model_height_var.set(f"{self.current_box.height:g}")

    def _apply_preset(self, recipe_text: str) -> None:
        self.recipe_var.set(recipe_text)
        try:
            entries = parse_recipe_text(recipe_text)
            self._fill_rows_from_entries(entries)
            self._refresh_all()
        except Exception as exc:
            self._log(f"预设加载失败: {exc}")

    def _browse_source_and_refresh(self) -> None:
        self._browse_source()
        self._refresh_all()

    def _browse_output_and_refresh(self) -> None:
        self._browse_output()
        self._refresh_all()

    def _sync_geometry_fields_if_needed(self) -> None:
        try:
            structure, _resolved_path = self._structure_for_path(self._source_path())
            self.model_width_var.set(f"{structure.box.width:g}")
            self.model_height_var.set(f"{structure.box.height:g}")
        except Exception:
            pass

    def _clear_all(self) -> None:
        for row in self.composition_rows:
            row.clear()
        self._composition_status_var().set("准备就绪")
        for row in self.doping_rows:
            row.clear()
        self.doping_preset_var.set(DOPING_PRESET_PLACEHOLDER)
        self._doping_status.set("当前未设置掺杂")
        self.doping_enabled_var.set(False)
        self.crack_mode_var.set("none")
        self.crack_orientation_var.set("horizontal")
        self.crack_side_var.set("left")
        self.crack_shape_var.set("rectangle")
        self.crack_length_var.set("80")
        self.crack_opening_var.set("8")
        self._on_crack_shape_changed()
        self._refresh_all()

    def _geometry_target_info(self) -> str:
        try:
            text, previews, node_count, height = self._geometry_preview()
        except Exception as exc:
            return f"几何参数无效: {exc}"
        first_count = derive_first_layer_count(
            parse_float(self.model_width_var.get(), "模型宽度"),
            parse_int(self.first_layer_count_var.get(), "第一层晶粒数"),
            parse_optional_float(self.target_grain_size_var.get()),
        )
        return f"第一层晶粒数 {first_count}，节点数 {node_count}，目标高度 {height:.3f} Å"

    def _add_recipe_string_to_rows(self) -> None:
        self._parse_recipe_to_rows()

    def _generate_geometry_from_output_tab(self) -> None:
        self._generate_geometry_only()

    def _refresh_manual_defaults(self) -> None:
        if self.current_box is not None:
            self.model_width_var.set(f"{self.current_box.width:g}")
            self.model_height_var.set(f"{self.current_box.height:g}")

    def _on_any_change(self) -> None:
        self._schedule_refresh()

    def run(self) -> None:
        self.mainloop()



def main() -> int:
    app = AlloyDesignerApp()
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
