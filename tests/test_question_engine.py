# Question Engine 동작 테스트 코드
# analyze_presentation_style + generate_question_ai 두 프롬프트 분리 동작 검증

import asyncio
from unittest.mock import MagicMock, patch

from app.schemas.question import QuestionGenerationInput
from app.services.question_service import QuestionService


# ── Gemini mock 헬퍼 ──────────────────────────────────────────────────────────

def _mock_gemini(response_text: str):
    """generate_content 호출 시 response_text를 반환하는 mock client"""
    mock_result = MagicMock()
    mock_result.text = response_text
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_result
    return mock_client


# ── analyze_presentation_style 테스트 ─────────────────────────────────────────

async def test_analyze_style():
    service = QuestionService()

    cases = [
        (
            "학술 발표",
            "본 연구는 트랜스포머 기반 자연어처리 모델의 어텐션 메커니즘을 분석하여 "
            "문맥 의존성 학습 능력을 실증적으로 검토합니다.",
            "academic",   # Gemini가 반환할 예상 라벨
        ),
        (
            "일반 발표",
            "여러분, 혹시 오늘 할 일을 내일로 미루지 말자는 말 좋아하시나요? "
            "저는 항상 방 청소를 미루곤 합니다.",
            "casual",
        ),
        (
            "비즈니스 발표",
            "이번 분기 매출은 전년 대비 23% 성장했으며, "
            "신규 고객 유치 비용은 15% 절감되었습니다.",
            "professional",
        ),
    ]

    print("\n===== analyze_presentation_style 테스트 =====")
    for name, context, expected_style in cases:
        with patch("app.services.question_service._gemini_client", _mock_gemini(expected_style)):
            result = await service.analyze_presentation_style(context)
        status = "✅ PASS" if result == expected_style else "❌ FAIL"
        print(f"\n[{status}] {name}")
        print(f"  context: {context[:50]}...")
        print(f"  style: {result} (expected: {expected_style})")


# ── generate_question_ai 테스트 ───────────────────────────────────────────────

async def test_generate_question():
    service = QuestionService()

    cases = [
        (
            "학술 발표 → 전문적 질문",
            QuestionGenerationInput(
                recent_context=[
                    "트랜스포머 모델은 셀프 어텐션을 통해 장거리 의존성을 학습합니다.",
                    "BERT는 양방향 인코더 구조로 문맥 이해 성능을 높였습니다.",
                ],
                audience_type="professor",
                presentation_type="academic",
                pressure_level="medium",
                previous_questions=[],
            ),
            "academic",
            "BERT의 양방향 인코더 구조가 기존 단방향 모델과 비교해 어떤 점에서 우수한지 설명해 주세요.",
        ),
        (
            "일반 발표 → 구어체 질문",
            QuestionGenerationInput(
                recent_context=[
                    "여러분도 할 일을 미루는 습관이 있으신가요?",
                    "저는 오늘 발표 준비도 마지막 날 밤새워서 했습니다.",
                ],
                audience_type="professor",
                presentation_type="presentation",
                pressure_level="low",
                previous_questions=[],
            ),
            "casual",
            "그 경험이 발표 주제와 어떤 연결이 있는지 말씀해 주실 수 있나요?",
        ),
        (
            "이전 질문 중복 회피",
            QuestionGenerationInput(
                recent_context=["발표의 핵심 내용을 요약하면 이렇습니다."],
                audience_type="professor",
                presentation_type="academic",
                pressure_level="medium",
                previous_questions=["핵심 내용을 다시 설명해 주세요."],
            ),
            "academic",
            "이 연구가 기존 연구와 다른 점은 무엇인가요?",
        ),
    ]

    print("\n===== generate_question_ai 테스트 =====")
    for name, data, style, mock_answer in cases:
        with patch("app.services.question_service._gemini_client", _mock_gemini(mock_answer)):
            result = await service.generate_question_ai(data, presentation_style=style)
        print(f"\n[케이스] {name}")
        print(f"  스타일: {style}")
        print(f"  생성된 질문: {result.question_text}")
        print(f"  question_type: {result.question_type}")


# ── Gemini 없을 때 룰 기반 폴백 테스트 ──────────────────────────────────────

async def test_fallback_without_gemini():
    service = QuestionService()
    data = QuestionGenerationInput(
        recent_context=["발표 내용입니다."],
        audience_type="professor",
        presentation_type="academic",
        pressure_level="medium",
        previous_questions=[],
    )

    print("\n===== Gemini 없을 때 폴백 테스트 =====")
    with patch("app.services.question_service._gemini_client", None):
        style = await service.analyze_presentation_style("발표 내용입니다.")
        question = await service.generate_question_ai(data, presentation_style=style)

    print(f"  style fallback: {style} (expected: general)")
    print(f"  question fallback: {question.question_text}")
    print(f"  question_type: {question.question_type}")

    assert style == "general", "Gemini 없을 때 style은 general이어야 함"
    assert question.question_type != "ai_generated", "Gemini 없을 때 룰 기반이어야 함"
    print("  ✅ PASS")


# ── 실행 ─────────────────────────────────────────────────────────────────────

async def run_all():
    await test_analyze_style()
    await test_generate_question()
    await test_fallback_without_gemini()


if __name__ == "__main__":
    asyncio.run(run_all())
