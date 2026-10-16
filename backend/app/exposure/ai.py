from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.exposure.detectors import ai_safe_text, has_operational_routine, has_precise_address, normalize_text


class ContentSignal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: Literal[
        "location_disclosure",
        "temporal_exposure",
        "education_work_context",
        "biographical_identifiers",
        "content_disclosure",
    ]
    severity: Literal["high", "medium", "low", "informational"]
    basis: Literal["observed"] = "observed"
    evidence_excerpt: str = Field(min_length=1, max_length=280)


class ContentBatchItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_id: str = Field(min_length=1, max_length=100)
    signals: list[ContentSignal] = Field(default_factory=list, max_length=8)


class ContentBatchOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signals: list[ContentBatchItem] = Field(default_factory=list, max_length=20)


class _RawContentSignal(BaseModel):
    """Typed envelope that lets the filter discard unknown model categories individually."""
    model_config = ConfigDict(extra="allow")

    category: str = Field(min_length=1, max_length=80)
    severity: str = Field(min_length=1, max_length=24)
    basis: str = Field(min_length=1, max_length=24)
    evidence_excerpt: str = Field(min_length=1, max_length=280)


class _RawContentBatchItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_id: str = Field(min_length=1, max_length=100)
    signals: list[_RawContentSignal] = Field(default_factory=list, max_length=8)


class _RawContentBatchOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signals: list[_RawContentBatchItem] = Field(default_factory=list, max_length=20)


SYSTEM_PROMPT = """Only analyze publicly observable privacy exposure in the supplied, already-attributed text.
Do not infer sensitive personal traits.
Do not infer exact home addresses.
Do not produce schedules or actionable routine predictions.
Do not identify relatives.
Do not perform social engineering.
Only use supplied evidence; excerpts must be verbatim substrings.
Return only structured signals with basis observed. Allowed categories are location_disclosure,
temporal_exposure, education_work_context, biographical_identifiers, and content_disclosure.
Never return sensitive categories such as political_belief, health, religion, sexual_orientation,
or ethnicity. Never include a precise address, a time, a route, or a routine in an excerpt.
"""


def _message_text(response) -> str:
    choices = getattr(response, "choices", None) or []
    if not choices:
        raise ValueError("Exposure AI returned no choices.")
    message = getattr(choices[0], "message", None)
    if message is None:
        raise ValueError("Exposure AI response has no message.")
    parsed = getattr(message, "parsed", None)
    if isinstance(parsed, ContentBatchOutput):
        return parsed.model_dump_json()
    if isinstance(parsed, dict):
        return json.dumps(parsed)
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content
    raise ValueError("Exposure AI response has no structured JSON content.")


async def classify_batch(model: str, items: list[dict], max_chars_per_item: int = 6000) -> dict[str, list[dict]]:
    """Classify a bounded batch. Ownership and subject attribution are never model decisions."""
    import litellm

    bounded = [
        {
            "content_id": str(item["content_id"]),
            "content_type": str(item.get("content_type") or "public text")[:40],
            "text": ai_safe_text(str(item.get("text") or ""), max_chars_per_item),
        }
        for item in items
    ]
    response = await litellm.acompletion(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps({"items": bounded}, ensure_ascii=False)},
        ],
        response_format=ContentBatchOutput,
        temperature=0,
        timeout=25,
        max_tokens=2500,
    )
    raw = _RawContentBatchOutput.model_validate(json.loads(_message_text(response)))

    allowed_text = {
        str(item["content_id"]): normalize_text(ai_safe_text(str(item.get("text") or ""), max_chars_per_item))
        for item in items
    }
    accepted: dict[str, list[dict]] = {key: [] for key in allowed_text}
    for raw_item in raw.signals:
        content_id = raw_item.content_id
        if not isinstance(content_id, str) or content_id not in allowed_text:
            continue
        for candidate in raw_item.signals:
            try:
                signal = ContentSignal.model_validate(candidate.model_dump())
            except (ValidationError, TypeError, ValueError):
                # Unknown or sensitive categories, inferred bases, and extra
                # fields are discarded item-by-item; they never enter the report.
                continue
            excerpt = normalize_text(signal.evidence_excerpt)
            if has_precise_address(excerpt) or has_operational_routine(excerpt):
                continue
            if excerpt not in allowed_text[content_id]:
                continue
            accepted[content_id].append(signal.model_copy(update={"evidence_excerpt": excerpt}).model_dump(mode="json"))
    return accepted
