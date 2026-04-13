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

        # 1. 슬라이딩 윈도우 업데이트
        self.recent_context.append(transcript)

        # 2. 슬라이드와의 유사도 계산
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

        # 3. 현재 슬라이드 업데이트
        if best_similarity > 0.3:
            self.current_slide_index = best_index

        # 4. 진행률 계산
        progress_index = (
            self.current_slide_index / max(len(slide_texts), 1)
        )

        # 5. Drift Score 계산
        drift_score = 1.0 - best_similarity

        return ContextTrackerResult(
            current_topic=slide_texts[self.current_slide_index]
            if slide_texts else None,
            progress_index=round(progress_index, 3),
            drift_score=round(drift_score, 3),
            recent_context=list(self.recent_context)
        )

    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """
        두 텍스트 간 유사도를 계산한다.
        """
        return SequenceMatcher(
            None,
            text1.lower(),
            text2.lower()
        ).ratio()