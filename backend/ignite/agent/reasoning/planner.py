"""Agent planner: multi-step planning with LLM tool decomposition."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from backend.ignite.agent.tools import ToolRegistry
from backend.ignite.llm.client import LLMClient, LLMResult
from backend.ignite.services.runtime import Runtime


@dataclass(frozen=True)
class PlanStep:
    """A single step in a plan."""
    tool: str
    args: dict[str, Any]
    expected_outcome: str
    success_criteria: str
    tool_result: dict[str, Any] | None = None
    status: str = "pending"  # pending, running, completed, failed


class Plan(BaseModel):
    """A multi-step execution plan."""
    model_config = ConfigDict(extra="forbid")

    plan_id: str
    goal: str
    steps: list[PlanStep]
    status: str = "created"  # created, running, completed, failed
    current_step: int = 0


class Planner:
    """Creates and executes multi-step plans using LLM tool decomposition."""

    def __init__(self, rt: Runtime) -> None:
        self.rt = rt
        self.tool_registry = ToolRegistry()
        self._plans: dict[str, Plan] = {}

    def create_plan(self, goal: str) -> Plan:
        """Decompose a goal into a sequence of tool calls."""
        if not goal or not goal.strip():
            raise ValueError("goal cannot be empty")

        plan_id = uuid.uuid4().hex

        # Get available tools for the current mode
        tools = self.tool_registry.get_available(
            self.rt.config().operating_mode,
            self.rt.kill_switch(),
            self.rt.config().autonomy_level,
        )

        # Build tool descriptions for the LLM
        tool_descriptions = []
        for tool in tools:
            tool_descriptions.append({
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema,
            })

        # Build the planning prompt
        system_prompt = self._build_system_prompt(tool_descriptions)
        user_prompt = f"Goal: {goal}\n\nCreate a step-by-step plan using the available tools."

        # Call LLM to generate plan
        resp = self.rt.llm.complete(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            tools=[{"type": "function", "function": {"name": "create_plan", "parameters": self._plan_schema()}}],
            tool_choice={"type": "function", "function": {"name": "create_plan"}},
        )

        # Parse the plan from LLM response
        if not resp.tool_calls:
            raise ValueError("LLM did not return a plan")

        tool_call = resp.tool_calls[0]
        if tool_call.name != "create_plan":
            raise ValueError(f"Unexpected tool call: {tool_call.name}")

        try:
            plan_data = tool_call.arguments
            steps = []
            for step_data in plan_data.get("steps", []):
                step = PlanStep(
                    tool=step_data["tool"],
                    args=step_data["args"],
                    expected_outcome=step_data["expected_outcome"],
                    success_criteria=step_data["success_criteria"],
                )
                steps.append(step)

            if not steps:
                raise ValueError("Plan must have at least one step")

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            raise ValueError(f"Invalid plan format: {e}") from e

        plan = Plan(
            plan_id=plan_id,
            goal=goal,
            steps=steps,
        )

        self._plans[plan_id] = plan
        return plan

    def execute_plan(self, plan_id: str) -> dict[str, Any]:
        """Execute a plan step by step."""
        plan = self._plans.get(plan_id)
        if not plan:
            raise ValueError(f"Plan not found: {plan_id}")

        if plan.status != "created":
            raise ValueError(f"Plan already executed or in progress: {plan.status}")

        plan.status = "running"
        results = []

        for i, step in enumerate(plan.steps):
            plan.current_step = i
            step.status = "running"

            # Find the tool
            tool = self.tool_registry._tools.get(step.tool)
            if not tool:
                step.status = "failed"
                step.tool_result = {"error": f"Unknown tool: {step.tool}"}
                plan.status = "failed"
                break

            # Validate input
            try:
                validated_args = tool.validate_input(step.args)
            except Exception as e:
                step.status = "failed"
                step.tool_result = {"error": f"Invalid arguments: {e}"}
                plan.status = "failed"
                break

            # Execute tool
            try:
                import asyncio
                result = asyncio.run(tool.handler(self.rt, validated_args))
                result = tool.validate_output(result)
            except Exception as e:
                step.status = "failed"
                step.tool_result = {"error": f"Tool execution failed: {e}"}
                plan.status = "failed"
                break

            # Validate success criteria
            if not self._check_success_criteria(step, result):
                step.status = "failed"
                step.tool_result = result
                plan.status = "failed"
                break

            step.status = "completed"
            step.tool_result = result
            results.append({"step": i, "tool": step.tool, "result": result})

        if plan.status == "running":
            plan.status = "completed"

        return {
            "plan_id": plan_id,
            "status": plan.status,
            "results": results,
        }

    def get_plan(self, plan_id: str) -> Plan | None:
        return self._plans.get(plan_id)

    # --- Helpers ---

    def _build_system_prompt(self, tool_descriptions: list[dict]) -> str:
        tool_list = "\n".join(
            f"- {t['name']}: {t['description']}\n  Parameters: {json.dumps(t['parameters'], indent=2)}"
            for t in tool_descriptions
        )
        return (
            "You are a trading agent planner. Break down the user's goal into a sequence of tool calls.\n"
            "Each step must specify the tool, arguments, expected outcome, and success criteria.\n"
            "Only use tools from the available list. Do not invent tools.\n"
            "Return the plan as a tool call to 'create_plan' with the required schema.\n\n"
            f"Available tools:\n{tool_list}"
        )

    def _plan_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "tool": {"type": "string"},
                            "args": {"type": "object"},
                            "expected_outcome": {"type": "string"},
                            "success_criteria": {"type": "string"},
                        },
                        "required": ["tool", "args", "expected_outcome", "success_criteria"],
                    },
                },
            },
            "required": ["steps"],
        }

    def _check_success_criteria(self, step: PlanStep, result: dict[str, Any]) -> bool:
        """Validate that the tool result meets the success criteria."""
        criteria = step.success_criteria.lower()
        result_str = str(result).lower()

        # Simple keyword-based validation
        keywords = [w for w in criteria.split() if len(w) > 3]
        return any(kw in result_str for kw in keywords) if keywords else True