# Interrupt Decision Engine 동작 테스트 코드
# 이 파일은 침묵, 주제 이탈, 필러 급증, WPM 감소 조건에서
# 인터럽트가 올바르게 발생하는지 확인하기 위한 테스트 스크립트이다.

from app.schemas.interrupt import (
    SpeechMetricsInput,
    ContextStateInput,
    InterruptDecisionInput,
)
from app.services.interrupt_service import InterruptService


def run_test():
    """
    Interrupt Decision Engine 테스트 실행
    """
    service = InterruptService()

    test_cases = [
        {
            "name": "정상 발표 상태 - 인터럽트 없음",
            "input": InterruptDecisionInput(
                speech_metrics=SpeechMetricsInput(
                    recent_wpm=140,
                    average_wpm=135,
                    filler_count=1,
                    silence_duration=1000,
                    hesitation_score=0.1,
                    stress_score=0.2,
                ),
                context_state=ContextStateInput(
                    drift_score=0.2,
                    current_topic="서비스 소개",
                    topic_shift_detected=False,
                ),
                cooldown_remaining_ms=0,
                pressure_level="medium",
                interrupt_enabled=True,
            ),
        },
        {
            "name": "긴 침묵 발생 - 인터럽트",
            "input": InterruptDecisionInput(
                speech_metrics=SpeechMetricsInput(
                    recent_wpm=130,
                    average_wpm=135,
                    filler_count=1,
                    silence_duration=3200,
                    hesitation_score=0.2,
                    stress_score=0.3,
                ),
                context_state=ContextStateInput(
                    drift_score=0.3,
                    current_topic="기능 설명",
                    topic_shift_detected=False,
                ),
                cooldown_remaining_ms=0,
                pressure_level="medium",
                interrupt_enabled=True,
            ),
        },
        {
            "name": "주제 이탈 - 인터럽트",
            "input": InterruptDecisionInput(
                speech_metrics=SpeechMetricsInput(
                    recent_wpm=120,
                    average_wpm=130,
                    filler_count=1,
                    silence_duration=800,
                    hesitation_score=0.1,
                    stress_score=0.2,
                ),
                context_state=ContextStateInput(
                    drift_score=0.8,
                    current_topic="날씨 이야기",
                    topic_shift_detected=True,
                ),
                cooldown_remaining_ms=0,
                pressure_level="medium",
                interrupt_enabled=True,
            ),
        },
        {
            "name": "고압박 + 주제 전환 - 인터럽트",
            "input": InterruptDecisionInput(
                speech_metrics=SpeechMetricsInput(
                    recent_wpm=125,
                    average_wpm=130,
                    filler_count=1,
                    silence_duration=500,
                    hesitation_score=0.15,
                    stress_score=0.2,
                ),
                context_state=ContextStateInput(
                    drift_score=0.4,
                    current_topic="다른 이야기",
                    topic_shift_detected=True,
                ),
                cooldown_remaining_ms=0,
                pressure_level="high",
                interrupt_enabled=True,
            ),
        },
        {
            "name": "쿨다운 중 - 인터럽트 금지",
            "input": InterruptDecisionInput(
                speech_metrics=SpeechMetricsInput(
                    recent_wpm=100,
                    average_wpm=130,
                    filler_count=5,
                    silence_duration=5000,
                    hesitation_score=0.5,
                    stress_score=0.7,
                ),
                context_state=ContextStateInput(
                    drift_score=0.9,
                    current_topic="주제 이탈",
                    topic_shift_detected=True,
                ),
                cooldown_remaining_ms=12000,
                pressure_level="high",
                interrupt_enabled=True,
            ),
        },
        {
            "name": "인터럽트 비활성화 - 인터럽트 금지",
            "input": InterruptDecisionInput(
                speech_metrics=SpeechMetricsInput(
                    recent_wpm=90,
                    average_wpm=130,
                    filler_count=6,
                    silence_duration=4500,
                    hesitation_score=0.5,
                    stress_score=0.7,
                ),
                context_state=ContextStateInput(
                    drift_score=0.95,
                    current_topic="완전 다른 주제",
                    topic_shift_detected=True,
                ),
                cooldown_remaining_ms=0,
                pressure_level="high",
                interrupt_enabled=False,
            ),
        },
    ]

    for idx, case in enumerate(test_cases, start=1):
        print(f"\n===== Test Case {idx}: {case['name']} =====")
        result = service.decide(case["input"])
        print(result.model_dump())


if __name__ == "__main__":
    run_test()