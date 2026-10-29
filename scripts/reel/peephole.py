"""Peephole fisheye for a reel section (build_reel: section "fisheye": {alpha, rmax, blur}): equidistant fisheye of the
rectilinear camera inside a circle, the rest of the frame = the same frame zoomed 1.3x and blurred. Tested 2026-10-29 on
14/hook: alpha 140, rmax 760 = the door-peephole look the user asked for; lenscorrection (pincushion) was rejected."""
import numpy as np, math, sys
W,H=1080,1920
def maps(alpha, rmax, name):
    """Equidistant fisheye of a rectilinear source: source assumed to cover `alpha` deg horizontally; output angle
    theta = 90 deg at radius rmax px. Outside the source -> mask 0 (filled with blur by the caller)."""
    y,x=np.mgrid[0:H,0:W].astype(np.float64)
    cx,cy=(W-1)/2,(H-1)/2
    Fin=(W/2)/math.tan(math.radians(alpha/2)); Fout=rmax/(math.pi/2)
    dx,dy=x-cx,y-cy; r=np.hypot(dx,dy); th=np.minimum(r/Fout, math.pi/2-1e-3)
    rin=Fin*np.tan(th); k=np.where(r>1e-6, rin/np.maximum(r,1e-6), Fin/Fout)
    xm=cx+dx*k; ym=cy+dy*k
    inside=(xm>=0)&(xm<=W-1)&(ym>=0)&(ym<=H-1)&(r<Fout*(math.pi/2-1e-3))
    for arr,fn in ((xm,f'{name}_x.pgm'),(ym,f'{name}_y.pgm')):
        a=np.clip(np.rint(np.where(inside,arr,0)),0,65535).astype('>u2')
        with open(fn,'wb') as fh: fh.write(f'P5\n{W} {H}\n65535\n'.encode()); fh.write(a.tobytes())
    with open(f'{name}_m.pgm','wb') as fh: fh.write(f'P5\n{W} {H}\n255\n'.encode()); fh.write((inside*255).astype('u1').tobytes())
def build(wd, alpha=140, rmax=760):
    """Write the remap maps + mask into wd (cached by the parameters); returns (x.pgm, y.pgm, m.pgm) paths."""
    from pathlib import Path
    wd = Path(wd); name = wd / f'peep_{int(alpha)}_{int(rmax)}'
    if not (Path(f'{name}_m.pgm')).is_file(): maps(alpha, rmax, str(name))
    return f'{name}_x.pgm', f'{name}_y.pgm', f'{name}_m.pgm'


if __name__ == '__main__':
    for spec in sys.argv[1:]:
        a, r = spec.split(':'); maps(float(a), float(r), f'fq{a}_{r}')
