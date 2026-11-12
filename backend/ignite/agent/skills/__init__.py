"""Skill implementations live one module each; the registry binds them."""

from backend.ignite.agent.skills import (
    analysis_narrative,
    daily_brief,
    draft_review,
    news_bias,
    postmortem,
)

__all__ = [
    "analysis_narrative",
    "daily_brief",
    "draft_review",
    "news_bias",
    "postmortem",
]
