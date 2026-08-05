# 발표 평가를 위한 기준(rubric) 기반 구조화 출력 스키마
# LLM에게 "평가해줘"라고 열린 질문을 던지는 대신, 4개의 고정된 평가 기준(criterion)에 대해
# 각각 점수/근거/진단/실천 항목을 받아 Python에서 가중합으로 overall_score를 계산한다.

from typing import List, Literal, Optional
from pydantic import BaseModel, Field


CriterionId = Literal[
    "logical_structure",
    "message_clarity",
    "delivery_fluency",
    "qa_response",
]


# 평가 기준별 가중치 (질의응답이 있었던 세션 기준, 합 = 1.00)
CRITERION_WEIGHTS: dict[str, float] = {
    "logical_structure": 0.30,   # 논리적 구조/흐름 (내용)
    "message_clarity": 0.30,     # 핵심 메시지 전달력 (내용)
    "delivery_fluency": 0.15,    # 전달력/유창성
    "qa_response": 0.25,         # 질문 대응력/회복력
}

# 발표 환경(청중 유형/압박 강도)에 따른 가중치 보정치.
# has_qa=True일 때만 적용되며, 적용 후 합이 1.00이 되도록 재정규화한다.
AUDIENCE_TYPE_WEIGHT_BIAS: dict[str, dict[str, float]] = {
    "investor": {"qa_response": 0.05, "logical_structure": -0.05},
    "professor": {"logical_structure": 0.05, "qa_response": -0.05},
    "boss": {"qa_response": 0.05, "delivery_fluency": -0.05},
    "general": {"message_clarity": 0.05, "logical_structure": -0.05},
}

PRESSURE_LEVEL_WEIGHT_BIAS: dict[str, dict[str, float]] = {
    "high": {"qa_response": 0.03},
    "low": {"qa_response": -0.03},
}

# 강점 / 개선 포인트를 가르는 기준 점수
STRENGTH_THRESHOLD = 75

# 프론트엔드에 표시할 기준별 한글 이름
CRITERION_LABELS: dict[str, str] = {
    "logical_structure": "논리적 구조/흐름",
    "message_clarity": "핵심 메시지 전달력",
    "delivery_fluency": "전달력/유창성",
    "qa_response": "질문 대응력/회복력",
}


def get_weights(
    has_qa: bool,
    audience_type: str | None = None,
    pressure_level: str | None = None,
) -> dict[str, float]:
    """
    세션에 질의응답이 있었는지, 그리고 발표 환경(청중 유형/압박 강도)에 따라
    평가 기준 가중치를 반환한다.

    - has_qa=True: CRITERION_WEIGHTS를 기준으로 audience_type/pressure_level 보정치를
      더한 뒤 합이 1.00이 되도록 재정규화한다.
    - has_qa=False: qa_response 가중치(0.25)를 나머지 3개 기준에
      기존 비율대로 재분배한다 (logical_structure 0.40 / message_clarity 0.40 / delivery_fluency 0.20).
      질의응답 자체가 없으므로 환경 보정은 적용하지 않는다.
    """
    if not has_qa:
        qa_weight = CRITERION_WEIGHTS["qa_response"]
        remaining = {k: v for k, v in CRITERION_WEIGHTS.items() if k != "qa_response"}
        total = sum(remaining.values())
        return {k: v + qa_weight * (v / total) for k, v in remaining.items()}

    bias: dict[str, float] = {}
    for source in (
        AUDIENCE_TYPE_WEIGHT_BIAS.get(audience_type, {}),
        PRESSURE_LEVEL_WEIGHT_BIAS.get(pressure_level, {}),
    ):
        for criterion, delta in source.items():
            bias[criterion] = bias.get(criterion, 0.0) + delta

    if not bias:
        return CRITERION_WEIGHTS

    adjusted = {k: max(0.0, v + bias.get(k, 0.0)) for k, v in CRITERION_WEIGHTS.items()}
    total = sum(adjusted.values())
    if total <= 0:
        return CRITERION_WEIGHTS
    return {k: v / total for k, v in adjusted.items()}


class CriterionEvaluation(BaseModel):
    """
    평가 기준 하나에 대한 LLM 평가 결과
    """
    criterion_id: CriterionId
    score: int = Field(ge=0, le=100)
    evidence: str       # 점수의 근거가 되는 실제 발화/대본 인용 또는 관찰
    diagnosis: str      # 이 점수가 나온 이유와 그것이 발표에 미치는 영향
    action_item: str    # 다음 발표에서 바로 실천할 수 있는 구체적 행동


class PresentationEvaluationResult(BaseModel):
    """
    발표 평가 LLM 호출의 구조화 출력 결과
    """
    criteria: List[CriterionEvaluation]
    overall_comment: str


class PresentationEvaluationInput(BaseModel):
    """
    발표 평가 LLM 호출에 필요한 입력 데이터
    """
    transcript_text: str
    script_text: Optional[str] = None
    duration_seconds: int
    avg_wpm: float
    filler_count: int
    interrupt_count: int
    avg_response_score: Optional[float] = None
