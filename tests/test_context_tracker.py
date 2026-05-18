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
            print("⚠️  Drift detected: 인터럽트 트리거 가능")
        if result.topic_shift_detected:
            print("🔀 Topic shift detected: 스타일 재분석 트리거")


def run_topic_shift_test():
    """슬라이드 없이 transcript 자체 비교로 topic shift 감지 테스트"""
    service = ContextTrackerService(window_size=3)

    test_cases = [
        # (설명, transcript, 예상 topic_shift)
        ("첫 발화 - shift 없음", "저는 오늘 머신러닝의 지도학습에 대해 발표하겠습니다.", False),
        ("연속 유사 발화 - shift 없음", "지도학습은 레이블된 데이터를 이용해 모델을 학습시킵니다.", False),
        ("유사 발화 - shift 없음", "대표적인 지도학습 알고리즘으로는 SVM, 랜덤포레스트가 있습니다.", False),
        ("완전히 다른 주제 - shift 감지", "오늘 점심은 뭐 먹을까요? 저는 파스타가 먹고 싶습니다.", True),
        ("발표 복귀 - shift 감지", "다시 돌아와서 비지도학습의 클러스터링 기법을 살펴보겠습니다.", True),
    ]

    print("\n\n===== Topic Shift 감지 테스트 (슬라이드 없음) =====")
    for desc, text, expected in test_cases:
        result = service.update(ContextTrackerInput(transcript=text, slide_texts=[]))
        status = "✅ PASS" if result.topic_shift_detected == expected else "❌ FAIL"
        print(f"\n[{status}] {desc}")
        print(f"  transcript: {text[:40]}...")
        print(f"  topic_shift_detected: {result.topic_shift_detected} (expected: {expected})")


if __name__ == "__main__":
    run_test()
    run_topic_shift_test()
