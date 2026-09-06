from collections.abc import Callable
from uuid import uuid4

from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import ValidationError

from app.capabilities.recruitment_events.postprocessing import (
    Clock,
    build_analysis_response,
    utc_now,
)
from app.capabilities.recruitment_events.prompts import build_messages
from app.capabilities.recruitment_events.schemas import (
    AnalyzeRecruitmentEventRequest,
    AnalyzeRecruitmentEventResponse,
    ModelAnalysis,
)


class AnalysisTimeoutError(Exception):
    """The configured model did not complete within its timeout."""


class AnalysisProviderError(Exception):
    """The provider failed or returned an invalid structured result."""


class RecruitmentEventAnalyzer:
    def __init__(
        self,
        model: BaseChatModel,
        *,
        structured_output_method: str = "function_calling",
        clock: Clock = utc_now,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._structured_model = model.with_structured_output(
            ModelAnalysis,
            method=structured_output_method,
        )
        self._clock = clock
        self._id_factory = id_factory or (lambda: str(uuid4()))

    async def analyze(
        self, request: AnalyzeRecruitmentEventRequest
    ) -> AnalyzeRecruitmentEventResponse:
        try:
            raw_result = await self._structured_model.ainvoke(build_messages(request))
            result = (
                raw_result
                if isinstance(raw_result, ModelAnalysis)
                else ModelAnalysis.model_validate(raw_result)
            )
        except Exception as exc:
            if _is_timeout(exc):
                raise AnalysisTimeoutError from exc
            if isinstance(exc, ValidationError):
                raise AnalysisProviderError from exc
            raise AnalysisProviderError from exc

        return build_analysis_response(
            request,
            result,
            analysis_id=self._id_factory(),
            clock=self._clock,
        )


def _is_timeout(exc: Exception) -> bool:
    return isinstance(exc, TimeoutError) or "timeout" in type(exc).__name__.lower()
