"""The notice-channel register in two layouts (docs/national-approach.md §4.2 and §7 item 1): the single file
data/notice-channels.json or one file per state data/notice-channels/<st>.json. One loader, one validator per file
and across files, `--split` from the first to the second, `--validate` on both."""
import json
import shutil
from pathlib import Path

import pytest

from export import coverage as C
from ingest import notification_pages as M

ROOT = Path(__file__).resolve().parents[2]
DIS = json.loads((ROOT / "data" / "dischargers.json").read_text())


def row(rid, state, **kw):
    r = {"id": rid, "state": state, "operator_id": None, "agency": "Some Agency", "name": "Some Agency",
         "permit": None, "channel_kind": "operator_page", "urls": [f"https://example.org/{rid}"], "method": "html",
         "legal_basis": None, "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None,
         "publishes": "notices", "note": None, "checked": "2026-11-04", "barrier": None}
    r.update(kw)
    return r


ROWS = [row("nj-b-page", "NJ"), row("nj-a-page", "NJ"), row("pa-a-page", "PA"),
        row("pa-z-list", "PA", monitored=False, urls=[], method=None, unmonitored_reason="email_only",
            barrier="no_web_page")]


def single(tmp_path, rows=ROWS) -> Path:
    p = tmp_path / "data" / "notice-channels.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(rows, key=lambda r: (str(r["state"]), r["id"]))
    p.write_text(json.dumps({"about": M.ABOUT, "schema_version": 1, "schema": M.SCHEMA, "channels": rows}, indent=1))
    return p


def test_split_writes_one_sorted_file_per_state_and_removes_the_single_file(tmp_path):
    p = single(tmp_path)
    before = M.load_register(p)["channels"]
    assert M.register_layout(p) == "single"
    assert M.split_register(p) == {"NJ": 2, "PA": 2}
    folder = tmp_path / "data" / "notice-channels"
    assert not p.exists() and sorted(x.name for x in folder.iterdir()) == ["_schema.json", "nj.json", "pa.json"]
    nj = json.loads((folder / "nj.json").read_text())
    assert nj["state"] == "NJ" and [r["id"] for r in nj["channels"]] == ["nj-a-page", "nj-b-page"]   # sorted by id
    assert json.loads((folder / "_schema.json").read_text())["schema"] == json.loads(json.dumps(M.SCHEMA))
    doc = M.load_register(folder)
    assert doc["channels"] == before and doc["layout"] == "per_state"
    assert doc["files"] == {"notice-channels/nj.json": 2, "notice-channels/pa.json": 2}
    assert M.register_layout(folder) == "per_state"


def test_validate_works_on_both_layouts(tmp_path):
    p = single(tmp_path)
    assert M.validate_layout(p, DIS) == []
    M.split_register(p)
    assert M.validate_layout(tmp_path / "data" / "notice-channels", DIS) == []


def test_the_split_of_todays_register_validates_and_reads_back_the_same(tmp_path):
    # the real register (single file today) split in a copy: the coordinator runs the split on data/ after merges
    src = M.REGISTER if M.REGISTER.exists() else None
    if src is None:
        pytest.skip("data/notice-channels.json is already split")
    p = tmp_path / "notice-channels.json"
    shutil.copy(src, p)
    rows = M.load_register(p)["channels"]
    counts = M.split_register(p)
    folder = tmp_path / "notice-channels"
    assert sum(counts.values()) == len(rows) and not p.exists()
    assert M.load_register(folder)["channels"] == sorted(rows, key=lambda r: (r["state"], r["id"]))
    assert M.validate_layout(folder, DIS, ROOT) == []


def test_split_refuses_and_writes_nothing(tmp_path):
    with pytest.raises(ValueError, match="does not exist"):
        M.split_register(tmp_path / "data" / "notice-channels.json")
    p = single(tmp_path, ROWS + [row("xx-bad", None)])
    with pytest.raises(ValueError, match="without a state code"):
        M.split_register(p)
    assert p.exists() and not (tmp_path / "data" / "notice-channels").exists()
    p = single(tmp_path)
    (tmp_path / "data" / "notice-channels").mkdir()
    (tmp_path / "data" / "notice-channels" / "nj.json").write_text("{}")
    with pytest.raises(ValueError, match="already has files"):
        M.split_register(p)
    assert p.exists()


def test_a_split_that_stopped_before_removing_the_single_file_is_finished_not_refused(tmp_path):
    # the state files are written and checked first, the single file removed last: a death in between leaves both
    # layouts, and the next --split removes the single file when the folder holds exactly its rows
    p = single(tmp_path)
    folder = tmp_path / "data" / "notice-channels"
    M.save_register(ROWS, folder)
    assert M.register_layout(p) == "single" and folder.is_dir()
    assert M.split_register(p) == {"NJ": 2, "PA": 2}
    assert not p.exists() and M.validate_layout(folder, DIS) == []
    # but not when the folder's rows differ from the file's: the rows the folder lacks would be lost
    p = single(tmp_path)
    (folder / "pa.json").unlink()
    with pytest.raises(ValueError, match="not this file's rows"):
        M.split_register(p)
    assert p.exists() and (folder / "nj.json").exists()


def write_state(folder: Path, name: str, doc) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(json.dumps(doc))


