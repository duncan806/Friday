"""muto 대역폭 필터 v0 — 정규식 기반. (스펙 §5)

채널 스키마:
  action_taken  항상 허용
  where_stuck   항상 허용
  expected      LEVEL 2 에서만 허용
  intent        항상 차단

허용 필드 안에서도 목적/의도 서술로 판정된 문장은 드롭한다.
드롭 문장은 호출자가 reports/dropped/ 에 원문 보존한다.

알려진 한계(공개, U1): 의도 누출을 완전히 막을 수 없다.
이는 은폐하지 않고 dropped 로그의 감사 가능성으로 상쇄한다.
"""

import re

ALLOWED_ALWAYS = ("action_taken", "where_stuck")
ALLOWED_LEVEL2 = ("expected",)
PASSTHROUGH = ("deviation", "round")  # 채널 내용이 아닌 메타데이터

# 목적/의도 서술 패턴 (한국어 + 영어)
INTENT_PATTERNS = [
    r"위해", r"위한", r"하려고", r"하고\s*싶", r"싶어서", r"원해서", r"목적", r"의도",
    r"필요해서", r"쓰려고", r"려는\s*것", r"하기\s*위함",
    r"\bin order to\b", r"\bso that\b", r"\bbecause I want\b",
    r"\bmy goal\b", r"\bintend(?:s|ed|ing)?\b", r"\bpurpose\b", r"\btrying to\b",
]
_INTENT_RE = re.compile("|".join(INTENT_PATTERNS), re.IGNORECASE)

_SENT_SPLIT = re.compile(r"(?<=[.!?다요음됨])\s+|\n+")


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT_SPLIT.split(text) if s.strip()]


def apply_filter(report: dict, level: int) -> tuple[dict, list[str]]:
    """(통과한 보고 dict, 드롭된 문장 리스트) 반환."""
    allowed = set(ALLOWED_ALWAYS)
    if level >= 2:
        allowed |= set(ALLOWED_LEVEL2)

    kept: dict = {}
    dropped: list[str] = []

    for key, value in report.items():
        if key in PASSTHROUGH:
            kept[key] = value
            continue
        text = str(value) if value is not None else ""
        if key not in allowed:
            # intent 필드 및 미허용 필드(LEVEL 1의 expected 포함) 통째로 차단
            if text.strip():
                dropped.append(f"[{key}] {text.strip()}")
            continue
        keep_sents, drop_sents = [], []
        for sent in _split_sentences(text):
            (drop_sents if _INTENT_RE.search(sent) else keep_sents).append(sent)
        kept[key] = " ".join(keep_sents)
        dropped.extend(f"[{key}] {s}" for s in drop_sents)

    return kept, dropped
