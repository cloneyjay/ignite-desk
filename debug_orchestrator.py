from tests.conftest import build_runtime
from backend.ignite.agent.orchestrator import Orchestrator
from backend.ignite.llm.client import LLMResult
from pathlib import Path
import tempfile

with tempfile.TemporaryDirectory() as tmp:
    rt = build_runtime(Path(tmp))
    rt.realised_override = 0.0
    def realised_today():
        return {'realised_usd': 0.0}
    rt.realised_today = realised_today
    rt.seed_symbols()
    rt.config_service.update({'enabled': True, 'operating_mode': 'autonomous', 'execution_mode': 'shadow'})
    
    print('Config:', rt.config())
    print('Symbols:', rt.store.list_symbols())
    
    # Create a fake LLM that returns a decision
    class FakeLLM:
        def complete(self, messages, tools=None, tool_choice='auto', **kwargs):
            return LLMResult(
                text='{"symbol": "XAUUSD", "timeframe": "M15", "action": "LONG", "conviction": 0.82, "thesis": "test", "evidence": [], "failed_conditions": [], "entry": {"type": "market", "price": 0.0}, "risk": {"lots": 0.01, "sl": 3920.0, "tp": 3950.0}, "expected_rr": 2.5, "invalidate_if": [], "links": {"analysis_id": null, "draft_id": null, "decision_id": "test"}}',
                provider='fake', model='fake', latency_ms=1, tool_calls=None
            )
    rt.llm = FakeLLM()
    
    orch = Orchestrator(rt)
    decision = orch.run_cycle('XAUUSD', 'M15')
    print('Decision:', decision)
    print('Events:', rt.store.agent_events())