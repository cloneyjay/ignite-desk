"""Markdown knowledge cards with YAML front-matter.

A card is a small, versioned piece of desk knowledge: a rule, the reason behind
it, and how it is applied in practice. The front-matter declares who may use it
(``scope``), which skills select it (``applies_to``), and which live facts it
interpolates. The body is plain markdown so a human can review it in git.

The parser is strict on purpose. A typo in a placeholder or a card marked
``reviewed`` without a reviewer must fail ``knowledge lint`` rather than quietly
reach a trading prompt.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

SCOPES = ("risk_manager", "market_analyst", "fundamentals_desk", "desk_analyst")
LAYERS = ("L1", "L2", "L3")
STATUSES = ("draft", "reviewed")
SKILL_IDS = (
    "analysis_narrative",
    "draft_review",
    "news_bias",
    "daily_brief",
    "postmortem",
)

ID_RE = re.compile(r"^[a-z][a-z0-9_.-]{2,64}$")
FRONT_MATTER_RE = re.compile(r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n(.*)$", re.S)
PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z0-9_.]+)\s*\}\}")
README_NAMES = {"readme.md", "index.md"}

REQUIRED = ("id", "title", "scope", "layer")


class CardError(ValueError):
    def __init__(self, source: str, issues: list[str]) -> None:
        self.source = source
        self.issues = issues
        super().__init__(f"{source}: {'; '.join(issues)}")


class RenderError(ValueError):
    pass


@dataclass(frozen=True)
class Card:
    id: str
    title: str
    scope: str
    layer: str
    version: int
    status: str
    reviewed_by: str | None
    priority: int
    tags: tuple[str, ...]
    facts: tuple[str, ...]
    applies_to: tuple[str, ...]
    max_words: int
    body: str
    source_path: str
    checksum: str

    @property
    def words(self) -> int:
        return len(self.body.split())

    def to_row(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "scope": self.scope,
            "layer": self.layer,
            "version": self.version,
            "status": self.status,
            "reviewed_by": self.reviewed_by,
            "priority": self.priority,
            "tags": list(self.tags),
            "facts": list(self.facts),
            "applies_to": list(self.applies_to),
            "max_words": self.max_words,
            "body": self.body,
            "source_path": self.source_path,
            "checksum": self.checksum,
        }


def _as_list(value: Any, field_name: str, issues: list[str]) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    issues.append(f"{field_name} must be a list or comma-separated string")
    return []


def checksum_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def placeholders(body: str) -> list[str]:
    return list(dict.fromkeys(PLACEHOLDER_RE.findall(body)))


def parse_card(text: str, source: str | Path) -> Card:
    source_path = str(source).replace("\\", "/")
    clean = text.lstrip("\ufeff")
    match = FRONT_MATTER_RE.match(clean)
    if not match:
        raise CardError(source_path, ["missing YAML front-matter delimited by ---"])
    raw_meta, body = match.groups()
    try:
        meta = yaml.safe_load(raw_meta) or {}
    except yaml.YAMLError as exc:
        raise CardError(source_path, [f"invalid YAML: {exc}"]) from exc
    if not isinstance(meta, dict):
        raise CardError(source_path, ["front-matter must be a mapping"])

    issues: list[str] = []
    for key in REQUIRED:
        if not str(meta.get(key, "")).strip():
            issues.append(f"missing required field {key}")

    card_id = str(meta.get("id", "")).strip()
    if card_id and not ID_RE.match(card_id):
        issues.append(f"id {card_id!r} must match {ID_RE.pattern}")

    scope = str(meta.get("scope", "")).strip()
    if scope and scope not in SCOPES:
        issues.append(f"scope {scope!r} must be one of {list(SCOPES)}")

    layer = str(meta.get("layer", "")).strip().upper()
    if layer and layer not in LAYERS:
        issues.append(f"layer {layer!r} must be one of {list(LAYERS)}")

    status = str(meta.get("status", "draft")).strip().lower()
    if status not in STATUSES:
        issues.append(f"status {status!r} must be one of {list(STATUSES)}")
    reviewed_by = meta.get("reviewed_by")
    reviewed_by = str(reviewed_by).strip() if reviewed_by else None
    if status == "reviewed" and not reviewed_by:
        issues.append("status reviewed requires reviewed_by")

    try:
        version = int(meta.get("version", 1))
        if version < 1:
            issues.append("version must be >= 1")
    except (TypeError, ValueError):
        version = 1
        issues.append("version must be an integer")

    try:
        priority = int(meta.get("priority", 50))
    except (TypeError, ValueError):
        priority = 50
        issues.append("priority must be an integer")

    try:
        max_words = int(meta.get("max_words", 180))
        if max_words < 1:
            issues.append("max_words must be >= 1")
    except (TypeError, ValueError):
        max_words = 180
        issues.append("max_words must be an integer")

    tags = _as_list(meta.get("tags"), "tags", issues)
    facts = _as_list(meta.get("facts"), "facts", issues)
    applies_to = _as_list(meta.get("applies_to"), "applies_to", issues)

    if not applies_to:
        issues.append("applies_to must name at least one skill")
    for skill in applies_to:
        if skill not in SKILL_IDS:
            issues.append(f"unknown skill {skill!r} in applies_to")

    body = body.strip()
    if not body:
        issues.append("body is empty")

    used = placeholders(body)
    from backend.ignite.knowledge.facts import FACT_SPECS

    for name in used:
        if name not in FACT_SPECS:
            issues.append(f"unknown placeholder {{{{{name}}}}}")
        if name not in facts:
            issues.append(f"placeholder {{{{{name}}}}} is not declared in facts")
    for name in facts:
        if name not in FACT_SPECS:
            issues.append(f"unknown fact {name!r} in facts")
        elif name not in used:
            issues.append(f"declared fact {name!r} is never used in the body")

    if len(body.split()) > max_words:
        issues.append(
            f"body has {len(body.split())} words, above max_words {max_words}"
        )

    if issues:
        raise CardError(source_path, issues)

    return Card(
        id=card_id,
        title=str(meta["title"]).strip(),
        scope=scope,
        layer=layer,
        version=version,
        status=status,
        reviewed_by=reviewed_by,
        priority=priority,
        tags=tuple(tags),
        facts=tuple(facts),
        applies_to=tuple(applies_to),
        max_words=max_words,
        body=body,
        source_path=source_path,
        checksum=checksum_of(clean),
    )


def render_card(card: Card | dict[str, Any], values: dict[str, str]) -> str:
    body = card.body if isinstance(card, Card) else str(card["body"])

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in values:
            raise RenderError(f"no value for placeholder {{{{{name}}}}}")
        return values[name]

    return PLACEHOLDER_RE.sub(replace, body)


@dataclass(frozen=True)
class LintIssue:
    source: str
    code: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"source": self.source, "code": self.code, "message": self.message}


@dataclass
class LoadResult:
    cards: list[Card] = field(default_factory=list)
    issues: list[LintIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues

    @property
    def errors(self) -> list[dict[str, str]]:
        return [issue.as_dict() for issue in self.issues]


def _card_files(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    return sorted(
        path
        for path in directory.rglob("*.md")
        if path.name.lower() not in README_NAMES
    )


def load_cards(directory: Path | str) -> LoadResult:
    root = Path(directory)
    result = LoadResult()
    seen: dict[str, str] = {}
    for path in _card_files(root):
        try:
            card = parse_card(path.read_text(encoding="utf-8"), path)
        except CardError as exc:
            result.issues.extend(
                LintIssue(exc.source, "parse", message) for message in exc.issues
            )
            continue
        except OSError as exc:
            result.issues.append(LintIssue(str(path), "io", str(exc)))
            continue
        if card.id in seen:
            result.issues.append(
                LintIssue(
                    card.source_path,
                    "duplicate_id",
                    f"id {card.id!r} already declared by {seen[card.id]}",
                )
            )
            continue
        seen[card.id] = card.source_path
        result.cards.append(card)
    return result
