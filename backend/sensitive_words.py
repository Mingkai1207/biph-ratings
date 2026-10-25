"""Non-destructive, deterministic review word masking metadata.

The stored comment and existing API ``comment`` field stay unchanged. This
module only identifies display segments, including for reviews imported before
the filter existed. It is presentation moderation, not an access-control layer.
"""
from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Optional


_LEXICON = json.loads(Path(__file__).with_suffix(".json").read_text(encoding="utf-8"))
# A short, explicit separator set catches f.u.c.k / 傻 逼 without allowing a
# match to consume arbitrary words or a long run of punctuation.
_SEPARATOR = r"[.\-_*·•\s]{0,2}"
_LEET = {"a": "[a@4]", "e": "[e3]", "i": "[i1!]", "o": "[o0]",
         "s": "[s$5]", "t": "[t7]"}


def _word_pattern(word: str, *, english: bool) -> str:
    letters = [_LEET.get(char, re.escape(char)) if english else re.escape(char)
               for char in word]
    return _SEPARATOR.join(letters)


_ENGLISH_TERMS = sorted(_LEXICON["english"], key=len, reverse=True)
_ENGLISH = re.compile(
    r"(?<![a-z0-9])(?:"
    + "|".join(_word_pattern(word, english=True) for word in _ENGLISH_TERMS)
    + "|" + "|".join(re.escape(word) for word in sorted(
        _LEXICON["english_literal_aliases"], key=len, reverse=True))
    + r")(?![a-z0-9])"
)
_CHINESE = re.compile("|".join(
    _word_pattern(word, english=False)
    for word in sorted(_LEXICON["chinese"], key=len, reverse=True)
))


def _normalized_with_positions(text: str) -> tuple[str, list[int]]:
    """Normalize matching characters while retaining their original indices.

    One source character can expand (e.g. compatibility letters or casefolding)
    and format characters can disappear. Never use these offsets in JavaScript;
    slice the original Python string here and send complete text segments.
    """
    normalized = []
    positions = []
    for index, char in enumerate(text):
        for expanded in unicodedata.normalize("NFKC", char).casefold():
            if unicodedata.category(expanded) == "Cf":
                continue
            normalized.append(expanded)
            positions.append(index)
    return "".join(normalized), positions


@lru_cache(maxsize=2048)
def _sensitive_ranges(text: str) -> tuple[tuple[int, int], ...]:
    normalized, positions = _normalized_with_positions(text)
    ranges = []
    for pattern in (_ENGLISH, _CHINESE):
        for match in pattern.finditer(normalized):
            ranges.append((positions[match.start()], positions[match.end() - 1] + 1))
    merged = []
    for start, end in sorted(ranges):
        if merged and start < merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return tuple(merged)


def comment_segments(comment: Optional[str]) -> list[dict]:
    """Return exact original text in normal/sensitive spans, without mutation.

    English terms match whole words (with a small list of known inflections).
    Chinese terms are explicit multi-character phrases. The frontend blurs only
    sensitive spans, leaving punctuation, whitespace and ordinary text readable.
    Fresh lists/dicts prevent callers from changing the cached detection result.
    """
    if not comment:
        return []
    segments = []
    cursor = 0
    for start, end in _sensitive_ranges(comment):
        if start > cursor:
            segments.append({"text": comment[cursor:start], "sensitive": False})
        segments.append({"text": comment[start:end], "sensitive": True})
        cursor = end
    if cursor < len(comment):
        segments.append({"text": comment[cursor:], "sensitive": False})
    return segments
