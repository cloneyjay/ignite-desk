"""Policy gradient optimization for sizing and exit parameters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from backend.ignite.services.runtime import Runtime


@dataclass(frozen=True)
class PolicyUpdate:
    """Proposed policy parameter update."""
    parameter: str
    old_value: float
    new_value: float
    expected_improvement: float
    confidence: float
    gradient: float


class PolicyGradient:
    """REINFORCE-style policy gradient for continuous parameters."""

    def __init__(self, rt: Runtime, learning_rate: float = 0.01, baseline: float = 0.0) -> None:
        self.rt = rt
        self.learning_rate = learning_rate
        self.baseline = baseline
        self.gradients: dict[str, list[float]] = {}
        self.rewards: list[float] = []

    def record_reward(self, reward: float) -> None:
        """Record a reward for policy gradient update."""
        self.rewards.append(reward)

    def update(self, params: dict[str, float], reward: float) -> dict[str, dict[str, Any]]:
        """Compute policy gradient updates for parameters."""
        self.record_reward(reward)
        
        updates = {}
        for param, value in params.items():
            if param not in self.gradients:
                self.gradients[param] = []
            
            # REINFORCE: gradient = (reward - baseline) * d(log_pi)/d(theta)
            # Simplified: gradient = (reward - baseline) * param
            grad = (reward - self.baseline) * params[param]
            self.gradients[param].append(grad)
            
            # Keep only recent gradients
            if len(self.gradients[param]) > 100:
                self.gradients[param] = self.gradients[param][-100:]
            
            # Update parameter
            avg_grad = np.mean(self.gradients[param]) if self.gradients[param] else 0.0
            new_value = params[param] + self.learning_rate * avg_grad
            
            # Clamp to reasonable bounds
            if "risk" in param.lower() or "leverage" in param.lower():
                new_value = max(0.001, min(new_value, 1.0))
            
            updates[param] = {
                "parameter": param,
                "old_value": params[param],
                "new_value": new_value,
                "expected_improvement": self.learning_rate * avg_grad * params[param],
                "confidence": min(1.0, len(self.gradients[param]) / 50.0),
                "gradient": avg_grad,
            }
        
        return updates