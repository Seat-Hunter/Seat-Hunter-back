from typing import Optional
from fastapi import APIRouter, HTTPException, Body
from app.repositories import report_repository, session_repository, interrupt_repository
from app.schemas.report import (
    ReportGenerationInput, SpeechMetricsSnapshot, AnswerEvaluationLogItem,
    RecoveryMetricsInput, UserPatternInput, TranscriptSegment, InterruptLogItem,
)
from app.services.report_service import ReportService

router = APIRouter()

_report_service = ReportService()


@router.post(
    "/debug/report",
    summary="[디버그] 더미 데이터로 리포트/AI 피드백 생성 테스트",
    description="실제 세션 없이 더미 데이터를 사용해 ReportService와 Gemini AI 피드백을 즉시 테스트합니다.",
    tags=["Debug"],
)
async def debug_generate_report(data: Optional[ReportGenerationInput] = Body(None)):
    if data is None:
        data = ReportGenerationInput(
            transcript=[
                TranscriptSegment(text="안녕하세요, 저희 팀의 프로젝트를 소개하겠습니다.", start_ms=0, end_ms=3000),
                TranscriptSegment(text="이 서비스는 발표 연습을 도와주는 AI 트레이너입니다.", start_ms=3000, end_ms=6000),
            ],
            interrupt_log=[
                InterruptLogItem(question_text="구체적인 기술 스택이 어떻게 되나요?", reason="기술 질문", interrupt_type="clarification", answered=True, answer_score=70.0, follow_up_count=0),
            ],
            answer_evaluation_log=[
                AnswerEvaluationLogItem(question_text="구체적인 기술 스택이 어떻게 되나요?", user_answer="FastAPI와 React를 사용했습니다.", answer_score=70.0, follow_up_needed=False, audience_reaction="neutral"),
            ],
            speech_metrics=[
                SpeechMetricsSnapshot(average_wpm=145, recent_wpm=155, filler_count=4, silence_duration=1200, hesitation_score=15, stress_score=25),
                SpeechMetricsSnapshot(average_wpm=138, recent_wpm=142, filler_count=6, silence_duration=800, hesitation_score=20, stress_score=30),
            ],
            recovery_metrics=RecoveryMetricsInput(
                wpm_recovery_speed_score=65, filler_reduction_score=55, silence_reduction_score=70
            ),
            user_pattern=UserPatternInput(session_count=2, repeated_weaknesses=["필러 사용이 많아 답변의 매끄러움이 떨어집니다."]),
        )

    result = _report_service.generate_report(data)
    return result


@router.get(
    "/sessions/{session_id}/report",
    summary="세션 리포트 조회",
    description=(
        "세션 종료 후 생성된 분석 리포트를 반환합니다. "
        "세션이 아직 종료되지 않았거나 리포트 생성 전이면 404를 반환합니다."
    ),
    responses={404: {"description": "리포트 없음"}},
)
async def get_report(session_id: str):
    report = await report_repository.get_report(session_id)
    if not report:
        raise HTTPException(status_code=404, detail="리포트 없음. 세션이 아직 종료되지 않았거나 생성 전입니다.")
    return report


@router.get(
    "/users/{user_id}/sessions",
    summary="유저 세션 목록 조회",
    description="특정 유저의 전체 발표 세션 이력을 반환합니다.",
)
async def get_user_sessions(user_id: int):
    sessions = await session_repository.get_user_sessions(user_id)
    return sessions


@router.get(
    "/sessions/{session_id}/interrupts",
    summary="세션 인터럽트 목록 조회",
    description="세션 중 발생한 모든 인터럽트 질문 이력을 반환합니다.",
)
async def get_session_interrupts(session_id: str):
    interrupts = await interrupt_repository.get_session_interrupts(session_id)
    return interrupts