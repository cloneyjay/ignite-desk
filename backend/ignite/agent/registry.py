"""The skill registry. One entry per task the desk can ask the model to do."""

from __future__ import annotations

from backend.ignite.agent.contracts import SkillSpec
from backend.ignite.agent.skills import (
    analysis_narrative,
    daily_brief,
    draft_review,
    news_bias,
    postmortem,
)

SKILLS: dict[str, SkillSpec] = {
    analysis_narrative.SPEC.id: analysis_narrative.SPEC,
    daily_brief.SPEC.id: daily_brief.SPEC,
    draft_review.SPEC.id: draft_review.SPEC,
    news_bias.SPEC.id: news_bias.SPEC,
    postmortem.SPEC.id: postmortem.SPEC,
}


class UnknownSkill(KeyError):
    pass


def get_skill(skill_id: str) -> SkillSpec:
    try:
        return SKILLS[skill_id]
    except KeyError as exc:
        raise UnknownSkill(f"unknown skill {skill_id!r}") from exc
