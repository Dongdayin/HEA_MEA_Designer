Files:
1) in.tensile_alloy_template  -> main tensile input script
2) ff_eam_alloy.in            -> example EAM/alloy force-field module
3) ff_nep.in                  -> example NEP force-field module

Recommended usage:
- Keep the main in file unchanged.
- Modify only:
  variable datafile string xxx.data
  variable ffmodule string ff_eam_alloy.in   (or ff_nep.in)
- Then edit the force-field file name inside the selected module.

Important assumption:
- This template is for periodic bulk uniaxial tension.
- boundary is p p p and tension direction is z.
- If you need free-surface tensile loading or rigid clamps at two ends,
  the boundary conditions and loading method should be rewritten.
