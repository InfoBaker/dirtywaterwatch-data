"""Bound work by records, including long linked notice histories."""
import copy

import pytest

from export import detail as D
from export import build as X


def chain(n):
    return [dict(event_id=f'ny:{i}', source_id='ny-dec-sprtk', event_type='sso',
                 parent_event_id=f'ny:{i - 1}' if i else None,
                 published_at=f'2026-01-01T00:{i % 60:02d}:00Z', volume_gal=i,
                 detail={'report_kind': 'Update', 'volume_qualifier': 'estimated'})
            for i in range(n)]


def test_later_totals_reads_each_family_member_once(monkeypatch):
    events = chain(120)
    # No total: the old implementation exhausts every family for every event.
    for e in events:
        e['volume_gal'] = None
    calls = []
    original = D._t
    monkeypatch.setattr(D, '_t', lambda e: calls.append(e['event_id']) or original(e))
    assert D.later_totals(events) == set()
    assert len(calls) <= len(events)


def test_links_reads_numeric_candidates_once_per_family():
    reads = []

    class Counted(dict):
        def get(self, key, default=None):
            if key == 'volume_gal':
                reads.append(self['event_id'])
            return super().get(key, default)

    events = [Counted(e) for e in chain(120)]
    result = D.links_of(events)
    assert result['ny:0']['later_volume']['event_id'] == 'ny:59'
    assert len(reads) <= 4 * len(events)


def test_enrichment_scrubs_repeated_source_text_once_per_call(monkeypatch):
    events = [dict(event_id=f'beacon:{i}', source_id='fed-beacon-beach-actions', event_type='beach',
                   raw={'action_type': 'Advisory', 'reason_comments': 'Elevated bacteria levels'})
              for i in range(100)]
    expected = [D.detail_of(e) for e in events]
    original, calls = D._clean, []

    def counted(value, address=False):
        calls.append((value, address))
        return original(value, address=address)

    monkeypatch.setattr(D, '_clean', counted)
    D.enrich(events)
    assert [e['detail'] for e in events] == expected
    assert len(calls) == len(set(calls)) == 2
    # A fresh export runs the scrubs again; nothing survives the enrichment call.
    D.enrich(events)
    assert len(calls) == 4


def test_compact_writes_overlap_and_finish_before_returning(tmp_path, monkeypatch):
    from threading import Event

    first_started, release_first = Event(), Event()
    original = X.write_compact

    def write(path, obj):
        if path.name == 'first.json':
            first_started.set()
            assert release_first.wait(5), 'independent writes did not overlap'
        else:
            assert first_started.wait(5)
            release_first.set()
        original(path, obj)

    monkeypatch.setattr(X, 'write_compact', write)
    with X.compact_writes(workers=2, max_pending=2) as emit:
        emit(tmp_path / 'first.json', {'text': 'Rivière'})
        emit(tmp_path / 'second.json', {'text': 'second'})
    assert (tmp_path / 'first.json').read_bytes() == '{"text":"Rivière"}'.encode()
    assert (tmp_path / 'second.json').read_bytes() == b'{"text":"second"}'
    assert not list(tmp_path.glob('*.tmp'))


def test_compact_writes_propagate_failure_and_join_workers(tmp_path, monkeypatch):
    from threading import Event

    second_started, release_second, second_finished = Event(), Event(), Event()

    def write(path, obj):
        if path.name == 'first.json':
            assert second_started.wait(5)
            release_second.set()
            raise OSError('synthetic write failure')
        second_started.set()
        assert release_second.wait(5)
        second_finished.set()

    monkeypatch.setattr(X, 'write_compact', write)
    with pytest.raises(OSError, match='synthetic write failure'):
        with X.compact_writes(workers=2, max_pending=2) as emit:
            emit(tmp_path / 'first.json', {})
            emit(tmp_path / 'second.json', {})
    assert second_finished.is_set()


@pytest.mark.parametrize('max_pending', [2, 32])
@pytest.mark.parametrize('alias', ['case', 'parent', 'unicode'])
def test_compact_writes_serialize_aliases_in_input_order(tmp_path, monkeypatch, max_pending, alias):
    from threading import Event

    first = tmp_path / 'feed~3AA.json'
    second = tmp_path / 'feed~3Aa.json'
    if alias == 'parent':
        (tmp_path / 'alias').symlink_to(tmp_path, target_is_directory=True)
        second = tmp_path / 'alias' / second.name
    elif alias == 'unicode':
        first, second = tmp_path / 'caf\u00e9.json', tmp_path / 'cafe\u0301.json'
    second_started, first_finished = Event(), Event()
    calls, overlaps, public = [], [], {}

    def write(path, obj):
        calls.append(obj['order'])
        if obj['order'] == 1:
            # Force the later write to finish first if aliases run concurrently.
            # A serial writer can finish after this bounded wait without the later job.
            second_started.wait(0.1)
        else:
            if not first_finished.is_set():
                overlaps.append(obj['order'])
            second_started.set()
        public['aliased destination'] = obj
        if obj['order'] == 1:
            first_finished.set()

    monkeypatch.setattr(X, 'write_compact', write)
    with X.compact_writes(workers=2, max_pending=max_pending) as emit:
        emit(first, {'order': 1})
        emit(second, {'order': 2})
        emit(first, {'order': 3})
    assert calls == [1, 2, 3]
    assert overlaps == []
    assert public['aliased destination'] == {'order': 3}


