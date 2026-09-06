import secrets
from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.capabilities.recruitment_events.schemas import (
    AnalyzeRecruitmentEventRequest,
    AnalyzeRecruitmentEventResponse,
)
from app.capabilities.recruitment_events.service import (
    AnalysisProviderError,
    AnalysisTimeoutError,
    RecruitmentEventAnalyzer,
)
from app.core.config import Settings, get_settings
from app.core.llm.factory import get_chat_model

router = APIRouter(
    prefix="/v1/capabilities/recruitment-event-follow-up",
    tags=["recruitment-event-follow-up"],
)


def require_ai_service_key(
    settings: Annotated[Settings, Depends(get_settings)],
    provided_key: Annotated[
        str | None, Header(alias="X-AI-Service-Key")
    ] = None,
) -> None:
    configured_key = settings.ai_service_api_key
    if configured_key is None or not configured_key.get_secret_value():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "AI_SERVICE_KEY_NOT_CONFIGURED",
                "message": "The protected capability is not configured.",
            },
        )
    if provided_key is None or not secrets.compare_digest(
        provided_key, configured_key.get_secret_value()
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "INVALID_AI_SERVICE_KEY",
                "message": "A valid X-AI-Service-Key header is required.",
            },
        )


@lru_cache
def _build_recruitment_event_analyzer() -> RecruitmentEventAnalyzer:
    settings = get_settings()
    return RecruitmentEventAnalyzer(
        get_chat_model(settings),
        structured_output_method=settings.ai_structured_output_method,
    )


def get_recruitment_event_analyzer() -> RecruitmentEventAnalyzer:
    try:
        return _build_recruitment_event_analyzer()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "AI_PROVIDER_NOT_CONFIGURED",
                "message": "The model provider configuration is invalid.",
            },
        ) from exc


@router.post(
    "/analyze",
    response_model=AnalyzeRecruitmentEventResponse,
    response_model_by_alias=True,
    dependencies=[Depends(require_ai_service_key)],
    summary="Analyze one recruitment notification",
    description=(
        "Returns confirmable candidate facts and never writes recruitment business "
        "state."
    ),
)
async def analyze_recruitment_event(
    request: AnalyzeRecruitmentEventRequest,
    analyzer: Annotated[
        RecruitmentEventAnalyzer, Depends(get_recruitment_event_analyzer)
    ],
) -> AnalyzeRecruitmentEventResponse:
    try:
        return await analyzer.analyze(request)
    except AnalysisTimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail={
                "code": "AI_PROVIDER_TIMEOUT",
                "message": "The model provider timed out.",
            },
        ) from exc
    except AnalysisProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "AI_PROVIDER_ERROR",
                "message": "The model provider returned an invalid response.",
            },
        ) from exc
