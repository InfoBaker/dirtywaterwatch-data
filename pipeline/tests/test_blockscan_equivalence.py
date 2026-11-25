"""Exact self-check semantics; every name and record here is invented."""
import json
import random
import re

import pytest

from build import redact as R
from export import build as X


def original_found(names, text):
    phrases = [(n, frozenset(R._SCAN_WORDS.findall(n.lower())), R._phrase_re([n]))
               for n in names if n.strip()]
    words = frozenset().union(*(ws for _, ws, _ in phrases)) if phrases else frozenset()
    if not phrases or not text:
        return []
    have = words.intersection(R._SCAN_WORDS.findall(text.lower()))
    if not have:
        return []
    return [n for n, ws, rx in phrases if ws <= have and rx.search(text)]


NAMES = ['Zorbel Quillfeather', 'Quillfeather', 'Zorbel', 'Élvix Nørble', "Q'Zorbel",
         'Q’Zorbel', 'Zorbel-Nørble', 'İxor Vex', 'Iſkor Vex', 'Korbel', 'Σorbel',
         'Zorbel\tQuillfeather', 'Zorbel  Quillfeather', ' Zorbel ', 'Vex.', '!!!', '123',
         'Zorbel Quillfeather', '', '  ', '0', r'Zorbel\nQuillfeather']


def test_original_equivalence_randomized():
    rng = random.Random(72134)
    alphabet = 'aZéİıſKΣςσøß012_\n\t \'’.,:;-\\"[]{}'
    for _ in range(4000):
        names = rng.sample(NAMES, rng.randrange(len(NAMES) + 1))
        text = ''.join(rng.choice(alphabet) for _ in range(rng.randrange(100)))
        for _ in range(rng.randrange(5)):
            n = rng.choice(NAMES)
            n = rng.choice([n, n.upper(), n.lower(), n.swapcase(), json.dumps(n),
                            n.replace(' ', '   '), n.replace(' ', r'\u0020')])
            pos = rng.randrange(len(text) + 1)
            text = text[:pos] + n + text[pos:]
        assert R.BlockScan(names).found(text) == original_found(names, text)


@pytest.mark.parametrize('text', [
    'Zorbel Quillfeather', 'xZorbel Quillfeather', "x'Zorbel Quillfeather", "'Zorbel Quillfeather'",
    'Zorbel   Quillfeather', 'Zorbel    Quillfeather', 'Zorbel\nQuillfeather',
    r'Zorbel\u0020Quillfeather', r'\u005aorbel Quillfeather', r'Zorbel\nQuillfeather',
    'ÉLVIX NØRBLE', 'Iſkor Vex Iskor', '!!! Zorbel', '123 Zorbel',
])
def test_original_boundaries_and_serialized_escapes(text):
    assert R.BlockScan(NAMES).found(text) == original_found(NAMES, text)


def test_timestamp_only_rebuild_reuses_cache_without_dropping_fields(tmp_path, monkeypatch):
    out = tmp_path / 'out'
    out.mkdir()
    p = out / 'events.json'
    cache = tmp_path / 'cache.json'
    p.write_text(json.dumps({'fetched_at': '2026-11-24T01:23:45Z', 'raw': {'text': 'river'}}))
    assert X.blocklist_hits(out, ['Zorbel Quillfeather'], cache) == []
    calls = []
    original = R.BlockScan.found
    monkeypatch.setattr(R.BlockScan, 'found', lambda self, t: calls.append(t) or original(self, t))
    p.write_text(json.dumps({'fetched_at': '2026-11-24T02:34:56Z', 'raw': {'text': 'river'}}))
    assert X.blocklist_hits(out, ['Zorbel Quillfeather'], cache) == []
    assert calls == []
    p.write_text(json.dumps({'fetched_at': 'Zorbel Quillfeather', 'raw': {'text': 'river'}}))
    assert X.blocklist_hits(out, ['Zorbel Quillfeather'], cache) == ['events.json']


def test_digest_equivalence_randomized():
    rng = random.Random(193)
    for names in [NAMES, [n for n in NAMES if not re.search('[0-9]', n)], ['Zorbel', '!!!'], ['123', 'Zorbel']]:
        scan = R.BlockScan(names)
        for _ in range(500):
            text = ' '.join(rng.choices(NAMES + ['2026-11-24T01:02:03Z', 'Zorbel123', '123Zorbel'], k=8))
            normalized = scan.cache_text(text)
            assert scan.found(text) == scan.found(normalized) == original_found(names, text)


def test_every_original_path_and_order(tmp_path):
    for d in ('events', 'waters', X.REACH_STATE_DIR):
        (tmp_path / d).mkdir()
    paths = ['events.json', *X.PUBLIC_PAYLOADS, 'waters/a.json', 'events/a.json',
             f'{X.REACH_STATE_DIR}/MA.geojson']
    added = ['events/new.txt', 'new.json']
    for name in paths + added:
        (tmp_path / name).write_text('Zorbel Quillfeather')
    assert X.blocklist_hits(tmp_path, ['Zorbel Quillfeather']) == paths + added


def test_clean_text_never_needs_per_name_search(monkeypatch):
    scan = R.BlockScan(['Zorbel Quillfeather', 'Élvix Nørble'])

    class NoTokenization:
        def findall(self, text):
            pytest.fail('clean text used the original per-name path')

    monkeypatch.setattr(R, '_SCAN_WORDS', NoTokenization())
    assert scan.found('{"raw":{"text":"a reported overflow"}}') == []


def test_long_name_and_overlapping_prefixes():
    names = ['Z' * 5000, 'Zorbel', 'Zorbel Quillfeather', 'Quillfeather', '!!!']
    for text in [names[0], 'Zorbel Quillfeather !!!', 'Zorbel !!!']:
        assert R.BlockScan(names).found(text) == original_found(names, text)


