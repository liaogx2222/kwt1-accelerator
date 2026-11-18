#!/usr/bin/env python3
"""Python 3.6-compatible launcher for scripts/emit_dc_corners.py.

WHY THIS EXISTS
---------------
The RServer06 login node ships Python 3.6, but scripts/emit_dc_corners.py:102
calls

    out.write_text(..., encoding='utf-8', newline='\\n')

and the ``newline`` keyword for pathlib.Path.write_text only exists from
Python 3.10. On 3.6 that raises

    TypeError: write_text() got an unexpected keyword argument 'newline'

This launcher does NOT reimplement the generator. It imports the original,
hash-bound script and supplies a 3.6-safe Path.write_text, so there is still
exactly ONE copy of the corner-emission logic. On Linux the newline argument
is a no-op anyway (no CRLF translation), so the emitted Tcl is byte-identical.

Usage is identical to the original:

    python3 flow/smic40/gen_dc_corners.py --config flow/targets/smic40.binding.filled.json \
        --output flow/targets/smic40.dc_corners.tcl --force

If a Python >= 3.10 is available on the node, prefer running the original
script directly; this launcher is only a compatibility bridge.
"""
import sys
from pathlib import Path

_orig_write_text = Path.write_text


def _write_text(self, data, encoding=None, errors=None, newline=None):
    """3.6-safe stand-in for Path.write_text (3.10+ signature)."""
    if newline is None:
        return _orig_write_text(self, data, encoding, errors)
    text = data.replace('\r\n', '\n').replace('\r', '\n')
    if newline not in ('', '\n'):
        text = text.replace('\n', newline)
    self.write_bytes(text.encode(encoding or 'utf-8'))
    return len(text)


Path.write_text = _write_text

HERE = Path(__file__).resolve()
SCRIPTS = HERE.parents[2] / 'scripts'
if not (SCRIPTS / 'emit_dc_corners.py').is_file():
    sys.stderr.write('ERROR: cannot locate scripts/emit_dc_corners.py next to %s\n' % HERE)
    raise SystemExit(2)
sys.path.insert(0, str(SCRIPTS))

if sys.version_info < (3, 10):
    sys.stderr.write('NOTE: python %s detected; using the 3.6 write_text shim\n'
                     % '.'.join(str(x) for x in sys.version_info[:3]))

import emit_dc_corners  # noqa: E402  (path must be set up first)

if __name__ == '__main__':
    raise SystemExit(emit_dc_corners.main())
