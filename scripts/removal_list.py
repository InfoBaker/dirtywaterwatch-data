#!/usr/bin/env python3
"""Maintain the private R2 removal list. Only request ids are ever printed."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'pipeline'))
from export.removals import DEFAULT_PATH, RemovalList

KEY = 'dirtywaterwatch-data/state/removal-list.json'


def transfer(action, path):
    # Use the existing guarded S3 route, never the REST fallback or raw AWS output.
    if not os.environ.get('R2_S3_ENDPOINT'):
        raise RuntimeError('the existing S3 route must be configured')
    cmd = [sys.executable, '-I', str(ROOT / 'scripts/wrangler_redact.py'),
           'r2', 'object', action, KEY, '--file', str(path), '--remote']
    try:
        run = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300)
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError('removal list transfer failed; contents withheld') from None
    if run.returncode == 0:
        return True
    # The guard normalizes S3 NoSuchKey, and only that response, to this fixed text.
    if action == 'get' and b'The specified key does not exist' in run.stdout + run.stderr:
        return False
    raise RuntimeError('removal list transfer failed; contents withheld')


def fetch(path=DEFAULT_PATH):
    """Absent is empty; failed reads never replace the last good list or permit publication."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(dir=path.parent) as work:
        staging = Path(work) / 'requests.json'
        if not transfer('get', staging):
            staging.write_text('[]\n', encoding='utf-8')
        RemovalList.load(staging)
        staging.chmod(0o600)
        staging.replace(path)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='command', required=True)
    sub.add_parser('fetch', help='restore the private list before collection/export')
    sub.add_parser('list', help='print ids only')
    add = sub.add_parser('add', help='read one entry from a private JSON file or stdin')
    add.add_argument('--file', default='-', help='private input file; default stdin')
    remove = sub.add_parser('remove')
    remove.add_argument('id')
    args = ap.parse_args(argv)
    try:
        if args.command == 'fetch':
            fetch()
            return 0
        # Never edit the refresh's local copy, and never put a temporary list in git.
        with tempfile.TemporaryDirectory(prefix='dww-removals-') as work:
            path = Path(work) / 'requests.json'
            fetch(path)
            policy = RemovalList.load(path)
            entries = policy.entries
            if args.command == 'list':
                for entry in entries:
                    print(entry['id'])
                return 0
            if args.command == 'add':
                text = sys.stdin.read() if args.file == '-' else Path(args.file).read_text(encoding='utf-8')
                entry = json.loads(text)
                entries.append(entry)
            else:
                if args.id not in {e['id'] for e in entries}:
                    raise ValueError('unknown removal id')
                entries = [e for e in entries if e['id'] != args.id]
            RemovalList(entries)  # validate before replacing the remote object
            path.write_text(json.dumps(entries, ensure_ascii=False) + '\n', encoding='utf-8')
            path.chmod(0o600)
            transfer('put', path)
        return 0
    except (ValueError, TypeError, OSError, RuntimeError):
        print('removal list operation failed; contents withheld', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
