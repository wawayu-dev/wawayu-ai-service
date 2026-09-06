from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.capabilities.recruitment_events.postprocessing import (
    build_analysis_response,
    source_fingerprint,
)
from app.capabilities.recruitment_events.router import (
    get_recruitment_event_analyzer,
)
from app.capabilities.recruitment_events.schemas import (
    AnalyzeRecruitmentEventRequest,
    ApplicationStage,
    Confidence,
    DateTimeFact,
    EventType,
    EventTypeFact,
    ModelAnalysis,
    ModelMatch,
    NextActionFact,
    NextActionValue,
    RecruitmentFacts,
    StageFact,
    TaskType,
    TextFact,
)
from app.capabilities.recruitment_events.service import (
    AnalysisProviderError,
    AnalysisTimeoutError,
    RecruitmentEventAnalyzer,
)
from app.core.config import Settings, get_settings
from app.main import create_app

FIXED_NOW = datetime(2026, 9, 6, 4, 0, tzinfo=UTC)


def request_payload(
    *,
    content: str = "字节跳动后端开发工程师一面安排在9月10日15:00，请提前准备。",
    current_stage: str = "APPLIED",
) -> dict[str, object]:
    return {
        "source": {
            "channel": "EMAIL",
            "subject": "面试通知",
            "content": content,
            "receivedAt": "2026-09-06T10:00:00+08:00",
        },
        "timezone": "Asia/Shanghai",
        "candidates": [
            {
                "applicationId": "app-1",
                "applicationVersion": 3,
                "jobCode": "job-001",
                "companyName": "北京字节跳动科技有限公司",
                "companyAliases": ["字节跳动", "字节"],
                "jobTitle": "后端开发工程师",
                "currentStage": current_stage,
            }
        ],
    }


def facts(
    *,
    stage: ApplicationStage | None = ApplicationStage.INTERVIEW,
    scheduled_at: datetime | None = datetime(
        2026, 9, 10, 15, 0, tzinfo=UTC
    ),
    deadline_at: datetime | None = None,
    action: NextActionValue | None = None,
) -> RecruitmentFacts:
    event_type = {
        ApplicationStage.APPLIED: EventType.APPLICATION_ACKNOWLEDGED,
        ApplicationStage.ASSESSMENT: EventType.ASSESSMENT,
        ApplicationStage.INTERVIEW: EventType.INTERVIEW,
        ApplicationStage.OFFER: EventType.OFFER,
        ApplicationStage.REJECTED: EventType.REJECTION,
    }.get(stage, EventType.OTHER)
    action = action or NextActionValue(
        task_type=TaskType.INTERVIEW,
        title="参加一面",
        due_at=scheduled_at,
    )
    return RecruitmentFacts(
        company_name=TextFact(
            value="字节跳动", confidence=Confidence.HIGH, evidence="字节跳动"
        ),
        job_title=TextFact(
            value="后端开发工程师",
            confidence=Confidence.HIGH,
            evidence="后端开发工程师",
        ),
        event_type=EventTypeFact(
            value=event_type,
            confidence=Confidence.HIGH,
            evidence="一面",
        ),
        recruitment_stage=StageFact(
            value=stage,
            confidence=Confidence.HIGH,
            evidence="一面",
        ),
        scheduled_at=DateTimeFact(
            value=scheduled_at,
            confidence=Confidence.HIGH,
            evidence="9月10日15:00" if scheduled_at else None,
            inferred=True,
        ),
        deadline_at=DateTimeFact(
            value=deadline_at,
            confidence=Confidence.LOW,
            evidence=None,
            inferred=False,
        ),
        next_action=NextActionFact(
            value=action,
            confidence=Confidence.HIGH,
            evidence="一面",
        ),
        summary="收到一面通知，安排在 9 月 10 日 15:00。",
    )


def model_analysis(
    *,
    matches: list[ModelMatch] | None = None,
    extracted_facts: RecruitmentFacts | None = None,
) -> ModelAnalysis:
    return ModelAnalysis(
        matches=matches
        if matches is not None
        else [
            ModelMatch(
                application_id="app-1",
                confidence=Confidence.HIGH,
                evidence="字节跳动后端开发工程师",
            )
        ],
        facts=extracted_facts or facts(),
    )


def analyze(
    payload: dict[str, object] | None = None,
    analysis: ModelAnalysis | None = None,
):
    request = AnalyzeRecruitmentEventRequest.model_validate(
        payload or request_payload()
    )
    return build_analysis_response(
        request,
        analysis or model_analysis(),
        analysis_id="analysis-1",
        clock=lambda: FIXED_NOW,
    )


