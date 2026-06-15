# HEA/MEA Designer

HEA/MEA Designer is a Windows desktop workflow tool for high-entropy and medium-entropy alloy molecular-dynamics preprocessing. It integrates alloy recipe setup, doping, grain/geometry generation, single-crystal and polycrystal modeling, crack templates, Atomsk postprocessing, and LAMMPS input preparation.

The current public release is **v1.3.4**.

Naming convention:

- Product name: **HEA/MEA Designer**
- Chinese name: **高/中熵合金设计器**
- Repository, executable, and release artifact prefix: **HEA_MEA_Designer**

## Download

Download the Windows package from:

- [HEA_MEA_Designer v1.3.4](https://github.com/Dongdayin/HEA_MEA_Designer/releases/tag/v1.3.4)

After downloading, extract the archive and run:

```text
HEA_MEA_Designer.exe
```

Keep the `_internal` directory beside the executable.

## Key Features

- HEA/MEA recipe definition and composition preview.
- Substitution, vacancy, adsorption, and interstitial doping workflows.
- Gradient grain, 2D/3D polycrystal, nanopowder, and single-crystal model generation.
- Crack preprocessing templates.
- Atomsk postprocessing for wrap, supercell duplication, mirror/twin operations, and mirror-merge bilayer construction.
- LAMMPS input generation, runtime path configuration, and output directory organization.
- Reproducibility reports for Atomsk postprocessing through `.atomsk.txt` command logs.

## Repository Scope

The public repository intentionally keeps only the files needed to build, verify, package, and run the current tool:

- application source, tests, package scripts, and verification scripts;
- current user-facing documentation in `docs/`;
- the default structure file `data/final.lmp`;
- the curated model presets referenced by the GUI model library.

Private notes, video scripts, research-paper references, old tutorial material, Atomsk intermediate output, generated runtime files, and local distribution archives are excluded from the repository and release zip.

## Recent Fixes

v1.3.2 fixed an Atomsk workflow issue where repeated postprocessing could make the output path equal to the current source model path. v1.3.3 aligns the public product name across the GUI, documentation, repository, and release pages. v1.3.4 trims the public repository and release package to the current necessary files only. The GUI now:

- warns in the command preview when a source/output collision is detected;
- provides an `自动命名输出` button;
- automatically prepares a safe next output path after a successful Atomsk run;
- keeps the lower-level overwrite protection in place.

## Validation

The v1.3.4 package was checked with:

```powershell
python tools\verify_project.py
```

Additional smoke checks were run for:

- packaged executable startup;
- real Atomsk duplicate/postprocess execution;
- source/output path collision avoidance;
- release zip SHA256 verification.

## Research Boundary

This project is a modeling and simulation-preparation tool. It does not validate material conclusions by itself. Formal research still requires potential-file suitability checks, convergence tests, system-size and timestep sensitivity analysis, and comparison with experiments or higher-accuracy calculations where appropriate.
