"""Backwards-compatible entrypoint shim for ``python src/battery_soc.py``."""

from __future__ import annotations

import sys
from pathlib import Path

_SRC_DIR = str(Path(__file__).resolve().parent)
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from solar_bridge.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
