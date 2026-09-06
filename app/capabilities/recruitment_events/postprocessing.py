import hashlib
import unicodedata
from collections.abc import Callable
from datetime import UTC, datetime

from app.capabilities.recruitment_events.schemas import (
    AnalyzeRecruitmentEventRequest,
    AnalyzeRecruitmentEventResponse,
    ApplicationCandidate,
    ApplicationStage,
    Confidence,
    EventType,
    MatchCandidateResult,
    MatchResult,
    MatchStatus,
    ModelAnalysis,
    ProposedChange,
    RecruitmentFacts,
    StageChangeDraft,
    TaskDraft,
    TimelineEventDraft,
    TimelineEventType,
)

Clock = Callable[[], datetime]

_PROGRESS_ORDER = {
    ApplicationStage.APPLIED: 0,
    ApplicationStage.ASSESSMENT: 1,
    ApplicationStage.INTERVIEW: 2,
    ApplicationStage.OFFER: 3,
}
_TERMINAL_STAGES = {ApplicationStage.REJECTED, ApplicationStage.WITHDRAWN}
_EVENT_STAGE = {
    EventType.APPLICATION_ACKNOWLEDGED: ApplicationStage.APPLIED,
    EventType.ASSESSMENT: ApplicationStage.ASSESSMENT,
    EventType.INTERVIEW: ApplicationStage.INTERVIEW,
    EventType.OFFER: ApplicationStage.OFFER,
    EventType.REJECTION: ApplicationStage.REJECTED,
}
_CONFIDENCE_ORDER = {
    Confidence.HIGH: 0,
    Confidence.MEDIUM: 1,
    Confidence.LOW: 2,
}


def utc_now() -> datetime:
    return datetime.now(UTC)


