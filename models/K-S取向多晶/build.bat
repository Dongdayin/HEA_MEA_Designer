atomsk --create fcc 4.046 Al orient [11-2] [1-10] [111]  aluminium.xsf
atomsk --create bcc 2.86 Fe orient [1-12] [-111] [110]  Fe.xsf -ow
atomsk --polycrystal aluminium.xsf seed.txt Al.lmp -wrap
atomsk --polycrystal Fe.xsf seed.txt final_Fe.lmp -wrap
atomsk Al.lmp -duplicate 1 1 10 Al-layer.lmp
atomsk Fe.lmp -duplicate 1 1 10 Fe-layer.lmp
atomsk --merge Z 2 Al-layer.lmp Fe-layer.lmp AlFe.lmp