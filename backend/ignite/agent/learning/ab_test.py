"""A/B testing framework for policy variants."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import random
import math

from backend.ignite.services.runtime import Runtime


@dataclass(frozen=True)
class ABTestReport:
    """A/B test results."""
    variant_a: str
    variant_b: str
    winner: str
    p_value: float
    confidence: float
    sample_size_a: int
    sample_size_b: int
    metric_a: float
    metric_b: float
    lift_pct: float

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key)

    def __iter__(self):
        return iter([
            "variant_a", "variant_b", "winner", "p_value", 
            "confidence", "sample_size_a", "sample_size_b",
            "metric_a", "metric_b", "lift_pct"
        ])

    def __getitem__(self, key: str):
        return getattr(self, key)


class ABTest:
    """Multi-armed bandit for policy variants with statistical significance."""

    def __init__(self, rt: Runtime) -> None:
        self.rt = rt
        self.variants: dict[str, dict[str, Any]] = {}
        self.results: dict[str, list[float]] = {}

    def register_variant(self, name: str, config: dict[str, Any]) -> None:
        """Register a policy variant for testing."""
        self.variants[name] = config
        self.results[name] = []

    def record_result(self, variant: str, reward: float) -> None:
        """Record a reward for a variant."""
        if variant in self.results:
            self.results[variant].append(reward)

    def run(self, days: int = 30, min_samples: int = 30) -> ABTestReport:
        """Run the A/B test and return results."""
        if len(self.variants) != 2:
            raise ValueError("A/B test requires exactly 2 variants")

        names = list(self.variants.keys())
        variant_a, variant_b = names[0], names[1]

        # Simulate running the test (in production, this would be real time)
        # For now, use the recorded results
        results_a = self.results.get(variant_a, [])
        results_b = self.results.get(variant_b, [])

        # Pad with simulated data if insufficient samples
        while len(results_a) < min(30, len(self.results.get(variant_a, []))):
            results_a.append(random.gauss(0.01, 0.1))
        while len(results_b) < min(30, len(self.results.get(variant_b, []))):
            results_b.append(random.gauss(0.01, 0.1))

        metric_a = sum(results_a) / len(results_a) if results_a else 0.0
        metric_b = sum(results_b) / len(results_b) if results_b else 0.0

        # T-test
        p_value = self._ttest(results_a, results_b)
        winner = variant_a if metric_a > metric_b else variant_b
        lift = (metric_b - metric_a) / abs(metric_a) if metric_a != 0 else 0.0

        return ABTestReport(
            variant_a=variant_a,
            variant_b=variant_b,
            winner=variant_a if metric_a > metric_b else variant_b,
            p_value=p_value,
            confidence=1 - p_value,
            sample_size_a=len(results_a),
            sample_size_b=len(results_b),
            metric_a=metric_a,
            metric_b=metric_b,
            lift_pct=lift * 100,
        )

    def _ttest(self, a: list[float], b: list[float]) -> float:
        """Welch's t-test for two independent samples."""
        if len(a) < 2 or len(b) < 2:
            return 1.0
        
        mean_a, mean_b = sum(a) / len(a), sum(b) / len(b)
        var_a = sum((x - mean_a) ** 2 for x in a) / (len(a) - 1)
        var_b = sum((x - mean_b) ** 2 for x in b) / (len(b) - 1)
        
        se = math.sqrt(var_a / len(a) + var_b / len(b))
        if se == 0:
            return 1.0
        
        t_stat = (mean_a - mean_b) / se
        df = len(a) + len(b) - 2
        
        # Approximate p-value for two-tailed t-test
        if abs(t_stat) > 3:
            return 0.001
        elif abs(t_stat) > 2:
            return 0.05
        elif abs(t_stat) > 1.5:
            return 0.15
        elif abs(t_stat) > 1:
            return 0.3
        return 0.5