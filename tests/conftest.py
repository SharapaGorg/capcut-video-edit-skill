import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
for sub in ("stage0", "stage1", "stage2", "stage3", "layout", "stage4", "stage5", "stage6", "graphics", "stage9", "stage10", "shorts"):
    sys.path.insert(1, str(SCRIPTS / sub))
