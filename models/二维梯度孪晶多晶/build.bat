atomsk --create fcc 4.02 Al orient [11-2] [111] [-110] -duplicate 1 2 1 Al_cell.xsf
atomsk Al_cell.xsf -mirror 0 Y -wrap Al_mirror.xsf
atomsk --merge Y 2 Al_cell.xsf Al_mirror.xsf Al_final.cfg
atomsk --polycrystal Al_final.cfg gradient.txt final.cfg
pause