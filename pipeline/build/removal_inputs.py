"""One private removal context shared by input readers, status, reaches and export.

Registration is a separate pass: values must be learned before any input loses a
field. Files on disk stay intact; derived work sees only the filtered view.
"""
from contextvars import ContextVar
from functools import wraps
import json
import csv
import io
import yaml
from pathlib import Path

ACTIVE = ContextVar('requested_removals', default=None)


def filtered(value):
    policy = ACTIVE.get()
    if policy is None or not policy.entries:
        return value
    policy.register(value)
    return policy.apply(value)


def publication_inputs(fn):
    @wraps(fn)
    def run(*args, **kwargs):
        if ACTIVE.get() is not None:
            return fn(*args, **kwargs)
        import common
        from export.removals import RemovalList
        policy = RemovalList.load()
        if policy.entries:
            # Raw responses and private state are deliberately outside this inventory.
            # No retired blocklist, environment, credential or token file is opened.
            paths = [p for p in common.DATA_DIR.rglob('*')
                     if p.suffix in {'.json', '.geojson', '.yaml', '.csv'}
                     and not {'private', 'raw', '.git'} & set(p.relative_to(common.DATA_DIR).parts)]
            paths += list((common.DATA_DIR.parent / 'research').glob('*/dischargers.json'))
            extra = kwargs.get('events_dir')
            if extra is not None:
                paths += list(Path(extra).glob('*.json'))
            for path in sorted(set(paths)):
                if path.name in {'name-blocklist.json', 'export-blocked.json', 'removal-list.json'}:
                    continue
                try:
                    text = path.read_text()
                    value = (yaml.safe_load(text) if path.suffix == '.yaml' else
                             list(csv.DictReader(io.StringIO(text))) if path.suffix == '.csv' else json.loads(text))
                    policy.register(value)
                except (OSError, ValueError):
                    raise ValueError('unreadable publication input during removal registration') from None
        token = ACTIVE.set(policy)
        try:
            return fn(*args, **kwargs)
        finally:
            ACTIVE.reset(token)
    return run
