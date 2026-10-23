import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
for sub in ("stage0", "stage1", "stage2", "layout"):
    sys.path.insert(1, str(SCRIPTS / sub))
