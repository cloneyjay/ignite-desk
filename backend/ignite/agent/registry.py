"""The skill registry. One entry per task the desk can ask the model to do."""

from __future__ import annotations

from backend.ignite.agent.contracts import SkillSpec
from backend.ignite.agent.skills import analysis_narrative

SKILLS: dict[str, SkillSpec] = {
    analysis_narrative.SPEC.id: analysis_narrative.SPEC,
}


class UnknownSkill(KeyError):
    pass


def get_skill(skill_id: str) -> SkillSpec:
    try:
        return SKILLS[skill_id]
    except KeyError as exc:
        raise UnknownSkill(f"unknown skill {skill_id!r}") from exc