def test_compact_writes_use_unique_temps_and_keep_complete_json_on_failure(tmp_path, monkeypatch):
    from pathlib import Path

    target = tmp_path / 'feed~3AA.json'
    target.write_bytes(b'{"previous":true}')
    original_open, original_replace = Path.open, Path.replace
    temps = []

    class PartialWrite:
        def __init__(self, file):
            self.file = file

        def __enter__(self):
            self.file.__enter__()
            return self

        def __exit__(self, *args):
            return self.file.__exit__(*args)

        def write(self, text):
            if '"fail":true' in text:
                self.file.write('{')
                self.file.flush()
                raise OSError('synthetic partial write')
            return self.file.write(text)

    def open_file(path, mode='r', *args, **kwargs):
        file = original_open(path, mode, *args, **kwargs)
        if mode in ('w', 'x'):
            temps.append(path)
            return PartialWrite(file)
        return file

    def replace(path, destination):
        # Only complete JSON may become public.
        import json
        json.loads(path.read_text())
        return original_replace(path, destination)

    monkeypatch.setattr(Path, 'open', open_file)
    monkeypatch.setattr(Path, 'replace', replace)
    with pytest.raises(OSError, match='synthetic partial write'):
        with X.compact_writes(workers=2) as emit:
            emit(target, {'complete': True})
            emit(target, {'fail': True})
    assert target.read_bytes() == b'{"complete":true}'
    assert len(temps) == 2 and len({str(p).casefold() for p in temps}) == 2
    assert not list(tmp_path.glob('*.tmp'))


@pytest.mark.parametrize('reverse', [False, True])
def test_family_summary_matches_exhaustive_selection(reverse):
    events = chain(75)
    events[1]['duplicate_of'] = 'ny:0'
    events[2]['published_at'] = 'invalid'
    events[3]['source_id'] = 'different-feed'
    events[4]['source_id'] = 'ny-dec-sprtk-web'
    events[5]['volume_gal'] = None
    events[5]['volume_text'] = 'more than 800 gallons'
    events[6]['volume_gal'] = True  # links historically accepts bool; total deliberately does not
    events[7]['_states_total'] = False
    events[8]['_states_total'] = True
    events[9]['event_type'] = 'beach'
    events[10]['parent_event_id'] = 'ny:12'  # cycle
    events[11]['published_at'] = None
    events[11]['reported_at'] = '2026-01-01T00:50:00Z'
    events[12]['detail']['volume_qualifier'] = 'measured'
    events[13]['parent_event_id'] = 'absent'
    events[14]['parent_event_id'] = events[14]['event_id']
    events[15]['raw'] = {'_other_source_record': ['ny:1', 'ny:2']}
    if reverse:
        events.reverse()
    duplicates = {'ny:58'}
    original = copy.deepcopy(events)
    by_id = {e['event_id']: e for e in events}
    _, family_of = D._families(by_id)
    times = {eid: D._t(e) for eid, e in by_id.items()}
    dup = lambda e: bool(e.get('duplicate_of')) or e['event_id'] in duplicates
    expected_totals, expected_volumes = set(), {}
    for eid, e in by_id.items():
        later = [x for x in family_of(eid) or [] if x is not e and not dup(x)
                 and times[eid] is not None and times[x['event_id']] is not None
                 and times[x['event_id']] > times[eid]]
        if any(x['_states_total'] if '_states_total' in x else D.states_total(x) for x in later):
            expected_totals.add(eid)
        candidates = [x for x in later if isinstance(x.get('volume_gal'), (int, float))]
        if candidates and e['event_type'] in D.DISCHARGE_TYPES and not dup(e):
            x = max(candidates, key=lambda x: times[x['event_id']])
            q = D._qualifier(x)
            if not (x['volume_gal'] == e.get('volume_gal') and q == D._qualifier(e)):
                expected_volumes[eid] = {k: v for k, v in {
                    'event_id': x['event_id'], 'volume_gal': x['volume_gal'], 'volume_text': x.get('volume_text'),
                    'volume_qualifier': q, 'report_kind': D._kind(x), 'published_at': x.get('published_at'),
                }.items() if v is not None}
    assert D.later_totals(events, duplicates) == expected_totals
    actual = D.links_of(events, duplicates)
    assert {eid: x['later_volume'] for eid, x in actual.items() if 'later_volume' in x} == expected_volumes
    assert events == original
