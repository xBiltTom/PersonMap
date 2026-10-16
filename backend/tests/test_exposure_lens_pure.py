import json
from types import SimpleNamespace

import pytest

from app.exposure.ai import SYSTEM_PROMPT, classify_batch
from app.exposure.detectors import ai_safe_text, exact_emails, exact_phones, has_operational_routine, safe_excerpt
from app.services.exposure_lens import _safe_report_text, _safe_url, dataset_hash


def test_dataset_hash_ignores_volatile_review_timestamp_but_tracks_decision_change():
    reviewed = {
        "accounts": [{"username": "shared", "ownership": {"status": "subject_confirmed"}}],
        "review": {"confirmed": [{"entity_id": "e-1", "decision": "confirmed", "decided_at": "2026-10-01T10:00:00Z"}]},
        "execution": {"reviewed_at": "2026-10-01T10:00:00Z", "source_mode": "fair"},
    }
    same_content_next_day = {
        "accounts": [{"username": "shared", "ownership": {"status": "subject_confirmed"}}],
        "review": {"confirmed": [{"entity_id": "e-1", "decision": "confirmed", "decided_at": "2026-10-02T10:00:00Z"}]},
        "execution": {"reviewed_at": "2026-10-02T10:00:00Z", "source_mode": "fair"},
    }
    rejected = {
        "accounts": [],
        "review": {"rejected": [{"entity_id": "e-1", "decision": "rejected", "decided_at": "2026-10-02T10:00:00Z"}]},
        "execution": {"reviewed_at": "2026-10-02T10:00:00Z", "source_mode": "fair"},
    }
    assert dataset_hash(reviewed) == dataset_hash(same_content_next_day)
    assert dataset_hash(reviewed) != dataset_hash(rejected)


def test_contact_extractors_find_exact_public_email_and_phone():
    text = "Contact me at public@example.org or +51 912 345 678."
    assert exact_emails(text) == ["public@example.org"]
    assert exact_phones(text) == ["+51912345678"]
    assert exact_phones("Published at 2026-10-16T17:32:00Z") == []


def test_address_and_routine_excerpts_are_generalized():
    address = "Nos vemos en Av. Los Olivos 123, tercer piso."
    routine = "I visit Lima every Tuesday at 8:15 am."
    assert "123" not in safe_excerpt(address)
    assert "Los Olivos" not in safe_excerpt(address)
    assert "8:15" not in safe_excerpt(routine)
    assert "referencias temporales repetidas" in safe_excerpt(routine)
    assert "Av. Los Olivos" not in ai_safe_text(address + " " + routine, 1000)
    assert "Tuesday at 8" not in ai_safe_text(address + " " + routine, 1000)


def test_less_common_schedule_and_family_references_are_not_reproduced():
    schedule = "Meet me Tuesdays and Thursdays 8am near campus."
    family = "My sister Elena studies at the university with me."
    assert has_operational_routine(schedule)
    assert "Thursday" not in safe_excerpt(schedule)
    assert "8am" not in ai_safe_text(schedule, 1000)
    assert "Thursday" not in ai_safe_text(schedule, 1000)
    assert "sister" not in safe_excerpt(family).lower()
    assert "Elena" not in ai_safe_text(family, 1000)


def test_report_metadata_redacts_addresses_but_keeps_contact_evidence():
    assert "Los Olivos 123" not in _safe_report_text("Av. Los Olivos 123 is in the source.")
    assert "health" not in _safe_report_text("Health is mentioned in a profile title.").lower()
    assert _safe_url("https://example.org/Av.%20Los%20Olivos%20123") is None
    assert "public@example.org" in _safe_report_text("Public email: public@example.org")


@pytest.mark.asyncio
async def test_ai_structured_output_discards_sensitive_and_actionable_signals(monkeypatch):
    text = "I visit Lima tomorrow; every Tuesday at 8 and Av. Los Olivos 123. My sister Ana is here."
    unsafe_response = {
        "signals": [{
            "content_id": "unit-1",
            "signals": [
                {
                    "category": "location_disclosure",
                    "severity": "medium",
                    "basis": "observed",
                    "evidence_excerpt": "I visit Lima tomorrow",
                },
                {
                    "category": "political_belief",
                    "severity": "high",
                    "basis": "inferred",
                    "evidence_excerpt": "The person is politically active",
                },
                {
                    "category": "temporal_exposure",
                    "severity": "high",
                    "basis": "observed",
                    "evidence_excerpt": "every Tuesday at 8",
                },
                {
                    "category": "location_disclosure",
                    "severity": "high",
                    "basis": "observed",
                    "evidence_excerpt": "Av. Los Olivos 123",
                },
            ],
        }],
    }

    async def fake_completion(**kwargs):
        assert "Only analyze publicly observable privacy exposure" in kwargs["messages"][0]["content"]
        assert "Do not infer sensitive personal traits" in kwargs["messages"][0]["content"]
        assert "Do not produce schedules" in kwargs["messages"][0]["content"]
        sent = json.loads(kwargs["messages"][1]["content"])["items"][0]["text"]
        assert "Los Olivos 123" not in sent and "Tuesday at 8" not in sent
        assert "sister" not in sent.lower() and "Ana" not in sent
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content=json.dumps(unsafe_response)
        ))])

    import litellm
    monkeypatch.setattr(litellm, "acompletion", fake_completion)
    result = await classify_batch("fixture/model", [{
        "content_id": "unit-1", "content_type": "social_post", "text": text,
    }])
    assert [item["category"] for item in result["unit-1"]] == ["location_disclosure"]
    assert "123" not in json.dumps(result)
    assert "Tuesday at 8" not in json.dumps(result)
    assert "sister" not in json.dumps(result).lower() and "Ana" not in json.dumps(result)
    assert "political" not in json.dumps(result).lower()
