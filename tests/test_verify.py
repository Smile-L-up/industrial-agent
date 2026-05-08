"""验证所有修改后的模块可以正常导入"""
import sys
sys.path.insert(0, '.')

errors = []

# 1. 验证 config.py
try:
    from config import LLM_CONFIG, DATABASE_CONFIG, SESSION_CONFIG
    print("[OK] config.py - LLM_CONFIG, DATABASE_CONFIG, SESSION_CONFIG")
    # 验证没有硬编码密钥
    api_key = LLM_CONFIG.get("api_key", "")
    if api_key and not api_key.startswith("${") and "your" not in api_key.lower():
        print(f"  [WARN] API key may be hardcoded: {api_key[:10]}...")
    else:
        print(f"  [OK] API key is from env or placeholder")
except Exception as e:
    errors.append(f"config.py: {e}")
    print(f"[FAIL] config.py: {e}")

# 2. 验证 core/logger.py
try:
    from core.logger import setup_logging, get_logger
    setup_logging()
    test_logger = get_logger("test")
    test_logger.info("日志系统测试消息")
    print("[OK] core/logger.py - setup_logging, get_logger")
except Exception as e:
    errors.append(f"core/logger.py: {e}")
    print(f"[FAIL] core/logger.py: {e}")

# 3. 验证 core/database.py
try:
    from core.database import DatabaseManager, init_database, get_database
    print("[OK] core/database.py - DatabaseManager, init_database, get_database")
except Exception as e:
    errors.append(f"core/database.py: {e}")
    print(f"[FAIL] core/database.py: {e}")

# 4. 验证 agent/graph.py
try:
    from agent.graph import AgentGraph
    print("[OK] agent/graph.py - AgentGraph")
except Exception as e:
    errors.append(f"agent/graph.py: {e}")
    print(f"[FAIL] agent/graph.py: {e}")

# 5. 验证 agent/router.py
try:
    from agent.router import Router
    print("[OK] agent/router.py - Router")
except Exception as e:
    errors.append(f"agent/router.py: {e}")
    print(f"[FAIL] agent/router.py: {e}")

# 6. 验证 agent/executor.py
try:
    from agent.executor import Executor
    print("[OK] agent/executor.py - Executor")
except Exception as e:
    errors.append(f"agent/executor.py: {e}")
    print(f"[FAIL] agent/executor.py: {e}")

# 7. 验证 api.py
try:
    from api import app
    print("[OK] api.py - app")
except Exception as e:
    errors.append(f"api.py: {e}")
    print(f"[FAIL] api.py: {e}")

# 8. 验证 main.py
try:
    from main import main
    print("[OK] main.py - main")
except Exception as e:
    errors.append(f"main.py: {e}")
    print(f"[FAIL] main.py: {e}")

# 9. 验证 llm/llm.py
try:
    from llm.llm import get_llm
    print("[OK] llm/llm.py - get_llm")
except Exception as e:
    errors.append(f"llm/llm.py: {e}")
    print(f"[FAIL] llm/llm.py: {e}")

# 10. 验证 core/streaming.py
try:
    from core.streaming import StreamingResponse, StreamHandler, EventType
    print("[OK] core/streaming.py - StreamingResponse, StreamHandler, EventType")
except Exception as e:
    errors.append(f"core/streaming.py: {e}")
    print(f"[FAIL] core/streaming.py: {e}")

print("\n" + "=" * 50)
if errors:
    print(f"发现 {len(errors)} 个错误:")
    for e in errors:
        print(f"  - {e}")
else:
    print("所有模块导入验证通过！")
print("=" * 50)