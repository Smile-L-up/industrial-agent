"""验证 api.py 的导入和 AgentGraph 初始化路径"""
import sys
sys.path.insert(0, ".")

# 模拟 api.py 的初始化流程中的关键导入
try:
    from agent.graph import AgentGraph
    print("[OK] agent.graph")
except Exception as e:
    print(f"[FAIL] agent.graph: {e}")

try:
    from core.database import init_database, DatabaseManager
    print("[OK] core.database")
except Exception as e:
    print(f"[FAIL] core.database: {e}")

try:
    from llm.llm import get_llm
    print("[OK] llm.llm.get_llm")
except Exception as e:
    print(f"[FAIL] llm.llm.get_llm: {e}")

try:
    from core.skill_loader import SkillLoader
    print("[OK] core.skill_loader")
except Exception as e:
    print(f"[FAIL] core.skill_loader: {e}")

try:
    from core.image_uploader import ImageUploader
    print("[OK] core.image_uploader")
except Exception as e:
    print(f"[FAIL] core.image_uploader: {e}")

try:
    from core.image_store import ImageStore
    print("[OK] core.image_store")
except Exception as e:
    print(f"[FAIL] core.image_store: {e}")

# 验证 AgentGraph 构造函数能接受参数（不会立即报错）
try:
    import inspect
    sig = inspect.signature(AgentGraph.__init__)
    print(f"[OK] AgentGraph.__init__ signature: {sig}")
except Exception as e:
    print(f"[FAIL] AgentGraph signature: {e}")

print("\nAPI startup import tests completed.")