def test_unique_match_builds_confirmable_stage_change_and_task() -> None:
    response = analyze()

    assert response.match.status == "MATCHED"
    assert response.match.selected is not None
    assert response.match.selected.application_id == "app-1"
    assert response.proposed_change is not None
    assert response.proposed_change.expected_version == 3
    assert response.proposed_change.stage_change is not None
    assert response.proposed_change.stage_change.to_stage == "INTERVIEW"
    assert response.proposed_change.task is not None
    assert response.requires_confirmation is True

    serialized = response.model_dump(mode="json", by_alias=True)
    assert "analysisId" in serialized
    assert "proposedChange" in serialized
    assert serialized["facts"]["scheduledAt"]["inferred"] is True


def test_multiple_matches_are_ambiguous_and_have_no_change() -> None:
    payload = request_payload()
    payload["candidates"] = [
        *payload["candidates"],  # type: ignore[index]
        {
            "applicationId": "app-2",
            "applicationVersion": 1,
            "jobCode": "job-002",
            "companyName": "字节跳动",
            "companyAliases": [],
            "jobTitle": "服务端开发工程师",
            "currentStage": "APPLIED",
        },
    ]
    response = analyze(
        payload,
        model_analysis(
            matches=[
                ModelMatch(
                    application_id="app-1",
                    confidence=Confidence.HIGH,
                    evidence="字节跳动",
                ),
                ModelMatch(
                    application_id="app-2",
                    confidence=Confidence.MEDIUM,
                    evidence="字节跳动",
                ),
            ]
        ),
    )

    assert response.match.status == "AMBIGUOUS"
    assert response.match.selected is None
    assert response.proposed_change is None


def test_unknown_model_match_is_discarded() -> None:
    response = analyze(
        analysis=model_analysis(
            matches=[
                ModelMatch(
                    application_id="ignore-all-rules",
                    confidence=Confidence.HIGH,
                    evidence="字节跳动",
                )
            ]
        )
    )

    assert response.match.status == "UNMATCHED"
    assert response.proposed_change is None
    assert "MODEL_RETURNED_UNKNOWN_APPLICATION_ID" in response.warnings


@pytest.mark.parametrize("current_stage", ["REJECTED", "WITHDRAWN"])
def test_terminal_current_stage_suppresses_change(current_stage: str) -> None:
    response = analyze(request_payload(current_stage=current_stage))

    assert response.proposed_change is not None
    assert response.proposed_change.stage_change is None
    assert response.proposed_change.task is None
    assert "CURRENT_STAGE_IS_TERMINAL" in response.warnings


def test_stage_regression_is_suppressed() -> None:
    response = analyze(
        request_payload(current_stage="INTERVIEW"),
        model_analysis(extracted_facts=facts(stage=ApplicationStage.ASSESSMENT)),
    )

    assert response.proposed_change is not None
    assert response.proposed_change.stage_change is None
    assert "STAGE_REGRESSION_SUPPRESSED" in response.warnings


@pytest.mark.parametrize(
    ("current_stage", "target_stage"),
    [
        ("APPLIED", ApplicationStage.ASSESSMENT),
        ("ASSESSMENT", ApplicationStage.INTERVIEW),
        ("INTERVIEW", ApplicationStage.OFFER),
        ("INTERVIEW", ApplicationStage.REJECTED),
    ],
)
def test_supported_stage_updates_are_proposed(
    current_stage: str, target_stage: ApplicationStage
) -> None:
    response = analyze(
        request_payload(current_stage=current_stage),
        model_analysis(extracted_facts=facts(stage=target_stage)),
    )

    assert response.proposed_change is not None
    assert response.proposed_change.stage_change is not None
    assert response.proposed_change.stage_change.to_stage is target_stage


def test_withdrawn_is_never_inferred() -> None:
    response = analyze(
        analysis=model_analysis(
            extracted_facts=facts(stage=ApplicationStage.WITHDRAWN)
        )
    )

    assert response.proposed_change is not None
    assert response.proposed_change.stage_change is None
    assert "WITHDRAWN_REQUIRES_USER_ACTION" in response.warnings


