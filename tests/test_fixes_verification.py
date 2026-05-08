"""
验证修复的测试脚本
运行方式: python -m tests.test_fixes_verification
"""
import sys
import os
import tempfile
import shutil

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_bounded_list():
    """测试 BoundedList 容量限制"""
    from agent.state import BoundedList

    # 1. 基本 append 不超限
    bl = BoundedList(max_len=5)
    for i in range(3):
        bl.append(i)
    assert len(bl) == 3, f"Expected 3, got {len(bl)}"
    assert list(bl) == [0, 1, 2]

    # 2. 超出后自动从头部裁剪
    for i in range(3, 8):
        bl.append(i)
    assert len(bl) == 5, f"Expected 5, got {len(bl)}"
    assert list(bl) == [3, 4, 5, 6, 7], f"Got {list(bl)}"

    # 3. extend 也受限制
    bl2 = BoundedList(max_len=3)
    bl2.extend([10, 20, 30, 40, 50])
    assert len(bl2) == 3, f"Expected 3, got {len(bl2)}"
    assert list(bl2) == [30, 40, 50], f"Got {list(bl2)}"

    # 4. 初始数据超限也会裁剪（通过位置参数传入可迭代对象）
    bl3 = BoundedList(2, [1, 2, 3, 4])
    assert len(bl3) == 2, f"Expected 2, got {len(bl3)}"
    assert list(bl3) == [3, 4], f"Got {list(bl3)}"

    print("[PASS] BoundedList 所有测试通过")


def test_agent_state():
    """测试 AgentState 使用 BoundedList"""
    from agent.state import AgentState

    state = AgentState()

    # 1. messages 应该是 BoundedList
    from agent.state import BoundedList
    assert isinstance(state.messages, BoundedList), \
        f"messages type: {type(state.messages)}"

    # 2. 添加大量消息后应自动裁剪
    for i in range(150):
        state.add_message("user", f"msg_{i}")
    assert len(state.messages) <= 100, \
        f"Expected <= 100, got {len(state.messages)}"

    # 3. tool_calls 也应有上限
    assert isinstance(state.tool_calls, BoundedList)
    for i in range(250):
        state.execution_record.add_tool_call(f"tool_{i}", {"idx": i})
    assert len(state.tool_calls) <= 200, \
        f"Expected <= 200, got {len(state.tool_calls)}"

    # 4. 向后兼容：to_dict 不报错
    d = state.to_dict()
    assert "messages" in d
    assert "tool_calls" in d

    print("[PASS] AgentState 所有测试通过")


def test_database_singleton():
    """测试 DatabaseManager 单例模式"""
    from core.database import DatabaseManager, _db_init_lock
    import threading

    # 清理单例状态
    DatabaseManager._instances = {}
    DatabaseManager._initialized_fingerprints = set()

    tmp_dir = tempfile.mkdtemp()
    db_path = os.path.join(tmp_dir, "test.db")

    try:
        # 1. 相同配置应返回同一实例
        db1 = DatabaseManager(db_type="sqlite", db_path=db_path)
        db2 = DatabaseManager(db_type="sqlite", db_path=db_path)
        assert db1 is db2, "Same config should return same instance"
        print("[PASS] 单例相同配置返回同一实例")

        # 2. 不同配置应返回不同实例
        db_path2 = os.path.join(tmp_dir, "test2.db")
        db3 = DatabaseManager(db_type="sqlite", db_path=db_path2)
        assert db3 is not db1, "Different config should return different instance"
        print("[PASS] 不同配置返回不同实例")

        # 3. 基本功能正常
        db1.create_session("test_session_1", {"key": "value"})
        session = db1.get_session("test_session_1")
        assert session is not None
        assert session["metadata"]["key"] == "value"
        print("[PASS] 会话创建和读取正常")

        # 4. 消息存储正常
        idx = db1.add_message("test_session_1", "user", "hello")
        assert idx == 0
        msgs = db1.get_messages("test_session_1")
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"
        print("[PASS] 消息存储正常")

        # 5. 统计信息正常
        stats = db1.get_stats()
        assert stats["session_count"] >= 1
        assert stats["message_count"] >= 1
        print("[PASS] 统计信息正常")

        # 6. 清理
        db1.delete_session("test_session_1")
        assert db1.get_session("test_session_1") is None
        print("[PASS] 会话删除正常")

        # 7. 并发创建测试
        DatabaseManager._instances = {}
        DatabaseManager._initialized_fingerprints = set()
        instances = []

        def create_db():
            db = DatabaseManager(db_type="sqlite", db_path=db_path)
            instances.append(id(db))

        threads = [threading.Thread(target=create_db) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 并发创建应返回同一实例
        assert len(set(instances)) == 1, \
            f"Concurrent creation produced {len(set(instances))} instances"
        print("[PASS] 并发创建返回同一实例")

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print("[PASS] DatabaseManager 所有测试通过")


def test_context_backward_compat():
    """测试 ExecutionContext 向后兼容"""
    from agent.state import ExecutionContext

    ctx = ExecutionContext()

    # 字典式访问
    ctx["custom_key"] = "custom_value"
    assert ctx["custom_key"] == "custom_value"
    assert ctx.get("custom_key") == "custom_value"
    assert ctx.get("nonexistent", "default") == "default"

    # 已知字段访问
    ctx.selected_skill = "weather"
    assert ctx["selected_skill"] == "weather"
    assert "selected_skill" in ctx

    # to_dict
    d = ctx.to_dict()
    assert d["selected_skill"] == "weather"
    assert d["custom_key"] == "custom_value"

    print("[PASS] ExecutionContext 向后兼容测试通过")


if __name__ == "__main__":
    print("=" * 60)
    print("  修复验证测试")
    print("=" * 60)

    tests = [
        ("BoundedList 容量限制", test_bounded_list),
        ("AgentState 集成", test_agent_state),
        ("DatabaseManager 单例", test_database_singleton),
        ("ExecutionContext 向后兼容", test_context_backward_compat),
    ]

    passed = 0
    failed = 0
    for name, fn in tests:
        print(f"\n--- {name} ---")
        try:
            fn()
            passed += 1
        except Exception as e:
            print(f"[FAIL] {name}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"  结果: {passed} 通过, {failed} 失败")
    print(f"{'=' * 60}")
    sys.exit(1 if failed else 0)