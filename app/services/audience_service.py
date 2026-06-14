# audience_service.py
# 발화 분석 결과를 바탕으로 청중 반응을 생성하는 서비스

import random
from app.schemas.speech_analysis import SpeechAnalysisResult


class AudienceService:
    """
    룰 기반 청중 반응 생성 서비스

    반응 종류:
    - nodding: 고개 끄덕임 (발표 흐름 좋을 때)
    - interested: 관심 (적절한 속도, 적은 필러)
    - confused: 혼란 (주제 이탈, 필러 급증)
    - cold: 무관심 (너무 빠르거나 느린 속도)
    - applause: 박수 (훌륭한 답변 후)
    - raising: 손들기 (질문하려는 상태)
    """

    def __init__(self):
        self.consecutive_good = 0   # 연속 좋은 발화 횟수
        self.consecutive_bad = 0    # 연속 나쁜 발화 횟수
        self.last_reaction = None

    def evaluate(self, analysis: SpeechAnalysisResult) -> dict:
        """
        분석 결과를 바탕으로 청중 반응 결정
        """
        wpm = analysis.recent_wpm
        filler = analysis.filler_count_segment   # 이번 세그먼트 필러만 사용
        stress = analysis.stress_score
        silence = analysis.current_silence_ms    # 직전 침묵 간격만 사용

        reaction, intensity, reason = self._decide_reaction(wpm, filler, stress, silence)

        self.last_reaction = reaction
        return {
            "type": "audience_reaction",
            "reaction": reaction,
            "intensity": round(intensity, 2),
            "reason": reason,
        }

    def evaluate_after_answer(self, answer_score: float) -> dict:
        """
        답변 평가 후 청중 반응
        """
        if answer_score >= 85:
            return {
                "type": "audience_reaction",
                "reaction": "applause",
                "intensity": 0.9,
                "reason": "훌륭한 답변",
            }
        if answer_score >= 65:
            return {
                "type": "audience_reaction",
                "reaction": "nodding",
                "intensity": 0.7,
                "reason": "적절한 답변",
            }
        if answer_score >= 40:
            return {
                "type": "audience_reaction",
                "reaction": "confused",
                "intensity": 0.5,
                "reason": "답변 불충분",
            }
        return {
            "type": "audience_reaction",
            "reaction": "cold",
            "intensity": 0.8,
            "reason": "답변 매우 부족",
        }

    def _decide_reaction(
        self, wpm: float, filler: int, stress: float, silence: int
    ) -> tuple[str, float, str]:

        # 침묵이 길면 raising (질문하려는 듯)
        if silence > 4000:
            self.consecutive_bad += 1
            self.consecutive_good = 0
            return "raising", 0.8, "긴 침묵 감지"

        # WPM 너무 빠름
        if wpm > 170:
            self.consecutive_bad += 1
            self.consecutive_good = 0
            intensity = min(0.9, 0.5 + (wpm - 170) * 0.005)
            return "confused", round(intensity, 2), "말속도 너무 빠름"

        # WPM 너무 느림
        if wpm > 0 and wpm < 60:
            self.consecutive_bad += 1
            self.consecutive_good = 0
            return "cold", 0.6, "말속도 너무 느림"

        # 필러 많음 (per-segment 기준이므로 임계값 낮춤)
        if filler >= 3:
            self.consecutive_bad += 1
            self.consecutive_good = 0
            intensity = min(0.95, 0.4 + filler * 0.05)
            return "confused", round(intensity, 2), "필러 단어 많음"

        # 스트레스 높음
        if stress > 0.7:
            self.consecutive_bad += 1
            self.consecutive_good = 0
            return "cold", round(stress * 0.9, 2), "긴장 감지"

        # 좋은 상태
        if 80 <= wpm <= 150 and filler <= 2 and stress <= 0.4:
            self.consecutive_good += 1
            self.consecutive_bad = 0

            # 연속 3회 이상 좋으면 박수
            if self.consecutive_good >= 3:
                intensity = min(0.95, 0.6 + self.consecutive_good * 0.05)
                return "applause", round(intensity, 2), "훌륭한 발표 흐름"

            return "nodding", round(0.5 + self.consecutive_good * 0.1, 2), "좋은 발표 흐름"

        # 보통 상태
        self.consecutive_good = 0
        self.consecutive_bad = 0
        intensity = round(random.uniform(0.3, 0.6), 2)
        return "interested", intensity, "발표 진행 중"