"""Merged readers declare downloaded contact fields for the report-page distinction."""
from pathlib import Path
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]

@pytest.mark.parametrize("source,kind,keys", [
    ("fl-miami-dade-sso", "reporter_contact", {"RPTNAME", "RPTPHONE"}),
    ("mi-egle-mienviro-cso-sso-list", "reporter_contact", {"contactName", "contactPhone"}),
    ("tn-tdec-events-report", "reporter_contact", {"contact_email"}),
    ("tx-tceq-sso-opendata", "customer_identifier", {"customer_number"}),
    ("nc-dwr-sso-2026", "reporter_contact", {"submitter_name", "reporter"}),
])
def test_retained_contact_and_customer_keys_are_declared(source, kind, keys):
    doc = yaml.safe_load((ROOT / "data/sources" / (source + ".yaml")).read_text())
    assert keys <= set(doc["raw_fields"][kind])


def test_default_name_review_is_retired():
    assert not (ROOT / "pipeline/build/name_review.py").exists()
    assert "build.name_review" not in (ROOT / "scripts/refresh-data.sh").read_text()
    assert "build.name_review" not in (ROOT / ".github/workflows/refresh.yml").read_text()


def test_default_blocklist_scanner_is_retired():
    from build import redact
    from export import build
    assert not hasattr(redact, "BlockScan")
    assert not hasattr(build, "BlocklistWrites")
    assert not hasattr(build, "blocklist_hits")
