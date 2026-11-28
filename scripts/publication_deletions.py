#!/usr/bin/env python3
"""Delete retired publication keys without printing private filenames or provider output."""
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / 'data/private/publication-deletions.json'


def delete(path=DEFAULT):
    path = Path(path)
    if not path.exists():
        return 0
    try:
        keys = json.loads(path.read_text())
        if not isinstance(keys, list) or any(not isinstance(k, str) or not k or
                PurePosixPath(k).is_absolute() or '..' in PurePosixPath(k).parts or '\\' in k for k in keys):
            raise ValueError('invalid manifest')
        for key in keys:
            result = subprocess.run([sys.executable, '-I', str(ROOT / 'scripts/wrangler_redact.py'),
                                     'r2', 'object', 'delete', 'dirtywaterwatch-data/current/' + key, '--remote'],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300)
            if result.returncode:
                raise RuntimeError('delete failed')
        # Keep the private manifest for retries on later runs and restored state.
        return 0
    except (OSError, ValueError, TypeError, RuntimeError, subprocess.TimeoutExpired):
        print('publication key retirement failed; contents withheld', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(delete())
