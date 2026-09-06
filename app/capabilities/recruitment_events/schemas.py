from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        serialize_by_alias=True,
        extra="forbid",
    )


NonBlankText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class SourceChannel(StrEnum):
    EMAIL = "EMAIL"
    SMS = "SMS"
    PHONE_NOTE = "PHONE_NOTE"
    RECRUITMENT_PLATFORM = "RECRUITMENT_PLATFORM"
    OTHER = "OTHER"


class ApplicationStage(StrEnum):
    APPLIED = "APPLIED"
    ASSESSMENT = "ASSESSMENT"
    INTERVIEW = "INTERVIEW"
    OFFER = "OFFER"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class TaskType(StrEnum):
    ASSESSMENT = "ASSESSMENT"
    INTERVIEW = "INTERVIEW"
    MATERIAL = "MATERIAL"
    CUSTOM = "CUSTOM"


class EventType(StrEnum):
    APPLICATION_ACKNOWLEDGED = "APPLICATION_ACKNOWLEDGED"
    ASSESSMENT = "ASSESSMENT"
    INTERVIEW = "INTERVIEW"
    OFFER = "OFFER"
    REJECTION = "REJECTION"
    MATERIAL_REQUEST = "MATERIAL_REQUEST"
    OTHER = "OTHER"


class Confidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class MatchStatus(StrEnum):
    MATCHED = "MATCHED"
    AMBIGUOUS = "AMBIGUOUS"
    UNMATCHED = "UNMATCHED"


class TimelineEventType(StrEnum):
    STAGE_CHANGE = "STAGE_CHANGE"
    NOTE = "NOTE"


class RecruitmentSource(ApiModel):
    channel: SourceChannel
    subject: str | None = Field(default=None, max_length=500)
    content: NonBlankText = Field(max_length=20_000)
    received_at: datetime

    @field_validator("received_at")
    @classmethod
    def received_at_must_include_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("receivedAt must include a timezone offset")
        return value


class ApplicationCandidate(ApiModel):
    application_id: NonBlankText = Field(max_length=128)
    application_version: int = Field(ge=1)
    job_code: NonBlankText = Field(max_length=128)
    company_name: NonBlankText = Field(max_length=255)
    company_aliases: list[NonBlankText] = Field(default_factory=list, max_length=10)
    job_title: NonBlankText = Field(max_length=255)
    current_stage: ApplicationStage


class AnalyzeRecruitmentEventRequest(ApiModel):
    source: RecruitmentSource
    timezone: str = Field(default="Asia/Shanghai", min_length=1, max_length=64)
    candidates: list[ApplicationCandidate] = Field(min_length=1, max_length=30)

    @field_validator("timezone")
    @classmethod
    def timezone_must_be_valid(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("timezone must be a valid IANA timezone") from exc
        return value

    @field_validator("candidates")
    @classmethod
    def candidate_ids_must_be_unique(
        cls, value: list[ApplicationCandidate]
    ) -> list[ApplicationCandidate]:
        application_ids = [candidate.application_id for candidate in value]
        if len(set(application_ids)) != len(application_ids):
            raise ValueError("candidate applicationId values must be unique")
        return value


class TextFact(ApiModel):
    value: str | None
    confidence: Confidence
    evidence: str | None = Field(max_length=500)


class EventTypeFact(ApiModel):
    value: EventType | None
    confidence: Confidence
    evidence: str | None = Field(max_length=500)


class StageFact(ApiModel):
    value: ApplicationStage | None
    confidence: Confidence
    evidence: str | None = Field(max_length=500)


class DateTimeFact(ApiModel):
    value: datetime | None
    confidence: Confidence
    evidence: str | None = Field(max_length=500)
    inferred: bool

    @field_validator("value")
    @classmethod
    def value_must_include_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("extracted datetime must include a timezone offset")
        return value


class NextActionValue(ApiModel):
    task_type: TaskType
    title: NonBlankText = Field(max_length=255)
    due_at: datetime | None

    @field_validator("due_at")
    @classmethod
    def due_at_must_include_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("next action dueAt must include a timezone offset")
        return value


class NextActionFact(ApiModel):
    value: NextActionValue | None
    confidence: Confidence
    evidence: str | None = Field(max_length=500)


class RecruitmentFacts(ApiModel):
    company_name: TextFact
    job_title: TextFact
    event_type: EventTypeFact
    recruitment_stage: StageFact
    scheduled_at: DateTimeFact
    deadline_at: DateTimeFact
    next_action: NextActionFact
    summary: str = Field(min_length=1, max_length=500)


class MatchCandidateResult(ApiModel):
    application_id: str
    job_code: str
    confidence: Confidence
    evidence: str | None


class MatchResult(ApiModel):
    status: MatchStatus
    selected: MatchCandidateResult | None
    candidates: list[MatchCandidateResult]


class StageChangeDraft(ApiModel):
    from_stage: ApplicationStage
    to_stage: ApplicationStage


class TimelineEventDraft(ApiModel):
    event_type: TimelineEventType
    occurred_at: datetime
    from_stage: ApplicationStage | None
    to_stage: ApplicationStage | None
    note: str


class TaskDraft(ApiModel):
    task_type: TaskType
    title: str
    due_at: datetime
    remind_at: datetime | None = None


class ProposedChange(ApiModel):
    application_id: str
    expected_version: int
    job_code: str
    stage_change: StageChangeDraft | None
    timeline_event: TimelineEventDraft
    task: TaskDraft | None


class AnalyzeRecruitmentEventResponse(ApiModel):
    analysis_id: str
    source_fingerprint: str
    match: MatchResult
    facts: RecruitmentFacts
    proposed_change: ProposedChange | None
    requires_confirmation: Literal[True] = True
    warnings: list[str]


# The following models are deliberately separate from the HTTP response. They are
# the only structure the model is asked to produce; identifiers and mutations are
# validated and rebuilt by deterministic application code afterwards.
class ModelMatch(ApiModel):
    application_id: str = Field(max_length=128)
    confidence: Confidence
    evidence: str | None = Field(max_length=500)


class ModelAnalysis(ApiModel):
    matches: list[ModelMatch] = Field(max_length=30)
    facts: RecruitmentFacts
