#!/usr/bin/env python3
"""Run polymkt from a checkout without setting PYTHONPATH.

    python polymkt.py doctor
    python polymkt.py demo

`PYTHONPATH=src python3 -m polymkt` still works and is what the docs use,
but that syntax is bash-only — it fails on Windows PowerShell, where the
equivalent is a separate `$env:PYTHONPATH="src"` statement. This shim
sidesteps the difference entirely, so the same command works everywhere.
"""

import sys
from pathlib import Path

# `X | None` in a runtime type alias (http.Transport) needs 3.10.
if sys.version_info < (3, 10):
    sys.exit(f"polymkt needs Python 3.10 or newer; this is "
             f"{sys.version_info.major}.{sys.version_info.minor}. "
             f"On Windows try `py -3.12 polymkt.py {' '.join(sys.argv[1:])}`.")

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from polymkt.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
