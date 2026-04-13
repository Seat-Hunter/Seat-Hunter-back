# 필러 단어(어, 음, uh, um 등)를 탐지하는 유틸리티 모듈

import re


class FillerDetector:
    """
    발화 중 사용된 필러 단어를 탐지하는 클래스
    """

    FILLER_WORDS = [
        "어", "음", "그", "저", "아",
        "uh", "um", "er", "ah", "like", "you know"
    ]

    def count_fillers(self, text: str) -> int:
        """텍스트에서 필러 단어 개수 계산"""
        count = 0
        for filler in self.FILLER_WORDS:
            count += len(re.findall(rf"\b{filler}\b", text.lower()))
        return count