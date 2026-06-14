# 슬라이딩 윈도우 방식으로 발표 흐름과 주제 일관성을 추적하는 Context Tracker 서비스
# 최근 발화 transcript를 기반으로 현재 주제, 진행률, drift_score를 계산한다.

from collections import deque
from difflib import SequenceMatcher
from typing import List

from app.schemas.context import ContextTrackerInput, ContextTrackerResult


class ContextTrackerService:
    """
    Context Tracker 서비스

    주요 기능:
    - 슬라이딩 윈도우로 최근 발화 유지
    - 슬라이드 텍스트와 유사도 비교
    - 현재 주제 추적
    - 발표 진행률 계산
    - 주제 이탈(drift) 감지
    """

    def __init__(self, window_size: int = 5):
        self.window_size = window_size
        self.recent_context = deque(maxlen=window_size)
        self.current_slide_index = 0

    def update(self, data: ContextTrackerInput) -> ContextTrackerResult:
        """
        Context Tracker를 업데이트하고 결과를 반환한다.
        """
        transcript = data.transcript
        slide_texts = data.slide_texts

        # 1. topic shift 감지 (윈도우 업데이트 전 기존 맥락과 비교)
        topic_shift_detected = self._detect_topic_shift(transcript)

        # 2. 슬라이딩 윈도우 업데이트
        self.recent_context.append(transcript)

        # 3. 슬라이드와의 유사도 계산
        similarities = [
            self._calculate_similarity(transcript, slide)
            for slide in slide_texts
        ]

        if similarities:
            best_index = similarities.index(max(similarities))
            best_similarity = similarities[best_index]
        else:
            best_index = 0
            best_similarity = 0.0

        # 4. 현재 슬라이드 업데이트
        if best_similarity > 0.3:
            self.current_slide_index = best_index

        # 5. 진행률 계산
        progress_index = (
            self.current_slide_index / max(len(slide_texts), 1)
        )

        # 6. Drift Score 계산
        drift_score = 1.0 - best_similarity

        return ContextTrackerResult(
            current_topic=slide_texts[self.current_slide_index]
            if slide_texts else None,
            progress_index=round(progress_index, 3),
            drift_score=round(drift_score, 3),
            topic_shift_detected=topic_shift_detected,
            recent_context=list(self.recent_context)
        )

    def _detect_topic_shift(self, new_transcript: str) -> bool:
        """
        새 발화와 기존 슬라이딩 윈도우의 문자 바이그램 Jaccard 유사도가 낮으면 topic shift로 판단.
        한국어 조사·어미 변화로 단어 단위 비교는 오탐이 많아 바이그램(n=2) 방식을 사용한다.
        """
        if len(self.recent_context) < 2:
            return False
        similarities = [
            self._bigram_jaccard(new_transcript, ctx)
            for ctx in self.recent_context
        ]
        return (sum(similarities) / len(similarities)) < 0.1

    def _bigram_jaccard(self, s1: str, s2: str) -> float:
        s1_bg = set(s1[i:i + 2] for i in range(len(s1) - 1))
        s2_bg = set(s2[i:i + 2] for i in range(len(s2) - 1))
        union = len(s1_bg | s2_bg)
        return len(s1_bg & s2_bg) / union if union > 0 else 0.0

    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """
        두 텍스트 간 유사도를 계산한다.
        """
        return SequenceMatcher(
            None,
            text1.lower(),
            text2.lower()
        ).ratio()