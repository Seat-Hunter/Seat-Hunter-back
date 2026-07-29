# app/services/prompt_scenarios.py
#
# 세션 설정값(presentation_type/audience_type/pressure_level/audience_count)을
# LLM 프롬프트에 그대로 나열하는 대신, 각 선택지에 맞는 행동 지침 문장으로 변환한다.

from typing import Optional

PRESENTATION_TYPE_SCENARIOS = {
    "academic": "청중은 논리적 근거와 방법론의 타당성에 집중한다. 왜 그 방법을 선택했는지, 결과가 다른 조건에서도 재현되는지, 선행 연구와 어떻게 다른지 같은 근거·타당성 질문을 우선한다.",
    "school": "청중은 발표자의 개념 이해도를 확인하려 한다. 어려운 용어를 쉽게 설명해달라는 식의 기초 확인 질문 위주로 하고, 어조는 부드럽고 격려하는 톤을 유지한다.",
    "meeting": "청중은 실행 가능성과 의사결정에 관심 있는 실무자다. 일정, 필요한 리소스, 리스크 같은 실행·리스크 중심 질문을 한다.",
}

AUDIENCE_TYPE_SCENARIOS = {
    "professor": "논리적 엄밀함을 추궁한다. 근거의 출처, 한계점, 대안적 해석을 파고든다. 정중하지만 날카로운 어조를 유지한다.",
    "investor": "사업성과 숫자에 집중한다. 시장 규모, 수익 모델, 경쟁 우위, ROI를 묻는다. 실용적이고 도전적인 어조를 유지한다.",
    "boss": "실행과 책임 소재에 집중한다. '그래서 언제까지 되는가', '책임자는 누구인가'처럼 직설적으로 묻는다.",
    "general": "전문 용어 이해도를 우선한다. '그게 일반인 입장에서 어떤 의미인가'처럼 친근한 어조로 묻는다.",
}

PRESSURE_LEVEL_SCENARIOS = {
    "low": "질문 개입 빈도를 낮추고, 설명이 명백히 빠진 경우에만 질문한다. 질문 톤은 부드럽고 격려하는 뉘앙스를 유지하며, 꼬리질문은 답변이 크게 부족할 때만 한다.",
    "medium": "표준적인 개입 빈도와 어조를 유지한다.",
    "high": "질문 타이밍이 애매해도 적극적으로 개입한다(판단 임계값을 낮춘다). 근거·예외 상황을 집요하게 파고들고, 답변이 조금이라도 허술하면 꼬리질문으로 계속 압박한다.",
}

PRESSURE_LEVEL_EVAL_SCENARIOS = {
    "low": "답변이 핵심에서 크게 벗어나지 않았다면 디테일이 부족해도 관대하게 충분하다고 판단한다.",
    "medium": "표준 기준으로 충분성을 판단한다.",
    "high": "디테일이 부족하거나 근거가 약하면 충분하다고 판단하지 말고 꼬리질문으로 더 파고든다.",
}


def audience_size_scenario(audience_count: Optional[int]) -> Optional[str]:
    if not audience_count:
        return None
    if audience_count <= 5:
        return "청중 규모가 작다(소규모). 발표자 개인의 경험과 디테일까지 캐묻는 친밀한 대화체 질문이 가능하다."
    if audience_count <= 12:
        return "청중 규모가 중간 정도다. 특별히 규모를 의식하지 않고 표준적인 질문 방식을 유지한다."
    return "청중 규모가 크다(대규모). 청중 전체를 대변하는 듯한 보편적인 질문 위주로 묻고, 지나치게 개인적인 디테일 질문은 피한다."


def build_scenario_block(
    presentation_type: Optional[str],
    audience_type: Optional[str],
    pressure_level: Optional[str],
    audience_count: Optional[int] = None,
) -> str:
    """
    선택된 설정값들을 조합해 LLM에게 줄 상황별 행동 지침 블록을 만든다.
    매칭되는 시나리오가 없는 값은 조용히 건너뛴다.
    """
    lines = [
        s for s in (
            PRESENTATION_TYPE_SCENARIOS.get(presentation_type),
            AUDIENCE_TYPE_SCENARIOS.get(audience_type),
            PRESSURE_LEVEL_SCENARIOS.get(pressure_level),
            audience_size_scenario(audience_count),
        )
        if s
    ]

    if not lines:
        return "- 특별한 상황별 지침 없음"

    return "\n".join(f"- {line}" for line in lines)
