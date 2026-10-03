"""Request/response shapes for POST /farms/{id}/ask -- see
app/services/advisor_service.py."""

from datetime import date, datetime

from pydantic import BaseModel, Field


class AdvisorAskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    # BCP-47-ish tag or plain language name ("en", "hi", "Hindi", "bn"...),
    # passed straight through to the model's system instruction.
    language: str = "en"


class AdvisorLLMOutput(BaseModel):
    """Exact shape requested from Gemini -- see
    AdvisorService._SYSTEM_INSTRUCTION. `sources_used` is re-validated
    against the context modules actually sent (AdvisorService._finalize)
    before it ever reaches a client, so the model can't claim a source that
    wasn't in its prompt."""

    answer: str
    action_points: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    sources_used: list[str] = Field(default_factory=list)


class AdvisorSourceOut(BaseModel):
    module: str
    label: str
    as_of: date | None


class AdvisorAskResponse(BaseModel):
    answer: str
    action_points: list[str]
    warnings: list[str]
    sources_used: list[AdvisorSourceOut]
    language: str
    # True when GEMINI_API_KEYS is empty (or every key failed) and this was
    # answered by the scripted, non-LLM fallback instead.
    is_scripted_fallback: bool
    generated_at: datetime
