import re

_FILLERS = {'어', '음', '그', '저', '뭐', '그냥', '좀', '아', '에', '이'}


class FillerDetector:
    async def count_fillers(self, text: str) -> int:
        return self._count_heuristic(text)

    def _count_heuristic(self, text: str) -> int:
        words = re.sub(r'[^가-힣a-z]', ' ', text.lower()).split()
        return sum(1 for w in words if w in _FILLERS)
