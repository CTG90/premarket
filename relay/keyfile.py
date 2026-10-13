"""Load Webull keys from MakeMeTrade/.webull_paper when they aren't already in the environment.
Lets Windows (and double-click launches) work without `source`. File format: lines of
export NAME='value'   (written by setup.command / setup.bat)."""
import os
from pathlib import Path

KEYFILE = Path(__file__).resolve().parent.parent / ".webull_paper"


def load():
    if not KEYFILE.exists():
        return
    for line in KEYFILE.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[7:]
        if "=" not in line or line.startswith("#"):
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip("'\"")
        if k.startswith("WEBULL_") and v and not os.environ.get(k):
            os.environ[k] = v


load()