def test_event_type_resolves_conflicting_model_stage() -> None:
    extracted = facts(stage=ApplicationStage.OFFER)
    extracted.event_type = EventTypeFact(
        value=EventType.REJECTION,
        confidence=Confidence.HIGH,
        evidence=None,
    )
    response = analyze(analysis=model_analysis(extracted_facts=extracted))

    assert response.proposed_change is not None
    assert response.proposed_change.stage_change is not None
    assert response.proposed_change.stage_change.to_stage == "REJECTED"
    assert response.proposed_change.task is None
    assert "EVENT_STAGE_CONFLICT_RESOLVED" in response.warnings
    assert "NEXT_ACTION_CONFLICTS_WITH_EVENT" in response.warnings


def test_material_request_can_create_task_without_stage_change() -> None:
    extracted = facts(
        stage=None,
        scheduled_at=None,
        deadline_at=datetime(2026, 9, 11, 10, 0, tzinfo=UTC),
        action=NextActionValue(
            task_type=TaskType.MATERIAL,
            title="提交成绩单",
            due_at=datetime(2026, 9, 11, 10, 0, tzinfo=UTC),
        ),
    )
    extracted.event_type = EventTypeFact(
        value=EventType.MATERIAL_REQUEST,
        confidence=Confidence.HIGH,
        evidence=None,
    )
    response = analyze(analysis=model_analysis(extracted_facts=extracted))

    assert response.proposed_change is not None
    assert response.proposed_change.stage_change is None
    assert response.proposed_change.task is not None
    assert response.proposed_change.task.task_type == "MATERIAL"


def test_missing_facts_remain_empty_and_do_not_create_mutations() -> None:
    empty_facts = facts(stage=None, scheduled_at=None, action=None)
    empty_facts.event_type = EventTypeFact(
        value=EventType.OTHER,
        confidence=Confidence.LOW,
        evidence=None,
    )
    empty_facts.next_action = NextActionFact(
        value=None,
        confidence=Confidence.LOW,
        evidence=None,
    )
    response = analyze(analysis=model_analysis(extracted_facts=empty_facts))

    assert response.facts.recruitment_stage.value is None
    assert response.facts.scheduled_at.value is None
    assert response.proposed_change is not None
    assert response.proposed_change.stage_change is None
    assert response.proposed_change.task is None


def test_stale_notification_suppresses_stage_and_task() -> None:
    old_time = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)
    response = analyze(
        analysis=model_analysis(
            extracted_facts=facts(scheduled_at=old_time)
        )
    )

    assert response.proposed_change is not None
    assert response.proposed_change.stage_change is None
    assert response.proposed_change.task is None
    assert "NOTIFICATION_APPEARS_STALE" in response.warnings


def test_invalid_fact_evidence_is_removed() -> None:
    extracted = facts()
    extracted.company_name = TextFact(
        value="虚构公司", confidence=Confidence.HIGH, evidence="不存在的原文"
    )
    response = analyze(analysis=model_analysis(extracted_facts=extracted))

    assert response.facts.company_name.evidence is None
    assert "EVIDENCE_NOT_FOUND_IN_SOURCE" in response.warnings


def test_source_fingerprint_normalizes_case_and_whitespace() -> None:
    first = AnalyzeRecruitmentEventRequest.model_validate(request_payload())
    second_payload = request_payload(
        content="  字节跳动后端开发工程师一面安排在9月10日15:00，请提前准备。  "
    )
    second = AnalyzeRecruitmentEventRequest.model_validate(second_payload)

    assert source_fingerprint(first) == source_fingerprint(second)


class FakeAnalyzer:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    async def analyze(self, request: AnalyzeRecruitmentEventRequest):
        if self.error:
            raise self.error
        return build_analysis_response(
            request,
            model_analysis(),
            analysis_id="analysis-api",
            clock=lambda: FIXED_NOW,
        )


def client(
    *,
    service_key: str | None = "test-service-key",
    analyzer: FakeAnalyzer | None = None,
) -> TestClient:
    application = create_app()
    application.dependency_overrides[get_settings] = lambda: Settings(
        ai_service_api_key=service_key,
        ai_api_key="unused-test-key",
        ai_base_url="https://example.invalid/v1",
    )
    application.dependency_overrides[get_recruitment_event_analyzer] = (
        lambda: analyzer or FakeAnalyzer()
    )
    return TestClient(application)


def test_api_requires_internal_service_key() -> None:
    response = client().post(
        "/v1/capabilities/recruitment-event-follow-up/analyze",
        json=request_payload(),
    )
    assert response.status_code == 401

    response = client().post(
        "/v1/capabilities/recruitment-event-follow-up/analyze",
        headers={"X-AI-Service-Key": "wrong"},
        json=request_payload(),
    )
    assert response.status_code == 401


