# app/services/prompt_scenarios.py
#
# 세션 설정값(presentation_type/audience_type/pressure_level/audience_count)을
# LLM 프롬프트에 그대로 나열하는 대신, 각 선택지에 맞는 행동 지침 문장으로 변환한다.

from typing import Optional


PRESENTATION_TYPE_SCENARIOS = {
    "academic": (
        "학술 발표를 듣는 관점에서 논리적 근거, 방법 선택의 이유, "
        "결과의 해석과 한계에 관심을 둔다. 다만 모든 요소를 확인하려 하지 말고, "
        "현재 발표 내용에서 실제로 가장 궁금하거나 설명이 필요한 지점 하나에만 초점을 맞춘다."
    ),
    "school": (
        "발표자가 핵심 개념을 이해하고 자신의 말로 설명하는지 살펴본다. "
        "어려운 표현이 청중의 이해를 막을 때는 쉬운 설명이나 간단한 예시를 요청할 수 있지만, "
        "이미 충분히 명확한 내용은 다시 확인하지 않는다. "
        "어조는 부드럽고 격려하는 방향을 유지한다."
    ),
    "meeting": (
        "실무적인 의사결정에 도움이 되는 정보에 관심을 둔다. "
        "현재 내용과 직접 연결될 때 일정, 리소스, 실행 방법, 예상 리스크 등을 물을 수 있으며, "
        "발표에 나오지 않은 숫자나 계획을 억지로 요구하지 않는다."
    ),
}


AUDIENCE_TYPE_SCENARIOS = {
    "professor": (
        "주장과 결론이 어떤 근거와 전제 위에 있는지 살펴보고, "
        "필요한 경우 한계나 다른 해석 가능성을 묻는다. "
        "논리적으로 날카로울 수는 있지만, 발표 내용에 근거해 정중하게 질문한다."
    ),
    "investor": (
        "제안이 실제로 어떤 가치를 만들고 지속 가능한지에 관심을 둔다. "
        "시장성, 수익 구조, 경쟁 우위, 비용 대비 효과 중 "
        "현재 발표와 가장 관련 있는 지점을 선택해 실용적으로 묻는다."
    ),
    "boss": (
        "실행 가능성과 다음 행동이 분명한지에 관심을 둔다. "
        "일정, 우선순위, 담당, 위험 요소 중 의사결정에 필요한 정보가 "
        "실제로 빠져 있을 때만 직접적으로 확인한다."
    ),
    "general": (
        "전문 지식이 없는 청중도 이해할 수 있는지를 중요하게 본다. "
        "낯선 용어나 추상적인 설명이 핵심 이해를 막을 때, "
        "일상적인 의미나 구체적인 예시를 친근하게 묻는다."
    ),
}


PRESSURE_LEVEL_SCENARIOS = {
    "low": (
        "발표 흐름을 충분히 존중한다. 청중의 이해에 중요한 설명이 분명히 빠졌거나 "
        "발표자가 자연스럽게 도움을 받을 수 있는 경우에만 질문하고, "
        "답변의 핵심이 전달되면 세부 사항을 더 요구하지 않는다."
    ),
    "medium": (
        "발표 흐름과 질문의 유용성을 균형 있게 본다. "
        "자연스럽게 궁금증이 생긴 지점에서는 질문하되, "
        "이미 설명된 내용이나 곧 이어질 가능성이 높은 내용은 기다린다."
    ),
    "high": (
        "경계가 애매한 상황에서는 비교적 적극적으로 질문할 수 있고, "
        "핵심 주장에 필요한 근거·조건·예외가 부족하면 한 단계 더 파고들 수 있다. "
        "다만 압박은 질문의 깊이와 직접성으로 표현하며, "
        "미완성 발화를 끊거나 같은 요구를 반복하거나 트집을 잡지는 않는다."
    ),
}

# 청중 유형별로 발표 "내용" 자체에서 확인해야 할 요소.
# 평가 프롬프트에서 logical_structure/message_clarity가 이 요소들을 실제로 다뤘는지
# evidence에 구체적으로 언급하도록 강제하는 데 쓴다 (qa_response에만 환경이 반영되는 것을 막기 위함).
AUDIENCE_TYPE_CONTENT_CHECKS = {
    "professor": "선행 연구·근거 자료 언급, 방법론의 타당성 설명, 결과의 한계점 인정 여부",
    "investor": "시장 규모, 수익 모델, 경쟁 우위, ROI/수익성 지표 언급 여부",
    "boss": "실행 일정, 필요 리소스, 리스크 및 책임 소재 언급 여부",
    "general": "전문 용어를 쉬운 말로 풀어 설명했는지, 청중이 왜 관심을 가져야 하는지 설명했는지",
}


PRESSURE_LEVEL_EVAL_SCENARIOS = {
    "low": (
        "질문의 핵심에 답했고 전체 의미가 전달되었다면, "
        "세부 정보가 다소 부족해도 충분한 답변으로 본다."
    ),
    "medium": (
        "질문의 핵심 요구에 직접 답했는지와 답변을 이해할 만큼 "
        "필요한 설명이 있는지를 균형 있게 판단한다."
    ),
    "high": (
        "원래 질문의 핵심을 뒷받침하는 근거·조건·예외가 실질적으로 부족하면 "
        "꼬리질문을 고려한다. 다만 핵심 요구에 이미 직접 답했다면 "
        "단순히 더 자세한 답을 얻기 위해 불필요한 꼬리질문을 만들지 않는다."
    ),
}


def audience_size_scenario(
    audience_count: Optional[int],
) -> Optional[str]:
    if not audience_count:
        return None

    if audience_count <= 5:
        return (
            "청중 규모가 작다(소규모). 현재 발표와 관련이 있다면 "
            "발표자의 경험이나 구체적인 맥락을 조금 더 개인적인 대화체로 물을 수 있다. "
            "다만 사적인 정보나 불필요한 세부 사항까지 요구하지 않는다."
        )

    if audience_count <= 12:
        return (
            "청중 규모가 중간 정도다. 규모 자체를 과도하게 의식하지 말고, "
            "발표 내용과 상황에 가장 자연스러운 질문 방식을 선택한다."
        )

    return (
        "청중 규모가 크다(대규모). 여러 청중이 함께 이해하거나 판단하는 데 "
        "도움이 되는 보편적인 지점을 우선하되, 현재 내용에 꼭 필요한 경우에는 "
        "구체적인 질문도 할 수 있다. 지나치게 사적인 질문은 피한다."
    )


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
        scenario
        for scenario in (
            PRESENTATION_TYPE_SCENARIOS.get(presentation_type),
            AUDIENCE_TYPE_SCENARIOS.get(audience_type),
            PRESSURE_LEVEL_SCENARIOS.get(pressure_level),
            audience_size_scenario(audience_count),
        )
        if scenario
    ]

    if not lines:
        return "- 특별한 상황별 지침 없음"

    return "\n".join(f"- {line}" for line in lines)