def test_cache_stats_invalid_and_changed_stamp(tmp_path, monkeypatch):
    out = tmp_path / 'out'
    out.mkdir()
    (out / 'events.json').write_text('river')
    cache = tmp_path / 'cache.json'
    stats = {}
    names = ['Zorbel Quillfeather']
    X.blocklist_hits(out, names, cache, stats=stats)
    assert stats == dict(files=1, scanned=1, cache_hits=0, cache_state='missing', in_memory=0)
    X.blocklist_hits(out, names, cache, stats=stats)
    assert stats == dict(files=1, scanned=0, cache_hits=1, cache_state='loaded', in_memory=0)
    monkeypatch.setattr(X, 'scan_stamp', lambda names: 'new semantics')
    X.blocklist_hits(out, names, cache, stats=stats)
    assert stats['scanned'] == 1 and stats['cache_state'] == 'stamp_changed'
    cache.write_text('{broken')
    X.blocklist_hits(out, names, cache, stats=stats)
    assert stats['scanned'] == 1 and stats['cache_state'] == 'unreadable'


def test_in_memory_check_reuses_exact_written_text_and_rechecks_changed_file(tmp_path, monkeypatch):
    out = tmp_path / 'out'
    (out / 'events').mkdir(parents=True)
    cache = tmp_path / 'cache.json'
    names = ['Zorbel Quillfeather']
    observed = X.BlocklistWrites(out, names, cache)
    good, bad = out / 'events/a.json', out / 'events/b.json'
    for p, text in [(good, '{"text":"river"}'), (bad, '{"text":"Zorbel Quillfeather"}')]:
        p.write_text(text)
        observed.observe(p, text)
    original = type(out).read_text
    read = []

    def counted(p, *args, **kwargs):
        read.append(p)
        return original(p, *args, **kwargs)

    monkeypatch.setattr(type(out), 'read_text', counted)
    stats = {}
    assert X.blocklist_hits(out, names, cache, observed=observed, stats=stats) == ['events/b.json']
    assert good not in read and bad not in read and stats['in_memory'] == 2
    good.write_text('{"text":"Zorbel Quillfeather"}')
    read.clear()
    assert X.blocklist_hits(out, names, cache, observed=observed) == ['events/a.json', 'events/b.json']
    assert good in read and bad not in read
    read.clear()
    assert X.blocklist_hits(out, names + ['river'], cache, observed=observed) == ['events/a.json', 'events/b.json']
    assert good in read and bad in read
    bad.unlink()
    assert X.blocklist_hits(out, names, cache, observed=observed) == ['events/a.json']


def test_same_size_replacement_does_not_reuse_in_memory_result(tmp_path):
    import os
    names = ['Zorbel']
    p = tmp_path / 'events.json'
    p.write_text('river!')
    before = p.stat()
    observed = X.BlocklistWrites(tmp_path, names)
    observed.observe(p, 'river!')
    replacement = tmp_path / 'replacement'
    replacement.write_text('Zorbel')
    os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
    replacement.replace(p)
    assert X.blocklist_hits(tmp_path, names, observed=observed) == ['events.json']


def test_processes_preserve_order_matches_and_cache(tmp_path):
    for d in ['waters', 'events', X.REACH_STATE_DIR]:
        (tmp_path / d).mkdir()
    for i in range(520):
        (tmp_path / 'events' / f'{i:03}.json').write_text('Zorbel Quillfeather' if i % 31 == 0 else f'river {i}')
    (tmp_path / X.REACH_STATE_DIR / 'MA.geojson').write_text('Zorbel Quillfeather')
    names = ['Zorbel Quillfeather']
    expected = X.blocklist_hits(tmp_path, names, workers=1)
    cache = tmp_path / 'cache.json'
    assert X.blocklist_hits(tmp_path, names, cache, workers=2) == expected
    assert X.blocklist_hits(tmp_path, names, cache, workers=2) == expected


def test_parallel_writer_observations_and_lifecycle(tmp_path):
    (tmp_path / 'events').mkdir()
    names = ['Zorbel Quillfeather']
    with X.BlocklistWrites(tmp_path, names, workers=2) as observed:
        for i in range(520):
            path = tmp_path / 'events' / f'{i:03}.json'
            text = 'Zorbel Quillfeather' if i % 31 == 0 else f'river {i}'
            path.write_text(text)
            observed.observe(path, text)
        # The final value wins even when observations span pending batches.
        path = tmp_path / 'events/000.json'
        path.write_text('river')
        observed.observe(path, 'river')
    assert observed._pool is None and not observed._pending
    assert X.blocklist_hits(tmp_path, names, observed=observed) == X.blocklist_hits(tmp_path, names)
    assert len(observed.results) == 520


def test_observer_closes_processes_when_writer_raises(tmp_path):
    with pytest.raises(ValueError, match='invented writer failure'):
        with X.BlocklistWrites(tmp_path, ['Zorbel'], workers=2) as observed:
            p = tmp_path / 'events.json'
            p.write_text('river')
            observed.observe(p, 'river')
            raise ValueError('invented writer failure')
    assert observed._pool is None and not observed._pending


def test_wide_alternation_uses_cheap_word_rejection(monkeypatch):
    names = [chr(65 + i) + 'orbel ' + chr(65 + i) + 'vex' + chr(65 + i) for i in range(26)]
    scan = R.BlockScan(names)

    class NoWideSearch:
        def search(self, text):
            pytest.fail('wide alternation ran despite no relevant words')

    monkeypatch.setattr(scan, '_any', NoWideSearch())
    assert scan.found('The crew inspected the treatment facility and restored flow.') == []
