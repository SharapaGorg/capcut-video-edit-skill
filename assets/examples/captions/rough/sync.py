import sys
from pathlib import Path
sys.path.insert(0, str(Path.home()/'.claude/skills/video-edit/scripts/layout'))
import xcorr
cache = Path('auto/work/xc'); cache.mkdir(parents=True, exist_ok=True)
pairs = [('hook1.m4a','1.MOV'),('hook2.m4a','1.MOV'),('заходим-нажимаем-на-фильтр.m4a','2.MOV'),('можно-тут-что-то.m4a','3.MOV'),('делюсь-ссылкой-на-сайт.m4a','4.MOV'),('CTA.m4a','5.MOV')]
for v,c in pairs:
    vw = xcorr.read_wav(xcorr.to_wav16k(Path('voice')/v, cache)); cw = xcorr.read_wav(xcorr.to_wav16k(Path('camera')/c, cache))
    print(v, c, xcorr.sync(vw, cw), flush=True)
