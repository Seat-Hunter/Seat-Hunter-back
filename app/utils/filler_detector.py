import re

try:
    from openai import AsyncOpenAI
    from app.core.config import settings
    _client = AsyncOpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None
except Exception:
    _client = None

# OpenAI 실패 시 폴백: 문맥과 무관하게 필러로 쓰이는 경우가 거의 없는 단어만 유지
_FALLBACK_PATTERNS = [
    r"\b어\b", r"\b음\b",
    r"\buh\b", r"\bum\b", r"\ber\b", r"\bah\b", r"\blike\b", r"\byou know\b",
]


class FillerDetector:
    async def count_fillers(self, text: str) -> int:
        if _client:
            try:
                return await self._count_with_llm(text)
            except Exception:
                pass
        return self._count_heuristic(text)

    async def _count_with_llm(self, text: str) -> int:
        response = await _client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": (
                    "다음 발화에서 내용 없이 습관적으로 삽입된 말버릇(필러)의 개수를 세세요.\n"
                    "'그 상황에서'의 '그', '저는'의 '저'처럼 문법적 의미가 있으면 제외합니다.\n"
                    "숫자만 답하세요.\n\n"
                    f"발화: \"{text}\""
                ),
            }],
            max_tokens=5,
            temperature=0,
        )
        content = response.choices[0].message.content.strip()
        match = re.search(r"\d+", content)
        return int(match.group()) if match else 0

    def _count_heuristic(self, text: str) -> int:
        count = 0
        for pattern in _FALLBACK_PATTERNS:
            count += len(re.findall(pattern, text.lower()))
        return count