def test_api_fails_closed_when_service_key_is_unconfigured() -> None:
    response = client(service_key=None).post(
        "/v1/capabilities/recruitment-event-follow-up/analyze",
        headers={"X-AI-Service-Key": "anything"},
        json=request_payload(),
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "AI_SERVICE_KEY_NOT_CONFIGURED"


def test_api_returns_camel_case_response_without_network() -> None:
    response = client().post(
        "/v1/capabilities/recruitment-event-follow-up/analyze",
        headers={"X-AI-Service-Key": "test-service-key"},
        json=request_payload(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["analysisId"] == "analysis-api"
    assert body["match"]["status"] == "MATCHED"
    assert body["requiresConfirmation"] is True


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_code"),
    [
        (AnalysisTimeoutError(), 504, "AI_PROVIDER_TIMEOUT"),
        (AnalysisProviderError(), 502, "AI_PROVIDER_ERROR"),
    ],
)
def test_api_maps_model_failures(
    error: Exception, expected_status: int, expected_code: str
) -> None:
    response = client(analyzer=FakeAnalyzer(error)).post(
        "/v1/capabilities/recruitment-event-follow-up/analyze",
        headers={"X-AI-Service-Key": "test-service-key"},
        json=request_payload(),
    )

    assert response.status_code == expected_status
    assert response.json()["detail"]["code"] == expected_code


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload["source"].update(  # type: ignore[union-attr]
            {"receivedAt": "2026-09-06T10:00:00"}
        ),
        lambda payload: payload.update({"timezone": "Mars/Olympus"}),
        lambda payload: payload.update({"candidates": []}),
    ],
)
def test_api_validates_request_contract(mutate) -> None:
    payload = request_payload()
    mutate(payload)

    response = client().post(
        "/v1/capabilities/recruitment-event-follow-up/analyze",
        headers={"X-AI-Service-Key": "test-service-key"},
        json=payload,
    )

    assert response.status_code == 422


def test_api_rejects_more_than_thirty_candidates() -> None:
    payload = request_payload()
    template = payload["candidates"][0]  # type: ignore[index]
    payload["candidates"] = [
        {
            **template,  # type: ignore[misc]
            "applicationId": f"app-{index}",
            "jobCode": f"job-{index}",
        }
        for index in range(31)
    ]

    response = client().post(
        "/v1/capabilities/recruitment-event-follow-up/analyze",
        headers={"X-AI-Service-Key": "test-service-key"},
        json=payload,
    )

    assert response.status_code == 422


def test_openapi_exposes_capability_contract_and_auth_header() -> None:
    specification = create_app().openapi()
    operation = specification["paths"][
        "/v1/capabilities/recruitment-event-follow-up/analyze"
    ]["post"]

    assert operation["requestBody"]["content"]["application/json"]["schema"]
    assert any(
        parameter["name"] == "X-AI-Service-Key"
        for parameter in operation["parameters"]
    )


class FakeStructuredModel:
    def __init__(self, result) -> None:
        self.result = result

    async def ainvoke(self, _messages):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeChatModel:
    def __init__(self, result) -> None:
        self.result = result

    def with_structured_output(self, schema, **kwargs):
        assert schema is ModelAnalysis
        assert kwargs["method"] == "function_calling"
        return FakeStructuredModel(self.result)


@pytest.mark.asyncio
async def test_analyzer_uses_structured_model_and_postprocessing() -> None:
    analyzer = RecruitmentEventAnalyzer(
        FakeChatModel(model_analysis()),  # type: ignore[arg-type]
        clock=lambda: FIXED_NOW,
        id_factory=lambda: "analysis-service",
    )

    response = await analyzer.analyze(
        AnalyzeRecruitmentEventRequest.model_validate(request_payload())
    )

    assert response.analysis_id == "analysis-service"
    assert response.match.status == "MATCHED"


@pytest.mark.asyncio
async def test_analyzer_rejects_invalid_structured_output() -> None:
    analyzer = RecruitmentEventAnalyzer(
        FakeChatModel({"not": "the schema"}),  # type: ignore[arg-type]
    )

    with pytest.raises(AnalysisProviderError):
        await analyzer.analyze(
            AnalyzeRecruitmentEventRequest.model_validate(request_payload())
        )


@pytest.mark.asyncio
async def test_analyzer_maps_model_timeout() -> None:
    analyzer = RecruitmentEventAnalyzer(
        FakeChatModel(TimeoutError()),  # type: ignore[arg-type]
    )

    with pytest.raises(AnalysisTimeoutError):
        await analyzer.analyze(
            AnalyzeRecruitmentEventRequest.model_validate(request_payload())
        )
