atomsk --create fcc 3.61 Cu Cu_unitcell.xsf
atomsk --polycrystal Cu_unitcell.xsf polycrystal.txt Cu_polycrystal.cfg -select prop grainID 1 -rmatom select -select prop grainID 6 -rmatom select
atomsk --create bcc 3.16 W W_unitcell.xsf
atomsk --polycrystal W_unitcell.xsf polycrystal.txt W_polycrystal.cfg -select prop grainID 2:5 -rmatom select
atomsk --merge 2 Cu_polycrystal.cfg W_polycrystal.cfg final_polycrystal.cfg
pause