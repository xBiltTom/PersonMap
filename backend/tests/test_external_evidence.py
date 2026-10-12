"""External observations cannot spoof collector metadata or promote snippets into facts."""
from datetime import datetime, timezone, timedelta

import pytest
from pydantic import ValidationError

from app.schemas.external_evidence import ExternalEvidence, ExternalEvidenceBatch


def record(**overrides):
    return {"entity_type": "document", "url": "https://example.test/roll", "source_url": "https://example.test/roll",
        "title": "Public roll", "acquisition_method": "agent_browser", "evidence_level": "page_content",
        "observed_at": datetime.now(timezone.utc), "excerpt": "PÉREZ ROJAS, ANA MARÍA — Ingeniería", **overrides}


def test_grounded_identifiers_preserve_full_names_without_trusting_identity():
    evidence = ExternalEvidence(**record(identifiers=[{"kind": "name", "value": "Pérez Rojas Ana María"}]))
    assert evidence.identifiers[0].kind == "name"
    for extra in ({"metadata_info": {"verification_status": "verified"}}, {"confidence": 1},
                  {"identifiers": [{"kind": "username", "value": "unseen_alias"}]}):
        with pytest.raises(ValidationError):
            ExternalEvidence(**record(**extra))


@pytest.mark.parametrize("extra", [
    {"source_url": "http://127.0.0.1/private"}, {"url": "https://example.test/?api_key=secret"},
    {"observed_at": datetime.now()}, {"observed_at": datetime.now(timezone.utc) + timedelta(days=1)},
    {"acquisition_method": "agent_search"}, {"observed_links": ["https://example.test/unseen"]},
    {"url": "https://example.test/unseen"}])
def test_invalid_provenance_is_rejected(extra):
    with pytest.raises(ValidationError):
        ExternalEvidence(**record(**extra))


def test_search_snippet_stays_separate_from_page_identifiers():
    data = record(acquisition_method="agent_search", evidence_level="search_result")
    assert ExternalEvidence(**data).evidence_level == "search_result"
    with pytest.raises(ValidationError):
        ExternalEvidence(**{**data, "identifiers": [{"kind": "name", "value": "Pérez Rojas Ana María"}]})


def test_import_batch_is_bounded_and_rejects_identical_records():
    evidence = ExternalEvidence(**record())
    for rows in ([], [evidence]*2, [evidence]*11):
        with pytest.raises(ValidationError):
            ExternalEvidenceBatch(rationale="Import public record", records=rows)
