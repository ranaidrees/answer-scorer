"""Request, response and model-output shapes (spec FR-1, FR-4 step 6, FR-5).

The request is identity-blind: it has no name, gender, age, ethnicity, nationality or
photo field, and unknown fields are rejected. Length limits (the answer's and the
question's) are checked in the pipeline, so that a breach returns a named 400 code and is
never silently truncated.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

NOTICE = "Decision support only. A trained person makes the decision."


class ScoreRequest(BaseModel):
    """Body of `POST /api/score`. `candidate_ref` is opaque and never reaches the model."""

    model_config = ConfigDict(extra="forbid")

    competency_id: str
    question: str
    answer: str
    candidate_ref: str | None = None


class EvidenceItem(BaseModel):
    quote: str
    grounded: bool


class Flags(BaseModel):
    injection_detected: bool = False
    hidden_text_removed: bool = False
    platform_guardrail: bool = False
    ungrounded_quotes: int = 0
    inconsistent: bool = False
    off_topic: bool = False
    rationale_protected_term: bool = False


class ScoreResponse(BaseModel):
    # `model_deployment` is a field name from the spec, not a pydantic method.
    model_config = ConfigDict(protected_namespaces=())

    request_id: str
    competency_id: str
    score: int | None
    level_label: str | None
    rationale: str
    evidence: list[EvidenceItem]
    runs: list[int]
    spread: int | None
    needs_human_review: bool
    review_reasons: list[str]
    flags: Flags
    prompt_version: str
    model_deployment: str
    trace_id: str | None = None
    notice: str = NOTICE


class ModelOutput(BaseModel):
    """One model run. Strict: a string "4" or an extra field is not a valid output."""

    model_config = ConfigDict(extra="forbid", strict=True)

    score: Literal[1, 2, 3, 4, 5]
    rationale: str
    evidence: list[str]
    off_topic: bool

    @field_validator("score", mode="before")
    @classmethod
    def _score_is_a_plain_integer(cls, value: object) -> object:
        # `True == 1` and `4.0 == 4` in Python, so a literal check alone would accept them.
        if type(value) is not int:
            raise ValueError("score must be an integer from 1 to 5")
        return value


# The strict JSON schema sent to the model. Strict mode has no `minimum` or `maximum`, so
# the score is an integer enum. Evidence and rationale come before the score so that the
# model writes its quotes and reasons first (decision S2-3).
MODEL_OUTPUT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "evidence": {"type": "array", "items": {"type": "string"}},
        "rationale": {"type": "string"},
        "off_topic": {"type": "boolean"},
        "score": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
    },
    "required": ["evidence", "rationale", "off_topic", "score"],
    "additionalProperties": False,
}