def test_the_per_state_validator_catches_each_kind_of_mistake(tmp_path):
    f = tmp_path / "notice-channels"
    write_state(f, "nj.json", M.state_doc("NJ", [row("nj-a-page", "NJ"), row("pa-a-page", "PA")]))   # wrong file
    write_state(f, "pa.json", {**M.state_doc("PA", []), "channels": [row("pa-z", "PA"), row("pa-a-page", "PA")]})
    write_state(f, "ny.json", {**M.state_doc("NY", [row("ny-a", "NY")]), "state": "NJ"})              # file's state
    write_state(f, "NJ-draft.json", M.state_doc("NJ", []))                                            # name
    write_state(f, "zz.json", M.state_doc("NJ", []))                                                  # not a state
    errs = M.validate_layout(f, DIS)
    text = "\n".join(errs)
    assert "notice-channels/nj.json: channels[1] (pa-a-page): state 'PA' belongs in pa.json" in text
    assert "notice-channels/pa.json: channels[1] (pa-a-page): duplicate id, also in notice-channels/nj.json" in text
    assert "notice-channels/pa.json: channels are not sorted by (state, id)" in text
    assert "notice-channels/ny.json: state is 'NJ', not 'NY'" in text
    assert "notice-channels/NJ-draft.json: a state file is named <st>.json" in text
    assert "notice-channels/zz.json: a state file is named <st>.json" in text
    # each file still goes through the row validator, its errors named by the file
    write_state(f, "ct.json", M.state_doc("CT", [row("ct-a", "CT", channel_kind="website")]))
    assert any(e.startswith("notice-channels/ct.json: channels[0] (ct-a): channel_kind") for e in M.validate_layout(f, DIS))


def test_both_layouts_at_once_load_every_row_and_fail_validation(tmp_path):
    p = single(tmp_path, [row("nj-a-page", "NJ")])
    write_state(tmp_path / "data" / "notice-channels", "pa.json", M.state_doc("PA", [row("pa-a-page", "PA")]))
    write_state(tmp_path / "data" / "notice-channels", "nj.json", M.state_doc("NJ", [row("nj-a-page", "NJ")]))
    import ingest.notification_pages as mod
    old = (mod.REGISTER, mod.REGISTER_DIR)
    try:
        mod.REGISTER, mod.REGISTER_DIR = p, tmp_path / "data" / "notice-channels"
        assert M.register_layout() == "both"
        assert [r["id"] for r in M.load_register()["channels"]] == ["nj-a-page", "nj-a-page", "pa-a-page"]
        errs = M.validate_layout(None, DIS)
        assert errs[0].startswith("both notice-channels.json and notice-channels/ exist")
        assert any("duplicate id, also in notice-channels.json" in e for e in errs)
        with pytest.raises(ValueError, match="merge them first"):
            M.save_register(M.load_register()["channels"])
    finally:
        mod.REGISTER, mod.REGISTER_DIR = old


def test_barriers_and_schema_write_in_the_layout_the_register_has(tmp_path):
    p = single(tmp_path)
    M.split_register(p)
    folder = tmp_path / "data" / "notice-channels"
    doc = json.loads((folder / "pa.json").read_text())
    doc["channels"][1].update(barrier=None, barrier_review="not settled yet")
    (folder / "pa.json").write_text(json.dumps(doc))
    counts = M.apply_barriers(folder)
    assert counts == {"none": 3, "no_web_page": 1} and not p.exists()
    pa = json.loads((folder / "pa.json").read_text())["channels"]
    assert [r.get("barrier") for r in pa] == [None, "no_web_page"] and "barrier_review" not in pa[1]
    # a state whose last row goes loses its file; the rest are rewritten sorted
    M.save_register([r for r in M.load_register(folder)["channels"] if r["state"] != "NJ"], folder)
    assert sorted(x.name for x in folder.iterdir()) == ["_schema.json", "pa.json"]
    assert M.write_schema(folder)["channels"] == pa


def test_the_command_line_validates_and_splits(tmp_path, capsys):
    p = single(tmp_path)
    assert M.main(["--validate", "--register", str(p)]) == 0
    assert "valid (single), 4 channels" in capsys.readouterr().out
    assert M.main(["--split", "--register", str(p)]) == 0
    assert "4 channels in 2 state files (NJ 2, PA 2); the single file is removed" in capsys.readouterr().out
    folder = tmp_path / "data" / "notice-channels"
    assert M.main(["--validate", "--register", str(folder)]) == 0
    assert "valid (per_state), 4 channels" in capsys.readouterr().out
    assert M.main(["--split", "--register", str(p)]) == 1                 # nothing left to split
    write_state(folder, "ny.json", M.state_doc("NY", [row("nj-a-page", "NY")]))
    assert M.main(["--validate", "--register", str(folder)]) == 1


def test_the_coverage_export_reads_either_layout(tmp_path):
    p = single(tmp_path)
    assert [r["id"] for r in C.load_register(p)["channels"]] == [r["id"] for r in M.load_register(p)["channels"]]
    M.split_register(p)
    assert len(C.load_register(tmp_path / "data" / "notice-channels")["channels"]) == 4
    assert C.load_register(tmp_path / "nothing-here") is None
