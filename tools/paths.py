"""Every path the tools share, in one place, plus first-run bootstrap.

Two files are per-user and gitignored: config/providers.json (model choices and key names)
and core/master-cv.json (the facts). Each has a committed .example.json beside it. The
config is copied automatically on first run; the master is not - it is written by the
dashboard's Setup tab from the user's own CV, because a CV full of someone else's facts is
worse than no CV at all.
"""
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CONFIG = ROOT / "config" / "providers.json"
CONFIG_EXAMPLE = ROOT / "config" / "providers.example.json"
TERMS = ROOT / "config" / "terminology.json"
STYLE = ROOT / "config" / "style.json"

MASTER = ROOT / "core" / "master-cv.json"
MASTER_EXAMPLE = ROOT / "core" / "master-cv.example.json"

POSITIONS = ROOT / "positions"
ENV = ROOT / ".env"
RULES = ROOT / "RULES.md"
LEDGER = ROOT / "state" / "usage.jsonl"


def ensure_config():
    """Give a fresh clone a providers.json to edit. Returns the path either way."""
    if not CONFIG.exists() and CONFIG_EXAMPLE.exists():
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(CONFIG_EXAMPLE, CONFIG)
    return CONFIG


def master_exists():
    return MASTER.exists()
