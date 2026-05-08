import sys
sys.path.insert(0, ".")

try:
    from agent.router import Router
    print("[OK] agent.router")
except Exception as e:
    print(f"[FAIL] agent.router: {e}")

try:
    from agent.executor import Executor
    print("[OK] agent.executor")
except Exception as e:
    print(f"[FAIL] agent.executor: {e}")

try:
    from agent.state import AgentState, BoundedList, ExecutionContext
    print("[OK] agent.state")
except Exception as e:
    print(f"[FAIL] agent.state: {e}")

try:
    from core.base_skill import BaseSkill
    print("[OK] core.base_skill")
except Exception as e:
    print(f"[FAIL] core.base_skill: {e}")

try:
    from core.logger import get_logger
    print("[OK] core.logger")
except Exception as e:
    print(f"[FAIL] core.logger: {e}")

try:
    from agent.routing_config import SKILL_KEYWORDS, get_skill_keywords
    print("[OK] agent.routing_config")
except Exception as e:
    print(f"[FAIL] agent.routing_config: {e}")

print("\nAll import tests completed.")