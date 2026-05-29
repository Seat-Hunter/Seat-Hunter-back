"""
stress_score 계산 수정 및 피드백 임계값 변경 검증 테스트
"""
import pytest
from app.services.speech_analysis_service import SpeechAnalysisService
from app.schemas.speech_analysis import SpeechAnalysisInput, SpeechAnalysisResult
from app.ws.session_ws import _generate_feedback


def make_input(text: str, start_ms: int = 0, end_ms: int = 3000) -> SpeechAnalysisInput:
    return SpeechAnalysisInput(text=text, start_ms=start_ms, end_ms=end_ms, is_speaking=True)


# ── stress_score 계산 ─────────────────────────────────────────────────────────

class TestStressScore:
    @pytest.mark.anyio
    async def test_first_segment_no_wpm_penalty(self):
        """첫 세그먼트는 previous_wpm=0 대비 변화량이 스트레스에 반영되지 않아야 함"""
        service = SpeechAnalysisService()
        result = await service.analyze(make_input(
            "안녕하세요 저는 오늘 발표를 시작하겠습니다",
            start_ms=0, end_ms=3000
        ))
        assert result.stress_score < 0.1, (
            f"첫 세그먼트 stress_score가 너무 높음: {result.stress_score}"
        )

    @pytest.mark.anyio
    async def test_stress_accumulates_with_fillers(self):
        """필러가 많으면 stress_score가 올라야 함"""
        service = SpeechAnalysisService()
        result = await service.analyze(make_input(
            "음 어 그 있잖아요 음 어 그냥",
            start_ms=0, end_ms=3000
        ))
        assert result.stress_score > 0.2, (
            f"필러 많은데 stress_score가 너무 낮음: {result.stress_score}"
        )

    @pytest.mark.anyio
    async def test_stress_wpm_change_weight_reduced(self):
        """첫 세그먼트(wpm_change=0) → WPM 기여분 없이 필러 기여분만 반영"""
        service = SpeechAnalysisService()
        # 필러 없는 깔끔한 문장 → stress_score 거의 0
        result = await service.analyze(make_input(
            "이번 발표에서는 머신러닝 모델의 성능을 분석합니다", start_ms=0, end_ms=3000
        ))
        assert result.stress_score < 0.3, (
            f"필러 없는 첫 세그먼트의 stress_score가 너무 높음: {result.stress_score}"
        )

    @pytest.mark.anyio
    async def test_stress_score_does_not_exceed_1(self):
        """stress_score는 항상 1.0 이하"""
        service = SpeechAnalysisService()
        service.previous_wpm = 200
        result = await service.analyze(make_input(
            "음 어 그 있잖아요 음 어 뭐랄까",
            start_ms=1000, end_ms=2000
        ))
        assert result.stress_score <= 1.0


# ── _generate_feedback 임계값 ─────────────────────────────────────────────────

def make_result(**kwargs) -> SpeechAnalysisResult:
    defaults = dict(
        recent_wpm=120.0, average_wpm=120.0,
        filler_count=0, filler_count_segment=0,
        silence_duration=0, current_silence_ms=0,
        silence_count=0, response_latency=0,
        hesitation_score=0.0, stress_score=0.0,
    )
    defaults.update(kwargs)
    return SpeechAnalysisResult(**defaults)


class TestFeedbackThresholds:
    def test_wpm_130_no_feedback(self):
        """WPM 130은 이제 피드백 대상이 아님 (임계값 160으로 상향)"""
        result = make_result(recent_wpm=130.0)
        assert _generate_feedback(result) is None

    def test_wpm_160_no_feedback(self):
        """WPM 정확히 160은 피드백 없음 (초과만 해당)"""
        result = make_result(recent_wpm=160.0)
        assert _generate_feedback(result) is None

    def test_wpm_161_triggers_feedback(self):
        """WPM 161은 '말속도 너무 빠름' 피드백 트리거"""
        result = make_result(recent_wpm=161.0)
        fb = _generate_feedback(result)
        assert fb is not None and "빠릅니다" in fb

    def test_stress_07_no_feedback(self):
        """stress_score 0.7은 이제 피드백 대상 아님 (임계값 0.85로 상향)"""
        result = make_result(stress_score=0.7)
        assert _generate_feedback(result) is None

    def test_stress_085_no_feedback(self):
        """stress_score 정확히 0.85는 피드백 없음"""
        result = make_result(stress_score=0.85)
        assert _generate_feedback(result) is None

    def test_stress_086_triggers_feedback(self):
        """stress_score 0.86은 '긴장이 감지됩니다' 피드백 트리거"""
        result = make_result(stress_score=0.86)
        fb = _generate_feedback(result)
        assert fb is not None and "긴장" in fb

    def test_slow_wpm_still_triggers(self):
        """느린 말속도(< 60 WPM) 피드백은 그대로 동작"""
        result = make_result(recent_wpm=50.0)
        fb = _generate_feedback(result)
        assert fb is not None and "느립니다" in fb

    def test_filler_threshold_unchanged(self):
        """필러 3개 이상 피드백은 변경 없음"""
        result = make_result(filler_count_segment=3)
        fb = _generate_feedback(result)
        assert fb is not None and "필러" in fb
