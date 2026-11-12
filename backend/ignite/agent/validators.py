"""Output validators: numeric grounding, style, and no promises.

The model is allowed to sound like a desk analyst. It is not allowed to invent a
number. Every numeric token in the draft must round to a value from the context
payload or from a rendered desk card, and the prose must stay short, plain and
non-promissory.
"""

from __future__ import annotations

import math
import re
from typing import Any

TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_.])[-+]?\d[\d,]*(?:\.\d+)?%?")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
BANNED = (
    re.compile(r"\bguarantee(d|s)?\b", re.I),
    re.compile(r"\brisk[- ]free\b", re.I),
    re.compile(r"\bsure thing\b", re.I),
    re.compile(r"\bcan(no|')t lose\b", re.I),
    re.compile(r"\bwill (definitely|surely)\b", re.I),
    re.compile(r"\bI (have |just )?(executed|placed|sent|bought|sold)\b", re.I),
    re.compile(r"\bI (recommend|advise) (you )?to (buy|sell)\b", re.I),
)
MARKDOWN = re.compile(r"(^#{1,6}\s)|(^\s*[-*]\s)|(\*\*)", re.M)


def normalise(text: str) -> str:
    return text.replace("−", "-").replace("–", "-").replace("—", "-")


def collect_numbers(value: Any) -> set[float]:
    """Every number that appears anywhere in a structured value."""
    out: set[float] = set()

    def visit(item: Any) -> None:
        if item is None or isinstance(item, bool):
            return
        if isinstance(item, (int, float)):
            if math.isfinite(float(item)):
                out.add(float(item))
            return
        if isinstance(item, str):
            for token in TOKEN_RE.findall(normalise(item)):
                text = token.rstrip("%")
                try:
                    number = float(text.replace(",", ""))
                except ValueError:
                    continue
                out.add(number)
                if token.endswith("%"):
                    out.add(number / 100.0)
            return
        if isinstance(item, dict):
            for child in item.values():
                visit(child)
            return
        if isinstance(item, (list, tuple, set)):
            for child in item:
                visit(child)

    visit(value)
    return out


def _decimal_places(token: str) -> int:
    text = token.rstrip("%").replace(",", "")
    if "." not in text:
        return 0
    return len(text.split(".", 1)[1])


def _matches(value: float, decimals: int, allowed: set[float]) -> bool:
    for candidate in allowed:
        if abs(candidate - value) <= 1e-9:
            return True
        if decimals <= 8 and round(candidate, decimals) == round(value, decimals):
            return True
    return False


def numeric_grounding(text: str, allowed: set[float]) -> dict[str, Any]:
    checked = 0
    violations: list[dict[str, str]] = []
    for match in TOKEN_RE.finditer(normalise(text)):
        token = match.group(0)
        raw = token.rstrip("%")
        try:
            value = float(raw.replace(",", ""))
        except ValueError:
            continue
        decimals = _decimal_places(token)
        candidates = [value]
        if token.endswith("%"):
            candidates.append(value / 100.0)
            decimals += 2
        checked += 1
        if any(_matches(candidate, decimals, allowed) for candidate in candidates):
            continue
        if 0 <= value <= 12 and value.is_integer():
            continue
        if len(violations) < 8:
            start = max(0, match.start() - 30)
            end = min(len(text), match.end() + 30)
            violations.append(
                {"token": token, "context": text[start:end].replace("\n", " ").strip()}
            )
    return {
        "ok": not violations,
        "numbers_checked": checked,
        "violations": violations,
    }


def style_check(text: str, max_words: int) -> dict[str, Any]:
    words = len(text.split())
    sentences = [part for part in SENTENCE_RE.split(text.strip()) if part.strip()]
    issues: list[str] = []
    if words > max_words:
        issues.append(f"{words} words exceeds the {max_words}-word budget")
    if len(sentences) > 6:
        issues.append(f"{len(sentences)} sentences; keep it to 2-4")
    if MARKDOWN.search(text):
        issues.append("markdown headings, bullets or bold are not allowed")
    for pattern in BANNED:
        banned = pattern.search(text)
        if banned:
            issues.append(f"banned phrase {banned.group(0)!r}")
    if not text.strip():
        issues.append("empty narrative")
    return {"ok": not issues, "issues": issues, "words": words, "sentences": len(sentences)}


def validate_text(text: str, allowed: set[float], max_words: int) -> dict[str, Any]:
    grounding = numeric_grounding(text, allowed)
    style = style_check(text, max_words)
    return {
        "ok": grounding["ok"] and style["ok"],
        "numbers_checked": grounding["numbers_checked"],
        "violations": grounding["violations"],
        "style_issues": style["issues"],
        "words": style["words"],
        "sentences": style["sentences"],
    }
