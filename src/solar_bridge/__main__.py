"""Support running the package via ``python -m solar_bridge``."""

from __future__ import annotations

import sys

from solar_bridge.cli import main

if __name__ == "__main__":
    sys.exit(main())
