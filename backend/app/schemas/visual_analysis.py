"""Client-authored visual interpretation, with explicit media provenance."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class VisualObservation(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    media_id: str = Field(pattern=r'^[a-f0-9]{64}$')
    kind: Literal['visible_text', 'academic_or_work', 'logo_or_badge', 'location_clue',
                  'contact_or_identifier', 'document_or_screen', 'other']
    region: str = Field(min_length=3, max_length=160)
    observation: str = Field(min_length=10, max_length=700)
    visible_text: str = Field(default='', max_length=700)
    why_it_matters: str = Field(min_length=10, max_length=700)
    recommendation: str = Field(min_length=10, max_length=500)


class PostVisualAnalysis(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    post_id: str = Field(min_length=1, max_length=256)
    dataset_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    summary: str = Field(min_length=30, max_length=2000)
    severity: Literal['high', 'medium', 'low', 'informational']
    observations: list[VisualObservation] = Field(min_length=1, max_length=8)
    inferences: list[str] = Field(default_factory=list, max_length=5)
    limitations: list[str] = Field(min_length=1, max_length=5)

    # Per-string bounds keep authored notes below the shared workspace JSON limit.
    @field_validator('inferences', 'limitations')
    @classmethod
    def bounded_items(cls, values):
        if any(not value.strip() or len(value) > 700 for value in values):
            raise ValueError('Usa afirmaciones de 1 a 700 caracteres.')
        return values
