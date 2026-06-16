# Data Sources and References

This document records the provenance and research boundary for the example data bundled with HEA/MEA Designer.

## Scope

The bundled `data/` and `models/` files are workflow fixtures and model presets for testing, demonstration, and reproducible preprocessing. They are not experimental measurements, validated material-property datasets, or benchmark conclusions.

The software helps prepare atomic structures and LAMMPS inputs. Any publication-quality result still requires independent checks of interatomic potentials, boundary conditions, timestep, system size, ensemble choice, equilibration, convergence, and comparison against experiments or higher-accuracy calculations where appropriate.

## Bundled Structure Assets

| Path | Format | Header / size | Role in software |
|---|---:|---:|---|
| `data/final.lmp` | LAMMPS atomic data | Voronoi polycrystal, 128 grains, 216236 atoms, Al seed | Default quick-start structure and regression fixture |
| `models/二维六边形多晶/final.lmp` | LAMMPS atomic data | Voronoi polycrystal, 2 grains, 782 atoms | Small 2D regular-grain comparison preset |
| `models/二维随机多晶/final.lmp` | LAMMPS atomic data | Voronoi polycrystal, 8 grains, 4881 atoms | Small 2D random-grain comparison preset |
| `models/二维梯度孪晶多晶/final.cfg` | Atomsk/Atomeye CFG | 105033 particles, 38 grains | Gradient/twin reference preset, converted through Atomsk when used downstream |
| `models/倾斜孪晶多晶/final.cfg` | Atomsk/Atomeye CFG | 492568 particles, 12 grains | Inclined twin preset |
| `models/预存孪晶多晶/final.cfg` | Atomsk/Atomeye CFG | 492585 particles, 12 grains | Predefined twin preset |
| `models/双相多晶/final_polycrystal.cfg` | Atomsk/Atomeye CFG | 589162 particles, two 6-grain Voronoi polycrystal blocks | Dual-phase polycrystal preset |
| `models/K-S取向多晶/final_Fe.lmp` | LAMMPS atomic data | Voronoi polycrystal, 8 grains, 6926 atoms, Fe seed | K-S orientation workflow preset |

The retained assets are the minimum set referenced by the current GUI model library. Atomsk intermediate files, seed files, generated statistics, local runtime output, old tutorials, video scripts, private notes, and research PDFs are intentionally excluded from the repository and release package.

## Generation and Conversion Basis

The internal model-library terminology follows Atomsk-style structure generation and conversion workflows:

- Voronoi/polycrystal presets use grain nodes and cell partitioning consistent with Atomsk `--polycrystal` workflows.
- `.cfg` and `.xsf` user inputs are converted to LAMMPS-compatible temporary structures through Atomsk before later HEA/MEA composition replacement, crack preprocessing, or LAMMPS input generation.
- LAMMPS files are parsed in the current code as `Atoms # atomic` structures with `id type x y z` atom records.

## Citation Guidance

If this software or its bundled examples help prepare a simulation workflow, cite the underlying tools and alloy-design literature as relevant to your actual method:

1. Pierre Hirel, "Atomsk: A tool for manipulating and converting atomic data files", Computer Physics Communications 197, 212-219 (2015). DOI: https://doi.org/10.1016/j.cpc.2015.07.012
2. Steve Plimpton, "Fast Parallel Algorithms for Short-Range Molecular Dynamics", Journal of Computational Physics 117, 1-19 (1995). DOI: https://doi.org/10.1006/jcph.1995.1039
3. Aidan P. Thompson et al., "LAMMPS - a flexible simulation tool for particle-based materials modeling at the atomic, meso, and continuum scales", Computer Physics Communications 271, 108171 (2022). DOI: https://doi.org/10.1016/j.cpc.2021.108171
4. B. Cantor, I. T. H. Chang, P. Knight, and A. J. B. Vincent, "Microstructural development in equiatomic multicomponent alloys", Materials Science and Engineering A 375-377, 213-218 (2004). DOI: https://doi.org/10.1016/j.msea.2003.10.257
5. J.-W. Yeh, S.-K. Chen, S.-J. Lin, J.-Y. Gan, and T.-S. Chin, "Nanostructured High-Entropy Alloys with Multiple Principal Elements: Novel Alloy Design Concepts and Outcomes", Advanced Engineering Materials 6, 299-303 (2004). DOI: https://doi.org/10.1002/adem.200300567

When reporting results, cite the exact potential files, LAMMPS version, Atomsk version, structure-generation parameters, random seeds, boundary conditions, and all postprocessing scripts used in the final study.
