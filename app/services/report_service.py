# 세션 종료 후 전체 로그를 종합하여 최종 리포트를 생성하는 Report Generator 서비스
# 이 서비스는 요약 통계, 기준별(rubric) LLM 평가를 통한 강점/개선 포인트/실천 방법,
# overall score, 대응 점수(response_score), 누적 패턴 업데이트, 다음 커리큘럼 추천까지 수행한다.

from statistics import mean

from google import genai
from google.genai import types

from app.core.config import settings
from app.schemas.evaluation import (
    PresentationEvaluationResult,
    STRENGTH_THRESHOLD,
    CRITERION_LABELS,
    get_weights,
)
from app.schemas.report import (
    ReportGenerationInput,
    ReportGenerationResult,
    ReportSummary,
    CriterionScoreItem,
    UserPatternOutput,
)
from app.services.prompt_scenarios import build_scenario_block, AUDIENCE_TYPE_CONTENT_CHECKS

try:
    if settings.gemini_api_key:
        _gemini_client = genai.Client(api_key=settings.gemini_api_key)
    else:
        _gemini_client = None
except Exception as _e:
    print(f"[Gemini 초기화 실패] {_e}")
    _gemini_client = None


class ReportService:
    """
    Report Generator 서비스

    주요 기능
    - 세션 요약 통계 계산
    - 기준별(rubric) LLM 평가 → overall_score / 대응 점수(response_score) / 강점·개선 포인트·실천 방법
    - LLM 평가 실패 시 규칙 기반 폴백
    - 누적 패턴 갱신
    - 다음 추천 커리큘럼 생성
    """

    def generate_report(self, data: ReportGenerationInput) -> ReportGenerationResult:
        """
        전체 세션 데이터를 바탕으로 종합 리포트를 생성한다.
        """
        summary = self._build_summary(data)
        has_qa = summary.interrupt_count > 0

        eval_result = self._generate_evaluation(summary, data, has_qa)

        if eval_result:
            overall_score, response_score, strengths, weaknesses, improvements, criteria_scores, curriculum_next = \
                self._apply_evaluation(eval_result, has_qa, data, summary)
        else:
            response_score = self._calculate_fallback_response_score(data)
            weaknesses = self._extract_weaknesses(data, summary, response_score)
            strengths = self._extract_strengths(data, summary, response_score)
            improvements = self._build_improvements(weaknesses)
            overall_score = self._calculate_overall_score(summary, response_score, weaknesses)
            criteria_scores = []
            curriculum_next = None  # updated_pattern 계산 후 채움

        updated_pattern = self._update_user_pattern(data, weaknesses)

        if curriculum_next is None:
            curriculum_next = self._recommend_curriculum(
                updated_pattern=updated_pattern,
                weaknesses=weaknesses,
                response_score=response_score,
            )

        return ReportGenerationResult(
            summary=summary,
            strengths=strengths,
            weaknesses=weaknesses,
            improvements=improvements,
            overall_score=round(overall_score, 2),
            response_score=round(response_score, 2) if response_score is not None else None,
            criteria_scores=criteria_scores,
            curriculum_next=curriculum_next,
            updated_pattern=updated_pattern,
        )

    def _apply_evaluation(
        self,
        eval_result: PresentationEvaluationResult,
        has_qa: bool,
        data: ReportGenerationInput,
        summary: ReportSummary,
    ) -> tuple[float, float | None, list[str], list[str], list[str], list[CriterionScoreItem], str]:
        """
        LLM 기준별 평가 결과를 overall_score / response_score / 강점·개선 포인트·실천 방법 / 기준별 점수로 변환한다.
        """
        weights = get_weights(
            has_qa=has_qa,
            audience_type=data.audience_type,
            pressure_level=data.pressure_level,
        )
        total_weight = sum(weights.get(c.criterion_id, 0.0) for c in eval_result.criteria)
        if total_weight > 0:
            overall_score = sum(
                c.score * weights.get(c.criterion_id, 0.0) for c in eval_result.criteria
            ) / total_weight
        else:
            overall_score = mean(c.score for c in eval_result.criteria) if eval_result.criteria else 0.0

        criteria_by_id = {c.criterion_id: c for c in eval_result.criteria}
        qa_criterion = criteria_by_id.get("qa_response")
        response_score = float(qa_criterion.score) if qa_criterion else None

        strengths: list[str] = []
        weaknesses: list[str] = []
        improvements: list[str] = []
        criteria_scores: list[CriterionScoreItem] = []

        for c in eval_result.criteria:
            criteria_scores.append(CriterionScoreItem(
                criterion_id=c.criterion_id,
                label=CRITERION_LABELS.get(c.criterion_id, c.criterion_id),
                score=c.score,
            ))

            if c.score >= STRENGTH_THRESHOLD:
                strengths.append(c.diagnosis)
            else:
                weaknesses.append(c.diagnosis)
                improvements.append(c.action_item)

        if not strengths:
            strengths = self._extract_strengths(data, summary, response_score)
        if not weaknesses:
            weaknesses = self._extract_weaknesses(data, summary, response_score)
        if not improvements:
            improvements = self._build_improvements(weaknesses)

        return overall_score, response_score, strengths, weaknesses, improvements, criteria_scores, eval_result.overall_comment

    def _generate_evaluation(
        self,
        summary: ReportSummary,
        data: ReportGenerationInput,
        has_qa: bool,
    ) -> PresentationEvaluationResult | None:
        if _gemini_client is None:
            return None

        prompt = self._build_evaluation_prompt(summary, data, has_qa)

        result_box: list = [None]
        error_box: list = [None]

        def _call():
            try:
                result_box[0] = _gemini_client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=PresentationEvaluationResult,
                    ),
                )
            except Exception as exc:
                error_box[0] = exc

        import threading
        t = threading.Thread(target=_call, daemon=True)
        t.start()
        t.join()

        if error_box[0] is not None:
            print(f"[Gemini 평가 오류] {type(error_box[0]).__name__}: {error_box[0]}")
            return None

        if result_box[0] is None:
            print("[Gemini 평가 오류] 결과 없음 — 규칙 기반 폴백")
            return None

        try:
            return PresentationEvaluationResult.model_validate_json(result_box[0].text)
        except Exception as e:
            print(f"[Gemini 평가 파싱 오류] {e}")
            return None

    def _build_evaluation_prompt(
        self,
        summary: ReportSummary,
        data: ReportGenerationInput,
        has_qa: bool,
    ) -> str:
        transcript_text = data.transcript_text or " ".join(seg.text for seg in data.transcript[:20])
        transcript_section = transcript_text if transcript_text.strip() else "발화 내용 없음 (마이크 미사용 또는 발화량 극히 적음)"
        transcript_word_count = len(transcript_text.split()) if transcript_text.strip() else 0
        is_empty_presentation = transcript_word_count < 10

        qa_lines = []
        for item in data.answer_evaluation_log:
            qa_lines.append(
                f"Q: {item.question_text}\nA: {item.user_answer}\n점수: {item.answer_score}/100"
            )
        qa_section = chr(10).join(qa_lines) if qa_lines else "질의응답 없음"

        script_section = ""
        if data.script_text:
            script_section = f"""
## 준비 대본
{data.script_text[:800]}

## 발표 평가 기준
실제 발화 내용을 준비 대본과 비교하여 대본 내용이 제대로 전달됐는지, 핵심 포인트가 빠지지 않았는지를
logical_structure / message_clarity 평가에 반영하세요. 발화 내용이 대본과 너무 다르거나 극히 짧다면
"발표를 제대로 수행하지 않았다"고 명시하세요.
"""

        if has_qa:
            qa_criterion_block = """
### 4. qa_response (질문 대응력/회복력)
질문 의도에 맞는 답변을 했는지, 인터럽트 이후 발표 흐름을 얼마나 빨리 회복했는지 평가합니다.
- 90~100: 질문 의도를 정확히 파악해 구체적 근거/예시로 답변, 빠르게 회복
- 70~89: 답변은 했으나 구체성/근거 부족, 회복은 양호
- 50~69: 답변이 질문 의도와 다소 어긋나거나 회복이 느림
- 0~49: 답변 회피 또는 매우 부실, 회복 실패
"""
            criteria_instruction = "criteria 배열에 logical_structure, message_clarity, delivery_fluency, qa_response 4개를 모두 포함하세요."
        else:
            qa_criterion_block = ""
            criteria_instruction = "이번 세션에는 질의응답이 없었으므로 criteria 배열에 qa_response를 포함하지 말고 logical_structure, message_clarity, delivery_fluency 3개만 평가하세요."

        empty_instruction = ""
        if is_empty_presentation:
            empty_instruction = """
- 발화 단어 수가 10 미만입니다. 모든 criterion의 evidence/diagnosis에
  "발표가 거의 수행되지 않아 해당 기준을 신뢰성 있게 평가할 수 없습니다"를 반영하고 0~30점 사이의 낮은 점수를 부여하세요.
  action_item에는 "마이크를 켜고 실제로 말하면서 연습하세요"를 포함하세요."""

        env_section = ""
        if any([data.presentation_type, data.audience_type, data.pressure_level, data.audience_count, data.topic]):
            scenario_block = build_scenario_block(
                data.presentation_type, data.audience_type, data.pressure_level, data.audience_count,
            )
            topic_line = f"- 발표 주제: {data.topic}\n" if data.topic else ""
            content_check = AUDIENCE_TYPE_CONTENT_CHECKS.get(data.audience_type)
            content_check_line = (
                f"\n- 이 청중 유형에서 특히 확인해야 할 내용 요소: {content_check}\n"
                "  발표 내용(실제 발화·대본)에 이 요소들이 실제로 등장했는지를 logical_structure와 message_clarity의\n"
                "  evidence/diagnosis에 구체적으로 언급하세요 (등장했다면 어디서, 빠졌다면 무엇이 빠졌는지)."
                if content_check else ""
            )
            env_section = f"""
## 발표 환경
{topic_line}{scenario_block}
{content_check_line}

위 발표 환경을 반드시 고려하여 평가하세요. qa_response뿐 아니라 logical_structure/message_clarity 평가에도
이 환경 맥락(청중이 무엇을 궁금해할지, 압박 강도)을 구체적으로 반영하세요. professor라면 근거의 타당성을,
압박 강도가 high라면 답변의 디테일 부족에 더 엄격한 기준을 적용하세요. evidence/diagnosis는 이 발표의
실제 주제·내용을 짚어 서술하고, 다른 발표에도 그대로 적용될 법한 뻔한 문장은 피하세요.
"""

        return f"""당신은 발표 코칭 전문가입니다. 아래 [평가 기준]에 따라 발표를 분석하고,
기준별로 점수(0~100)와 evidence(근거), diagnosis(진단), action_item(실천 항목)을 작성하세요.

## 평가 기준

### 1. logical_structure (논리적 구조/흐름)
발표가 도입-본론-결론 구조를 갖추고, 주장과 근거의 순서가 청중이 따라가기 쉽게 배치되었는지 평가합니다.
- 90~100: 구조가 명확하고 섹션 간 전환이 자연스러우며 근거 순서가 논리적
- 70~89: 구조는 있으나 일부 전환이 어색하거나 근거 순서가 비효율적
- 50~69: 구조가 느슨하여 청중이 흐름을 따라가기 어려움
- 0~49: 구조를 식별하기 어렵고 내용이 산발적

### 2. message_clarity (핵심 메시지 전달력)
발표의 핵심 주장/결론이 명확히 제시되고 청중에게 각인되는지 평가합니다.
- 90~100: 핵심 메시지가 명확하고 반복/강조되어 기억에 남음
- 70~89: 핵심 메시지는 있으나 부수적 내용에 묻히거나 한 번만 언급됨
- 50~69: 핵심 메시지가 모호하거나 여러 메시지가 경쟁함
- 0~49: 핵심 메시지를 식별할 수 없음

### 3. delivery_fluency (전달력/유창성)
WPM, 필러 단어, 침묵 구간을 바탕으로 발화가 매끄럽게 전달되었는지 평가합니다.
- 90~100: WPM 100~160 범위이고 필러·침묵이 거의 없음
- 70~89: 대체로 안정적이나 일부 구간에서 속도/필러/침묵 문제
- 50~69: 말속도 또는 필러/침묵 중 한 가지 이상이 뚜렷한 문제
- 0~49: 여러 지표가 동시에 문제
{qa_criterion_block}
{env_section}
## 세션 데이터
- 평균 WPM: {summary.avg_wpm} (적정: 100~160)
- 필러 단어: {summary.filler_count}회 (5회 이상이면 유창성 저하)
- 침묵 구간: {summary.silence_count}회
- 돌발 질문: {summary.interrupt_count}회
- 평균 답변 점수: {summary.avg_answer_score:.1f}/100
- 발화 단어 수: {transcript_word_count}단어
{script_section}
## 실제 발화 내용
{transcript_section}

## 질의응답 기록
{qa_section}

## 작성 지침
- {criteria_instruction}
- evidence: 점수의 근거가 되는 부분을 한 문장 이내로 짧게 요약하세요. 발화/대본을 통째로 길게 인용하지 말고,
  핵심 단어나 짧은 구절만 뽑아 제시하세요.
- diagnosis: 이 점수가 나온 이유와 청중에게 미치는 영향을 설명하세요.
- action_item: 다음 발표에서 바로 실천할 수 있는 구체적 행동을 한 문장으로 제시하세요.{empty_instruction}
- overall_comment: 발표 전체에 대한 총평을 1~2문장으로 작성하세요."""

    def _build_summary(self, data: ReportGenerationInput) -> ReportSummary:
        """
        세션 전체 요약 통계를 계산한다.
        """
        if not data.speech_metrics:
            avg_wpm = 0.0
            max_wpm = 0.0
            filler_count = 0
            silence_count = 0
        else:
            avg_wpm = mean(snapshot.average_wpm for snapshot in data.speech_metrics)
            max_wpm = max(snapshot.recent_wpm for snapshot in data.speech_metrics)
            filler_count = max(snapshot.filler_count for snapshot in data.speech_metrics)
            silence_count = sum(
                1 for snapshot in data.speech_metrics
                if snapshot.silence_duration >= 1000
            )

        if data.answer_evaluation_log:
            avg_answer_score = mean(item.answer_score for item in data.answer_evaluation_log)
        else:
            avg_answer_score = 0.0

        return ReportSummary(
            avg_wpm=round(avg_wpm, 2),
            max_wpm=round(max_wpm, 2),
            filler_count=filler_count,
            silence_count=silence_count,
            interrupt_count=len(data.interrupt_log),
            avg_answer_score=round(avg_answer_score, 2)
        )

    def _calculate_fallback_response_score(self, data: ReportGenerationInput) -> float:
        """
        LLM 평가가 실패했을 때 사용하는 대응 점수(response_score) 폴백 계산

        가중치 예시
        - WPM 회복 속도: 40%
        - filler 감소율: 30%
        - silence 감소 여부: 30%
        """
        recovery = data.recovery_metrics

        score = (
            recovery.wpm_recovery_speed_score * 0.4 +
            recovery.filler_reduction_score * 0.3 +
            recovery.silence_reduction_score * 0.3
        )

        return max(0.0, min(score, 100.0))

    def _extract_strengths(
        self,
        data: ReportGenerationInput,
        summary: ReportSummary,
        response_score: float | None,
    ) -> list[str]:
        """
        세션 강점 도출 (규칙 기반 폴백)
        """
        strengths = []

        if 110 <= summary.avg_wpm <= 160:
            strengths.append("전체 말속도가 비교적 안정적입니다.")

        if summary.filler_count <= 3:
            strengths.append("필러 사용이 적어 전달력이 좋습니다.")

        if summary.avg_answer_score >= 75:
            strengths.append("질문에 대한 답변 대응력이 좋습니다.")

        if response_score is not None and response_score >= 75:
            strengths.append("질문에 대한 대응 및 회복 속도가 빠릅니다.")

        if not strengths:
            strengths.append("전반적으로 발표를 끝까지 유지한 점이 좋습니다.")

        return strengths

    def _extract_weaknesses(
        self,
        data: ReportGenerationInput,
        summary: ReportSummary,
        response_score: float | None,
    ) -> list[str]:
        """
        세션 약점 도출 (규칙 기반 폴백)
        """
        weaknesses = []

        if summary.avg_wpm < 100:
            weaknesses.append("전체 말속도가 다소 느립니다.")
        elif summary.avg_wpm > 170:
            weaknesses.append("전체 말속도가 다소 빠릅니다.")

        if summary.filler_count >= 5:
            weaknesses.append("필러 사용이 많아 답변의 매끄러움이 떨어집니다.")

        if summary.silence_count >= 3:
            weaknesses.append("침묵 구간이 자주 발생합니다.")

        if summary.avg_answer_score < 60 and data.answer_evaluation_log:
            weaknesses.append("질문에 대한 답변 구체성이 부족합니다.")

        if response_score is not None and response_score < 60:
            weaknesses.append("질문에 대한 대응 및 회복이 느린 편입니다.")

        if not weaknesses:
            weaknesses.append("뚜렷한 약점은 적지만 세부 표현을 더 다듬을 여지가 있습니다.")

        return weaknesses

    def _build_improvements(self, weaknesses: list[str]) -> list[str]:
        """
        약점을 개선 포인트로 변환 (규칙 기반 폴백)
        """
        improvements = []

        for weakness in weaknesses:
            if "말속도" in weakness:
                improvements.append("핵심 문장마다 짧은 pause를 두고 일정한 속도로 말하는 연습이 필요합니다.")
            elif "필러" in weakness:
                improvements.append("답변 전에 1초 정도 생각한 뒤 말하는 습관으로 필러를 줄여보세요.")
            elif "침묵" in weakness:
                improvements.append("예상 질문에 대한 답변 템플릿을 준비해 침묵 구간을 줄여보세요.")
            elif "답변 구체성" in weakness:
                improvements.append("답변에 이유, 예시, 근거를 함께 넣는 방식으로 구체성을 높여보세요.")
            elif "대응" in weakness or "회복" in weakness:
                improvements.append("인터럽트 직후 핵심 키워드부터 다시 꺼내 말하는 회복 훈련이 필요합니다.")

        if not improvements:
            improvements.append("다음 세션에서는 표현을 더 자연스럽게 다듬는 연습을 해보세요.")

        return improvements

    def _calculate_overall_score(
        self,
        summary: ReportSummary,
        response_score: float | None,
        weaknesses: list[str]
    ) -> float:
        """
        LLM 평가가 실패했을 때 사용하는 overall_score 폴백 계산

        단순 예시 기준
        - 평균 답변 점수
        - 대응 점수(response_score)
        - 필러 / 침묵 / 약점 개수 패널티
        """
        base = 50.0

        base += min(summary.avg_answer_score * 0.3, 30.0)
        if response_score is not None:
            base += response_score * 0.2

        if summary.filler_count >= 5:
            base -= 8

        if summary.silence_count >= 3:
            base -= 8

        base -= max(len(weaknesses) - 1, 0) * 3

        # 질문 스킵 페널티 (스킵 1회당 10점)
        skipped = getattr(summary, 'skipped_count', 0)
        base -= skipped * 10

        return max(0.0, min(base, 100.0))

    def _update_user_pattern(
        self,
        data: ReportGenerationInput,
        weaknesses: list[str]
    ) -> UserPatternOutput:
        """
        사용자 누적 패턴 갱신

        - session_count 증가
        - 약점 누적
        - 5회차 이후 반복 약점 추적 시작
        """
        previous_count = data.user_pattern.session_count
        new_count = previous_count + 1

        repeated = list(data.user_pattern.repeated_weaknesses)

        if new_count >= 5:
            for weakness in weaknesses:
                if weakness not in repeated:
                    repeated.append(weakness)

        trend = self._infer_trend(weaknesses)

        return UserPatternOutput(
            session_count=new_count,
            repeated_weaknesses=repeated,
            trend=trend
        )

    def _infer_trend(self, weaknesses: list[str]) -> str:
        """
        장기 추세를 단순 추정
        """
        if len(weaknesses) <= 1:
            return "improving"
        if len(weaknesses) <= 3:
            return "stable"
        return "declining"

    def _recommend_curriculum(
        self,
        updated_pattern: UserPatternOutput,
        weaknesses: list[str],
        response_score: float | None,
    ) -> str:
        """
        다음 추천 커리큘럼 생성 (규칙 기반 폴백)
        """
        if updated_pattern.session_count >= 5 and updated_pattern.repeated_weaknesses:
            if any("필러" in item for item in updated_pattern.repeated_weaknesses):
                return "필러 감소 집중 훈련 — 짧은 정지 후 답변 연습"

            if any("침묵" in item for item in updated_pattern.repeated_weaknesses):
                return "즉답 훈련 심화 — 예상 질문 템플릿 반복 연습"

            if any("답변 구체성" in item for item in updated_pattern.repeated_weaknesses):
                return "근거·예시 확장 훈련 — STAR 방식 답변 연습"

        if response_score is not None and response_score < 60:
            return "압박 질문 대응 훈련 — 인터럽트 직후 회복 연습"

        if any("말속도" in weakness for weakness in weaknesses):
            return "발화 속도 조절 훈련 — 문장 끝 pause 연습"

        return "종합 발표 안정화 훈련 — 답변 구조와 전달력 강화"