def source_fingerprint(request: AnalyzeRecruitmentEventRequest) -> str:
    subject = request.source.subject or ""
    parts = (
        request.source.channel.value,
        subject,
        request.source.content,
        request.source.received_at.astimezone(UTC).isoformat(),
    )
    normalized = "\n".join(
        " ".join(unicodedata.normalize("NFKC", part).split()).casefold()
        for part in parts
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def build_analysis_response(
    request: AnalyzeRecruitmentEventRequest,
    model_analysis: ModelAnalysis,
    *,
    analysis_id: str,
    clock: Clock = utc_now,
) -> AnalyzeRecruitmentEventResponse:
    warnings: list[str] = []
    facts = _validate_evidence(request, model_analysis.facts, warnings)
    match = _build_match(request, model_analysis, warnings)
    proposed_change = None

    if match.status is MatchStatus.MATCHED and match.selected is not None:
        candidate_by_id = {
            candidate.application_id: candidate for candidate in request.candidates
        }
        candidate = candidate_by_id[match.selected.application_id]
        proposed_change = _build_proposed_change(
            request=request,
            candidate=candidate,
            facts=facts,
            now=clock(),
            warnings=warnings,
        )

    return AnalyzeRecruitmentEventResponse(
        analysis_id=analysis_id,
        source_fingerprint=source_fingerprint(request),
        match=match,
        facts=facts,
        proposed_change=proposed_change,
        requires_confirmation=True,
        warnings=list(dict.fromkeys(warnings)),
    )


def _build_match(
    request: AnalyzeRecruitmentEventRequest,
    model_analysis: ModelAnalysis,
    warnings: list[str],
) -> MatchResult:
    candidate_by_id = {
        candidate.application_id: candidate for candidate in request.candidates
    }
    valid_matches: dict[str, MatchCandidateResult] = {}
    source_text = "\n".join(
        part for part in (request.source.subject, request.source.content) if part
    )

    for model_match in model_analysis.matches:
        candidate = candidate_by_id.get(model_match.application_id)
        if candidate is None:
            warnings.append("MODEL_RETURNED_UNKNOWN_APPLICATION_ID")
            continue
        existing = valid_matches.get(candidate.application_id)
        result = MatchCandidateResult(
            application_id=candidate.application_id,
            job_code=candidate.job_code,
            confidence=model_match.confidence,
            evidence=_exact_evidence(
                model_match.evidence, source_text, warnings
            ),
        )
        if existing is None or _CONFIDENCE_ORDER[result.confidence] < _CONFIDENCE_ORDER[
            existing.confidence
        ]:
            valid_matches[candidate.application_id] = result

    matches = sorted(
        valid_matches.values(), key=lambda item: _CONFIDENCE_ORDER[item.confidence]
    )
    if not matches:
        return MatchResult(
            status=MatchStatus.UNMATCHED, selected=None, candidates=[]
        )
    if len(matches) > 1:
        return MatchResult(
            status=MatchStatus.AMBIGUOUS, selected=None, candidates=matches
        )
    return MatchResult(
        status=MatchStatus.MATCHED, selected=matches[0], candidates=matches
    )


def _validate_evidence(
    request: AnalyzeRecruitmentEventRequest,
    facts: RecruitmentFacts,
    warnings: list[str],
) -> RecruitmentFacts:
    source_text = "\n".join(
        part for part in (request.source.subject, request.source.content) if part
    )

    return facts.model_copy(
        update={
            "company_name": facts.company_name.model_copy(
                update={
                    "evidence": _exact_evidence(
                        facts.company_name.evidence, source_text, warnings
                    )
                }
            ),
            "job_title": facts.job_title.model_copy(
                update={
                    "evidence": _exact_evidence(
                        facts.job_title.evidence, source_text, warnings
                    )
                }
            ),
            "event_type": facts.event_type.model_copy(
                update={
                    "evidence": _exact_evidence(
                        facts.event_type.evidence, source_text, warnings
                    )
                }
            ),
            "recruitment_stage": facts.recruitment_stage.model_copy(
                update={
                    "evidence": _exact_evidence(
                        facts.recruitment_stage.evidence, source_text, warnings
                    )
                }
            ),
            "scheduled_at": facts.scheduled_at.model_copy(
                update={
                    "evidence": _exact_evidence(
                        facts.scheduled_at.evidence, source_text, warnings
                    )
                }
            ),
            "deadline_at": facts.deadline_at.model_copy(
                update={
                    "evidence": _exact_evidence(
                        facts.deadline_at.evidence, source_text, warnings
                    )
                }
            ),
            "next_action": facts.next_action.model_copy(
                update={
                    "evidence": _exact_evidence(
                        facts.next_action.evidence, source_text, warnings
                    )
                }
            ),
        }
    )


def _exact_evidence(
    evidence: str | None, source_text: str, warnings: list[str]
) -> str | None:
    if evidence is None:
        return None
    normalized = evidence.strip()
    if normalized and normalized in source_text:
        return normalized
    warnings.append("EVIDENCE_NOT_FOUND_IN_SOURCE")
    return None


def _build_proposed_change(
    *,
    request: AnalyzeRecruitmentEventRequest,
    candidate: ApplicationCandidate,
    facts: RecruitmentFacts,
    now: datetime,
    warnings: list[str],
) -> ProposedChange:
    normalized_now = now.astimezone(UTC)
    stale = _is_stale(facts, normalized_now)
    if stale:
        warnings.append("NOTIFICATION_APPEARS_STALE")
    terminal = candidate.current_stage in _TERMINAL_STAGES
    if terminal:
        warnings.append("CURRENT_STAGE_IS_TERMINAL")

    stage_change = None
    warning_count_before_stage = len(warnings)
    if not stale and not terminal:
        stage_change = _safe_stage_change(candidate, facts, warnings)
    new_stage_warnings = warnings[warning_count_before_stage:]
    stage_blocks_task = any(
        warning
        in {
            "WITHDRAWN_REQUIRES_USER_ACTION",
            "OFFER_REJECTION_REQUIRES_MANUAL_REVIEW",
            "STAGE_REGRESSION_SUPPRESSED",
        }
        for warning in new_stage_warnings
    )

    task = None
    if not stale and not terminal and not stage_blocks_task:
        task = _build_task(facts, normalized_now, warnings)

    timeline_type = (
        TimelineEventType.STAGE_CHANGE
        if stage_change is not None
        else TimelineEventType.NOTE
    )
    return ProposedChange(
        application_id=candidate.application_id,
        expected_version=candidate.application_version,
        job_code=candidate.job_code,
        stage_change=stage_change,
        timeline_event=TimelineEventDraft(
            event_type=timeline_type,
            occurred_at=request.source.received_at,
            from_stage=stage_change.from_stage if stage_change else None,
            to_stage=stage_change.to_stage if stage_change else None,
            note=facts.summary,
        ),
        task=task,
    )


def _is_stale(facts: RecruitmentFacts, now: datetime) -> bool:
    relevant_times = [
        value.astimezone(UTC)
        for value in (facts.deadline_at.value, facts.scheduled_at.value)
        if value is not None
    ]
    return bool(relevant_times) and max(relevant_times) < now


def _safe_stage_change(
    candidate: ApplicationCandidate,
    facts: RecruitmentFacts,
    warnings: list[str],
) -> StageChangeDraft | None:
    current = candidate.current_stage
    target = _target_stage(facts, warnings)
    if target is None or target is current:
        return None
    if target is ApplicationStage.WITHDRAWN:
        warnings.append("WITHDRAWN_REQUIRES_USER_ACTION")
        return None
    if current is ApplicationStage.OFFER and target is ApplicationStage.REJECTED:
        warnings.append("OFFER_REJECTION_REQUIRES_MANUAL_REVIEW")
        return None
    if target is ApplicationStage.REJECTED:
        return StageChangeDraft(from_stage=current, to_stage=target)
    if target not in _PROGRESS_ORDER:
        return None
    if _PROGRESS_ORDER[target] < _PROGRESS_ORDER[current]:
        warnings.append("STAGE_REGRESSION_SUPPRESSED")
        return None
    return StageChangeDraft(from_stage=current, to_stage=target)


def _target_stage(
    facts: RecruitmentFacts, warnings: list[str]
) -> ApplicationStage | None:
    extracted = facts.recruitment_stage.value
    event_type = facts.event_type.value
    expected = _EVENT_STAGE.get(event_type) if event_type is not None else None
    if expected is not None and extracted is not None and expected is not extracted:
        warnings.append("EVENT_STAGE_CONFLICT_RESOLVED")
    return expected or extracted


def _build_task(
    facts: RecruitmentFacts,
    now: datetime,
    warnings: list[str],
) -> TaskDraft | None:
    action = facts.next_action.value
    if action is None:
        return None
    if facts.event_type.value is EventType.REJECTION:
        warnings.append("NEXT_ACTION_CONFLICTS_WITH_EVENT")
        return None
    due_at = action.due_at or facts.deadline_at.value or facts.scheduled_at.value
    if due_at is None:
        warnings.append("NEXT_ACTION_WITHOUT_DUE_AT")
        return None
    if due_at.astimezone(UTC) < now:
        warnings.append("PAST_DUE_TASK_SUPPRESSED")
        return None
    return TaskDraft(
        task_type=action.task_type,
        title=action.title,
        due_at=due_at,
    )
