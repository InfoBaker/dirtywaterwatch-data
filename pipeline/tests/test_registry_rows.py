from build import status as S


def test_registry_rows_follow_meta_and_the_feed_yamls_own_registry_ids():
    registry = {
        "pa-alcosan": {"id": "pa-alcosan", "registry_ids": ["pa-alcosan-soak-log", "pa-alcosan-news-advisories"]},
        "pa-alcosan-soak-log": {"id": "pa-alcosan-soak-log"},
        "pa-alcosan-news-advisories": {"id": "pa-alcosan-news-advisories"},
        "pa-alcosan-from-meta": {"id": "pa-alcosan-from-meta"},
    }
    got = [r["id"] for r in S.registry_rows("pa-alcosan", {"registry_ids": ["pa-alcosan-from-meta"]}, registry)]
    assert got == ["pa-alcosan", "pa-alcosan-from-meta", "pa-alcosan-soak-log", "pa-alcosan-news-advisories"]
    # unknown ids and a missing own yaml are skipped, not errors
    assert [r["id"] for r in S.registry_rows("no-such-feed", {"registry_ids": ["pa-alcosan-soak-log", "x"]}, registry)] == ["pa-alcosan-soak-log"]
