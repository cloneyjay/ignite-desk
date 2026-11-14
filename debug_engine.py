from tests.conftest import build_runtime
from backend.ignite.agent.engine import AgentEngine
from backend.ignite.agent.decision import Decision, Entry, Risk, Links
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
    print('Symbols from store:', rt.store.list_symbols())
    
    # Create a fake LLM that returns a decision
    class FakeLLM:
        def complete(self, messages, tools=None, tool_choice='auto', **kwargs):
            return LLMResult(
                text='{"symbol": "XAUUSD", "timeframe": "M15", "action": "LONG", "conviction": 0.82, "thesis": "test", "evidence": [], "failed_conditions": [], "entry": {"type": "market", "price": 0.0}, "risk": {"lots": 0.01, "sl": 3920.0, "tp": 3950.0}, "expected_rr": 2.5, "invalidate_if": [], "links": {"analysis_id": null, "draft_id": null, "decision_id": "test"}}',
                provider='fake', model='fake', latency_ms=1, tool_calls=None
            )
    rt.llm = FakeLLM()
    
    engine = AgentEngine(rt, rt.config())
    print('Engine config symbols:', engine.config.symbols)
    print('Engine _get_symbols():', engine._get_symbols())
    
    # Call analyse_symbol directly
    decision = engine.analyse_symbol('XAUUSD', 'M15')
    print('Analyse symbol result:', decision)
    
    # Check agent_decisions
    print('Agent decisions:', rt.store.agent_decisions(limit=10))