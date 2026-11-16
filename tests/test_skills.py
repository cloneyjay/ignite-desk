"""Tests for skills discovery registry."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from backend.ignite.agent.skills.registry import SkillRegistry


def test_discovery_respects_module_cap(tmp_path: Path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    # Create 55 dummy modules with skill_meta
    for i in range(55):
        f = skills_dir / f"dummy_{i}.py"
        f.write_text(f"skill_meta = {{'name': 'dummy_{i}', 'description': 'desc {i}'}}")
    registry = SkillRegistry(skills_dir=skills_dir)
    skills = registry.list_skills()
    # Cap at 50 modules scanned
    assert len(skills) == 50
    names = {s.name for s in skills}
    # Ensure we got 50 distinct names
    assert len(names) == 50


def test_lazy_load(tmp_path: Path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    # Module that defines a marker
    f = skills_dir / "lazy_mod.py"
    f.write_text("skill_meta = {'name': 'lazy_skill', 'description': 'lazy'}\nMARKER = 123\n")
    registry = SkillRegistry(skills_dir=skills_dir)
    # After discover, module should not be imported yet
    module_name = "backend.ignite.agent.skills.lazy_mod"
    # Since we used a temp dir, the module name won't match actual import path, but we can check sys.modules
    # The registry builds loader with backend.ignite.agent.skills.{stem}, which won't be found for temp dir.
    # To test lazy loading properly, we use real skills dir with a temporary module.
    # Instead, create module in actual package path temporarily.
    # Simpler: check that load triggers import.
    # We'll create a real module in the actual skills directory for this test.
    real_skills_dir = Path(__file__).resolve().parent.parent / "backend" / "ignite" / "agent" / "skills"
    test_mod_path = real_skills_dir / "test_lazy_temp.py"
    mod_key = "backend.ignite.agent.skills.test_lazy_temp"
    try:
        test_mod_path.write_text("skill_meta = {'name': 'test_lazy_temp', 'description': 'temp'}\nLAZY = 'loaded'\n")
        # Ensure not imported
        sys.modules.pop(mod_key, None)
        registry2 = SkillRegistry(skills_dir=real_skills_dir)
        registry2.discover()
        assert mod_key not in sys.modules
        # Load should import
        mod = registry2.load("test_lazy_temp")
        assert mod_key in sys.modules
        assert getattr(mod, "LAZY") == "loaded"
    finally:
        if test_mod_path.exists():
            test_mod_path.unlink()
        sys.modules.pop(mod_key, None)


def test_registry_lookup_metadata():
    registry = SkillRegistry()
    registry.discover()
    skill = registry.get_skill("example_math")
    assert skill is not None
    assert skill.name == "example_math"
    assert "math" in skill.description.lower()
    assert skill.enabled is True

    skill2 = registry.get_skill("example_time")
    assert skill2 is not None
    assert skill2.name == "example_time"
