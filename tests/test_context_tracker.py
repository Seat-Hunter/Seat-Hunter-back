# Context Tracker 동작 테스트 코드

from app.schemas.context import ContextTrackerInput
from app.services.context_tracker_service import ContextTrackerService


def run_test():
    service = ContextTrackerService(window_size=3)

    slide_texts = [
        "서비스 소개",
        "실시간 음성 분석 기능",
        "인터럽트 및 질문 생성 기능",
        "종합 리포트 및 피드백"
    ]

    transcripts = [
        "안녕하세요. 이 서비스는 발표 연습을 돕습니다.",
        "이 시스템은 실시간 음성 분석 기능을 제공합니다.",
        "발표 중 인터럽트와 질문 생성 기능이 포함되어 있습니다.",
        "세션 종료 후 종합 리포트를 제공합니다.",
        "오늘 날씨는 매우 맑습니다."
    ]

    for i, text in enumerate(transcripts, start=1):
        result = service.update(
            ContextTrackerInput(
                transcript=text,
                slide_texts=slide_texts
            )
        )

        print(f"\n===== Test Case {i} =====")
        print(result.model_dump())

        if result.drift_score > 0.65:
            print("⚠️ Drift detected: 인터럽트 트리거 가능")


if __name__ == "__main__":
    run_test()