# Report Generator 동작 테스트 코드
# 이 파일은 세션 종료 후 종합 리포트가 정상적으로 생성되는지 확인하기 위한 테스트 스크립트이다.

from app.schemas.report import (
    ReportGenerationInput,
    TranscriptSegment,
    InterruptLogItem,
    AnswerEvaluationLogItem,
    SpeechMetricsSnapshot,
    RecoveryMetricsInput,
    UserPatternInput,
)
from app.services.report_service import ReportService


def run_test():
    """
    Report Generator 테스트 실행
    """
    service = ReportService()

    test_input = ReportGenerationInput(
        transcript=[
            TranscriptSegment(
                text="안녕하세요. 오늘 발표를 시작하겠습니다.",
                start_ms=0,
                end_ms=3000
            ),
            TranscriptSegment(
                text="이 서비스는 발표 중 실시간 발화 분석을 제공합니다.",
                start_ms=4000,
                end_ms=8000
            ),
        ],
        interrupt_log=[
            InterruptLogItem(
                question_text="방금 설명한 기능의 핵심 차별점은 무엇인가요?",
                reason="주제 이탈 점수 초과",
                interrupt_type="topic_clarification",
                answered=True,
                answer_score=72,
                follow_up_count=1
            ),
            InterruptLogItem(
                question_text="그 기능이 실제 사용자에게 어떤 가치를 주나요?",
                reason="긴 침묵 발생",
                interrupt_type="encouragement_probe",
                answered=True,
                answer_score=68,
                follow_up_count=0
            ),
        ],
        answer_evaluation_log=[
            AnswerEvaluationLogItem(
                question_text="방금 설명한 기능의 핵심 차별점은 무엇인가요?",
                user_answer="실시간으로 발표자의 발화 품질을 분석하고 즉시 피드백을 제공하는 점입니다.",
                answer_score=72,
                follow_up_needed=False,
                audience_reaction="satisfied"
            ),
            AnswerEvaluationLogItem(
                question_text="그 기능이 실제 사용자에게 어떤 가치를 주나요?",
                user_answer="사용자가 실전처럼 압박 상황을 연습할 수 있다는 장점이 있습니다.",
                answer_score=68,
                follow_up_needed=False,
                audience_reaction="satisfied"
            ),
        ],
        speech_metrics=[
            SpeechMetricsSnapshot(
                recent_wpm=145,
                average_wpm=138,
                filler_count=2,
                silence_duration=500,
                hesitation_score=0.1,
                stress_score=0.2
            ),
            SpeechMetricsSnapshot(
                recent_wpm=152,
                average_wpm=140,
                filler_count=3,
                silence_duration=1200,
                hesitation_score=0.2,
                stress_score=0.3
            ),
            SpeechMetricsSnapshot(
                recent_wpm=133,
                average_wpm=136,
                filler_count=3,
                silence_duration=800,
                hesitation_score=0.15,
                stress_score=0.25
            ),
        ],
        recovery_metrics=RecoveryMetricsInput(
            wpm_recovery_speed_score=78,
            filler_reduction_score=72,
            silence_reduction_score=70
        ),
        user_pattern=UserPatternInput(
            session_count=4,
            repeated_weaknesses=["전체 말속도가 다소 빠릅니다."]
        )
    )

    result = service.generate_report(test_input)

    print("\n===== REPORT RESULT =====")
    print(result.model_dump())


if __name__ == "__main__":
    run_test()