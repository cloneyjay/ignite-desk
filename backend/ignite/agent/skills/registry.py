"""Skills discovery registry with budget cap and lazy loading."""

from __future__ import annotations

import ast
import importlib
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    loader: Callable[[], Any]
    enabled: bool = True


class SkillRegistry:
    def __init__(self, skills_dir: Path | str | None = None) -> None:
        if skills_dir is None:
            skills_dir = Path(__file__).parent
        self.skills_dir = Path(skills_dir)
        self._discovered: Dict[str, Skill] = {}
        self._loaded: Dict[str, Any] = {}
        self._discover_done = False

    def discover(self) -> None:
        if self._discover_done:
            return
        start = time.monotonic()
        scanned = 0
        budget_exceeded = False

        # Collect candidate files
        try:
            files = list(self.skills_dir.iterdir())
        except FileNotFoundError:
            files = []

        for file in files:
            if not file.is_file():
                continue
            if file.suffix != ".py":
                continue
            if file.name.startswith("_"):
                continue
            # Budget checks
            if scanned >= 50:
                budget_exceeded = True
                break
            if time.monotonic() - start > 0.2:
                budget_exceeded = True
                break

            scanned += 1
            try:
                source = file.read_text(encoding="utf-8")
                if "skill_meta" not in source:
                    continue
                tree = ast.parse(source, filename=str(file))
                meta: dict[str, Any] = {}
                # Only inspect top-level assignments for speed
                for node in tree.body:
                    if isinstance(node, ast.Assign):
                        for target in node.targets:
                            if isinstance(target, ast.Name) and target.id == "skill_meta":
                                if isinstance(node.value, ast.Dict):
                                    for k_node, v_node in zip(node.value.keys, node.value.values):
                                        try:
                                            k = ast.literal_eval(k_node)
                                            v = ast.literal_eval(v_node)
                                            if isinstance(k, str):
                                                meta[k] = v
                                        except Exception:
                                            continue
                                break
                        if meta:
                            break
                if meta and "name" in meta and "description" in meta:
                    name = str(meta["name"])
                    description = str(meta["description"])
                    module_name = f"backend.ignite.agent.skills.{file.stem}"
                    # Loader captures module name safely
                    def make_loader(mod_name: str) -> Callable[[], Any]:
                        def loader() -> Any:
                            return importlib.import_module(mod_name)
                        return loader
                    skill = Skill(name=name, description=description, loader=make_loader(module_name), enabled=True)
                    # Avoid overwriting existing
                    self._discovered.setdefault(name, skill)
            except Exception:
                # Skip unreadable / unparsable modules
                continue

        self._discover_done = True
        if budget_exceeded:
            self._audit_budget_exceeded(scanned)

    def _audit_budget_exceeded(self, scanned: int) -> None:
        try:
            from backend.ignite.store.db import Store
            store_path = Path("data/ignite.db")
            if store_path.exists():
                store = Store(store_path)
                try:
                    store.audit(
                        "skills_registry",
                        "discovery_budget_exceeded",
                        {"scanned": scanned, "budget_modules": 50, "budget_ms": 200},
                        result="budget_exceeded",
                    )
                finally:
                    try:
                        store.close()
                    except Exception:
                        pass
        except Exception:
            # Audit is best-effort
            pass

    def list_skills(self) -> List[Skill]:
        if not self._discover_done:
            self.discover()
        return list(self._discovered.values())

    def load(self, name: str) -> Any:
        if not self._discover_done:
            self.discover()
        skill = self._discovered.get(name)
        if skill is None:
            raise KeyError(f"Skill {name!r} not found")
        if name not in self._loaded:
            self._loaded[name] = skill.loader()
        return self._loaded[name]

    def get_skill(self, name: str) -> Skill | None:
        if not self._discover_done:
            self.discover()
        return self._discovered.get(name)
