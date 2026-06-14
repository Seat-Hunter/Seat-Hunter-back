# 발표 발화 내용을 빠르게 분석하는 경량 NLP 서비스
# 매 발화마다 호출되며 키워드, 논리 전개 연결어, 주제 일치도, 간단한 주제 이탈 신호를 분석한다.

from collections import Counter
from typing import List

from app.schemas.analysis import AnalysisInput, NLPAnalysisResult


class NLPService:
    """
    룰 기반 경량 NLP 분석 서비스

    주요 기능
    - 키워드 추출
    - 논리 전개 연결어 탐지
    - 예상 주제와의 일치도 계산
    - 간단한 주제 이탈 판단
    - 발화 논리 구조 점수 계산
    """

    # 발표에서 자주 쓰이는 논리 연결어 목록
    DISCOURSE_MARKERS = [
        "먼저", "다음으로", "그리고", "또한", "반면", "하지만",
        "즉", "예를 들어", "정리하면", "결론적으로", "왜냐하면",
        "따라서", "한편", "요약하면"
    ]

    # 너무 흔해서 키워드로 보기 어려운 불용어 예시
    STOPWORDS = {
        "은", "는", "이", "가", "을", "를", "에", "의", "와", "과",
        "좀", "그리고", "그래서", "제가", "저는", "이제", "그", "이",
        "저", "것", "수", "등", "좀", "약간"
    }

    def analyze(self, data: AnalysisInput) -> NLPAnalysisResult:
        """
        입력 발화를 룰 기반으로 빠르게 분석한다.
        """
        text = data.text.strip()

        keywords = self._extract_keywords(text)
        discourse_markers = self._extract_discourse_markers(text)
        topic_match_score = self._calculate_topic_match_score(
            keywords=keywords,
            expected_topics=data.expected_topics
        )
        logic_structure_score = self._calculate_logic_structure_score(
            text=text,
            discourse_markers=discourse_markers
        )
        topic_shift_detected = self._detect_topic_shift(
            topic_match_score=topic_match_score,
            keywords=keywords,
            expected_topics=data.expected_topics
        )
        notes = self._build_notes(
            keywords=keywords,
            discourse_markers=discourse_markers,
            topic_match_score=topic_match_score,
            topic_shift_detected=topic_shift_detected,
            logic_structure_score=logic_structure_score
        )

        return NLPAnalysisResult(
            keywords=keywords,
            discourse_markers=discourse_markers,
            topic_match_score=round(topic_match_score, 3),
            topic_shift_detected=topic_shift_detected,
            logic_structure_score=round(logic_structure_score, 3),
            notes=notes,
        )

    def _extract_keywords(self, text: str) -> List[str]:
        """
        아주 단순한 룰 기반 키워드 추출
        - 공백 기준 분리
        - 짧은 조사/불용어 제거
        - 많이 나온 단어 우선 반환
        """
        tokens = [
            token.strip(".,!?()[]\"'")
            for token in text.split()
        ]
        filtered = [
            token for token in tokens
            if len(token) >= 2 and token not in self.STOPWORDS
        ]

        counter = Counter(filtered)
        return [word for word, _ in counter.most_common(5)]

    def _extract_discourse_markers(self, text: str) -> List[str]:
        """
        논리 전개 연결어를 찾아서 반환
        """
        found = []
        for marker in self.DISCOURSE_MARKERS:
            if marker in text:
                found.append(marker)
        return found

    def _calculate_topic_match_score(
        self,
        keywords: List[str],
        expected_topics: List[str]
    ) -> float:
        """
        예상 주제 키워드와 현재 발화 키워드의 단순 일치도를 계산
        """
        if not expected_topics:
            return 0.5

        expected_set = {topic.lower() for topic in expected_topics}
        keyword_set = {keyword.lower() for keyword in keywords}

        matched = len(expected_set.intersection(keyword_set))
        return matched / max(len(expected_set), 1)

    def _calculate_logic_structure_score(
        self,
        text: str,
        discourse_markers: List[str]
    ) -> float:
        """
        간단한 논리 구조 점수 계산
        기준:
        - 연결어가 있으면 가산점
        - 문장 길이가 너무 짧지 않으면 약간 가산점
        """
        score = 0.0

        if len(text) >= 10:
            score += 0.3

        if len(text) >= 20:
            score += 0.2

        score += min(len(discourse_markers) * 0.15, 0.5)

        return min(score, 1.0)

    def _detect_topic_shift(
        self,
        topic_match_score: float,
        keywords: List[str],
        expected_topics: List[str]
    ) -> bool:
        """
        주제 이탈을 간단히 감지
        - 예상 주제가 있는데 일치도가 너무 낮으면 이탈로 본다
        """
        if not expected_topics:
            return False

        if not keywords:
            return True

        return topic_match_score < 0.2

    def _build_notes(
        self,
        keywords: List[str],
        discourse_markers: List[str],
        topic_match_score: float,
        topic_shift_detected: bool,
        logic_structure_score: float
    ) -> List[str]:
        """
        사람이 보기 쉬운 간단한 해석 메시지 생성
        """
        notes = []

        if keywords:
            notes.append(f"핵심 키워드: {', '.join(keywords)}")
        else:
            notes.append("추출된 핵심 키워드가 적습니다.")

        if discourse_markers:
            notes.append(f"논리 연결어 감지: {', '.join(discourse_markers)}")
        else:
            notes.append("논리 연결어가 부족합니다.")

        notes.append(f"주제 일치도: {topic_match_score:.2f}")
        notes.append(f"논리 구조 점수: {logic_structure_score:.2f}")

        if topic_shift_detected:
            notes.append("주제 이탈 가능성이 있습니다.")

        return notes