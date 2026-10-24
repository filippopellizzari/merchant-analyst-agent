"""Extract numeric mentions from free-form agent answers.

The extractor is deliberately conservative about what it *excludes*: dates,
standalone years, list markers, times and hex hashes are not numbers an agent
needs to ground. Everything else that looks like a quantity is returned and
left to the matcher (``merchant_eval.grounding``) to judge.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

Kind = Literal["money", "percent", "count", "plain"]


@dataclass(frozen=True)
class NumberMention:
    """A number as written in the answer.

    ``value`` is the fully resolved float (``1.2k`` -> 1200.0, ``-5%`` -> -5.0);
    ``decimals`` is the number of decimals *displayed* in the written digits
    (``1.2k`` -> 1, ``$1,234.50`` -> 2) and ``scale`` the multiplier implied by
    a k/M/B suffix. The matcher uses both to decide what "equal" means.
    """

    raw: str
    value: float
    kind: Kind
    start: int
    end: int
    decimals: int = 0
    scale: float = 1.0

    @property
    def is_integer(self) -> bool:
        return self.decimals == 0 and self.scale == 1.0 and float(self.value).is_integer()


_MONTH = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
    r"aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
)
_ORD = r"(?:st|nd|rd|th)?"

# Spans that must never yield a number mention.
_EXCLUDE_PATTERNS = [
    # ISO / slash / dash calendar dates
    re.compile(r"(?<!\d)\d{4}[-/]\d{1,2}[-/]\d{1,2}(?!\d)"),
    re.compile(r"(?<!\d)\d{1,2}[-/]\d{1,2}[-/]\d{4}(?!\d)"),
    # Times 10:30, 18:05:59
    re.compile(r"(?<!\d)\d{1,2}:\d{2}(?::\d{2})?(?!\d)"),
    # Month-name context: "December 2020", "Dec 1, 2020", "December 25", "1 January 2021"
    re.compile(rf"\b{_MONTH}\s+\d{{4}}\b", re.IGNORECASE),
    re.compile(rf"\b{_MONTH}\s+\d{{1,2}}{_ORD}\b(?:,?\s+\d{{4}}\b)?", re.IGNORECASE),
    re.compile(rf"\b\d{{1,2}}{_ORD}\s+{_MONTH}\b(?:,?\s+\d{{4}}\b)?", re.IGNORECASE),
    # Ordinal list markers at line start (optionally after markdown heading hashes)
    re.compile(r"^[ \t]*(?:#+[ \t]*)?\d+[.)](?=\s)", re.MULTILINE),
    # Hex hashes (at least one a-f, 8+ chars) such as sql_hash values
    re.compile(r"\b(?=[0-9a-f]*[a-f])[0-9a-f]{8,}\b"),
]

_NUMBER = re.compile(
    r"""
    (?<![\w.])                                   # not glued to a word / decimal
    (?P<sign1>[-−+])?
    (?P<cur>\$|US\$|USD\s?)?
    (?P<sign2>[-−+])?
    (?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+)
    (?P<scale>[kKmMbB])?
    (?![A-Za-z0-9]|\.\d)                          # 1.2kg, 5th, Q4 are not numbers
    (?P<suffix>\s?%|\s?percent\b|\s?(?:USD|dollars)\b)?
    """,
    re.VERBOSE,
)

_SCALES = {"k": 1e3, "m": 1e6, "b": 1e9}


def _excluded_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for pat in _EXCLUDE_PATTERNS:
        spans.extend(m.span() for m in pat.finditer(text))
    return spans


def _overlaps(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
    return any(start < e and s < end for s, e in spans)


def extract_numbers(text: str) -> list[NumberMention]:
    """Return every numeric mention in ``text`` in order of appearance."""
    spans = _excluded_spans(text)
    out: list[NumberMention] = []
    for m in _NUMBER.finditer(text):
        start, end = m.span()
        if _overlaps(start, end, spans):
            continue
        num = m.group("num")
        sign = m.group("sign1") or m.group("sign2") or ""
        if m.group("sign1") and m.group("sign2"):
            continue  # "-$-5" is noise
        digits = num.replace(",", "")
        decimals = len(digits.split(".")[1]) if "." in digits else 0
        scale = _SCALES[m.group("scale").lower()] if m.group("scale") else 1.0
        value = float(digits) * scale
        if sign in ("-", "−"):
            value = -value
        suffix = (m.group("suffix") or "").strip().lower()
        if m.group("cur") or suffix in ("usd", "dollars"):
            kind: Kind = "money"
        elif suffix in ("%", "percent"):
            kind = "percent"
        elif decimals == 0 and scale == 1.0:
            kind = "count"
        else:
            kind = "plain"
        if suffix in ("usd", "dollars", "percent") or suffix == "%":
            # keep the suffix in the span only for '%' and currency words
            end = m.end("suffix")
        else:
            end = m.end("scale") if m.group("scale") else m.end("num")
        raw = text[start:end]
        # Standalone years (plain integer, no separators / sign / currency / percent)
        if kind == "count" and not sign and "," not in num and 1900 <= value <= 2100:
            continue
        out.append(
            NumberMention(
                raw=raw,
                value=value,
                kind=kind,
                start=start,
                end=end,
                decimals=decimals,
                scale=scale,
            )
        )
    return out
