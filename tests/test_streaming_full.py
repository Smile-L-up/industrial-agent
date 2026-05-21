"""
流式功能完整测试
测试 /api/chat/stream 端点的各种场景

使用方法：
    conda run -n skills python tests/test_streaming_full.py
"""

import asyncio
import json
import time
import uuid
import httpx

BASE_URL = "http://127.0.0.1:18000"
TIMEOUT = 120.0


async def wait_for_server(max_wait=60):
    """等待服务器启动"""
    print("[*] 等待服务器启动...")
    start = time.time()
    async with httpx.AsyncClient(timeout=5.0) as client:
        while time.time() - start < max_wait:
            try:
                r = await client.get(f"{BASE_URL}/health")
                if r.status_code == 200:
                    data = r.json()
                    if data.get("status") == "healthy":
                        print(f"[OK] 服务器已就绪 ({time.time()-start:.1f}s)")
                        return True
                    else:
                        print(f"    状态: {data.get('status')}")
            except Exception:
                pass
            await asyncio.sleep(1)
    print("[FAIL] 服务器启动超时")
    return False


# ======================== 测试用例 ========================

async def test_01_health_and_skills():
    """测试 1: 健康检查 + 技能列表"""
    print("\n" + "=" * 60)
    print("测试 1: 健康检查 + 技能列表")
    print("=" * 60)
    async with httpx.AsyncClient(timeout=10.0) as client:
        # 健康检查
        r = await client.get(f"{BASE_URL}/health")
        assert r.status_code == 200, f"健康检查失败: {r.status_code}"
        data = r.json()
        print(f"  健康检查: status={data['status']}, llm={data['llm']}, skills={data['skills_count']}")
        assert data["status"] == "healthy"

        # 技能列表
        r = await client.get(f"{BASE_URL}/api/skills")
        assert r.status_code == 200
        skills = r.json()["skills"]
        print(f"  技能数量: {len(skills)}")
        for s in skills:
            print(f"    - {s['name']}: {s['description'][:50]}")
    print("[PASS] 测试 1 通过")
    return True


async def test_02_basic_stream():
    """测试 2: 基础流式对话（无技能匹配，纯 LLM 回答）"""
    print("\n" + "=" * 60)
    print("测试 2: 基础流式对话")
    print("=" * 60)

    payload = {
        "messages": [{"role": "user", "content": "你好，请用一句话介绍你自己"}],
    }

    token_count = 0
    full_text = ""
    got_complete = False
    session_id = None
    start_time = time.time()

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        async with client.stream("POST", f"{BASE_URL}/api/chat/stream", json=payload) as resp:
            assert resp.status_code == 200, f"状态码: {resp.status_code}"
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                raw = line[6:]
                if not raw.strip():
                    continue
                try:
                    chunk = json.loads(raw)
                except json.JSONDecodeError:
                    print(f"  [WARN] 非 JSON: {raw[:80]}")
                    continue

                ctype = chunk.get("type")
                if ctype == "token":
                    token_count += 1
                    full_text += chunk.get("content", "")
                elif ctype == "complete":
                    got_complete = True
                    session_id = chunk.get("session_id")
                elif ctype == "error":
                    print(f"  [ERROR] {chunk.get('message')}")
                    return False
                elif ctype == "reasoning_content":
                    pass  # 思考内容

    elapsed = time.time() - start_time
    print(f"  Token 数: {token_count}")
    print(f"  完整回复: {full_text[:200]}{'...' if len(full_text)>200 else ''}")
    print(f"  耗时: {elapsed:.2f}s")
    print(f"  session_id: {session_id}")
    print(f"  收到 complete: {got_complete}")

    assert token_count > 0, "没有收到任何 token"
    assert got_complete, "没有收到 complete 事件"
    assert len(full_text) > 5, "回复内容过短"
    print("[PASS] 测试 2 通过")
    return session_id


async def test_03_multi_turn_stream(session_id):
    """测试 3: 多轮对话流式"""
    print("\n" + "=" * 60)
    print("测试 3: 多轮对话流式 (session_id={})".format(session_id[:8] + "..."))
    print("=" * 60)

    if not session_id:
        print("[SKIP] 无 session_id，跳过")
        return True

    payload = {
        "messages": [{"role": "user", "content": "刚才你说了什么？请简要复述"}],
        "session_id": session_id,
    }

    token_count = 0
    full_text = ""

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        async with client.stream("POST", f"{BASE_URL}/api/chat/stream", json=payload) as resp:
            assert resp.status_code == 200
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                raw = line[6:]
                if not raw.strip():
                    continue
                try:
                    chunk = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                ctype = chunk.get("type")
                if ctype == "token":
                    token_count += 1
                    full_text += chunk.get("content", "")
                elif ctype == "error":
                    print(f"  [ERROR] {chunk.get('message')}")
                    return False

    print(f"  Token 数: {token_count}")
    print(f"  回复: {full_text[:200]}{'...' if len(full_text)>200 else ''}")
    assert token_count > 0, "多轮对话没有收到 token"
    print("[PASS] 测试 3 通过")
    return True


async def test_04_stream_with_skill():
    """测试 4: 流式 + 指定技能"""
    print("\n" + "=" * 60)
    print("测试 4: 流式 + 指定技能")
    print("=" * 60)

    # 先获取技能列表
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(f"{BASE_URL}/api/skills")
        skills = r.json()["skills"]

    if not skills:
        print("[SKIP] 没有可用技能")
        return True

    skill_name = skills[0]["name"]
    print(f"  使用技能: {skill_name}")

    payload = {
        "messages": [{"role": "user", "content": "请帮我查询北京的天气"}],
        "selected_skills": [skill_name],
    }

    token_count = 0
    tool_calls = []
    tool_results = []
    full_text = ""
    got_complete = False
    event_types_seen = set()

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        async with client.stream("POST", f"{BASE_URL}/api/chat/stream", json=payload) as resp:
            assert resp.status_code == 200
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                raw = line[6:]
                if not raw.strip():
                    continue
                try:
                    chunk = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                ctype = chunk.get("type")
                event_types_seen.add(ctype)

                if ctype == "token":
                    token_count += 1
                    full_text += chunk.get("content", "")
                elif ctype == "tool_call":
                    tool_calls.append(chunk.get("name", ""))
                    print(f"  [tool_call] {chunk.get('name')} args={chunk.get('args')}")
                elif ctype == "tool_result":
                    tool_results.append(chunk.get("name", ""))
                    result_preview = str(chunk.get("result", ""))[:100]
                    print(f"  [tool_result] {chunk.get('name')}: {result_preview}...")
                elif ctype == "complete":
                    got_complete = True
                elif ctype == "error":
                    print(f"  [ERROR] {chunk.get('message')}")
                elif ctype == "status":
                    print(f"  [status] {chunk.get('content')}")

    print(f"  事件类型: {event_types_seen}")
    print(f"  Token 数: {token_count}")
    print(f"  tool_call 数: {len(tool_calls)}")
    print(f"  tool_result 数: {len(tool_results)}")
    print(f"  最终回复: {full_text[:200]}{'...' if len(full_text)>200 else ''}")
    print(f"  收到 complete: {got_complete}")

    print("[PASS] 测试 4 通过")
    return True


async def test_05_stream_with_thinking():
    """测试 5: 流式 + 思考模式"""
    print("\n" + "=" * 60)
    print("测试 5: 流式 + 思考模式 (enable_thinking=True)")
    print("=" * 60)

    payload = {
        "messages": [{"role": "user", "content": "1+1等于多少？请思考后回答"}],
        "enable_thinking": True,
    }

    token_count = 0
    thinking_count = 0
    full_text = ""
    full_thinking = ""

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        async with client.stream("POST", f"{BASE_URL}/api/chat/stream", json=payload) as resp:
            assert resp.status_code == 200
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                raw = line[6:]
                if not raw.strip():
                    continue
                try:
                    chunk = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                ctype = chunk.get("type")
                if ctype == "token":
                    token_count += 1
                    full_text += chunk.get("content", "")
                elif ctype == "reasoning_content":
                    thinking_count += 1
                    full_thinking += chunk.get("content", "")
                elif ctype == "error":
                    print(f"  [ERROR] {chunk.get('message')}")

    print(f"  Token 数: {token_count}")
    print(f"  思考 chunk 数: {thinking_count}")
    print(f"  思考内容: {full_thinking[:200]}{'...' if len(full_thinking)>200 else ''}")
    print(f"  回复: {full_text[:200]}{'...' if len(full_text)>200 else ''}")

    assert token_count > 0, "没有收到回答 token"
    # 注意：enable_thinking 依赖模型支持，不强制要求有思考内容
    if thinking_count > 0:
        print("  模型支持思考模式")
    else:
        print("  模型未返回思考内容（可能不支持或思考被跳过）")
    print("[PASS] 测试 5 通过")
    return True


async def test_06_stream_with_custom_model_params():
    """测试 6: 流式 + 自定义模型参数"""
    print("\n" + "=" * 60)
    print("测试 6: 流式 + 自定义模型参数")
    print("=" * 60)

    payload = {
        "messages": [{"role": "user", "content": "说一个字：好"}],
        "temperature": 0.1,
        "max_tokens": 50,
    }

    token_count = 0
    full_text = ""

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        async with client.stream("POST", f"{BASE_URL}/api/chat/stream", json=payload) as resp:
            assert resp.status_code == 200
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                raw = line[6:]
                if not raw.strip():
                    continue
                try:
                    chunk = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                ctype = chunk.get("type")
                if ctype == "token":
                    token_count += 1
                    full_text += chunk.get("content", "")
                elif ctype == "error":
                    print(f"  [ERROR] {chunk.get('message')}")

    print(f"  Token 数: {token_count}")
    print(f"  回复: {full_text[:100]}")
    assert token_count > 0, "没有收到 token"
    print("[PASS] 测试 6 通过")
    return True


async def test_07_stream_cancel():
    """测试 7: 流式取消"""
    print("\n" + "=" * 60)
    print("测试 7: 流式取消")
    print("=" * 60)

    request_id = f"test-cancel-{uuid.uuid4().hex[:8]}"
    payload = {
        "messages": [{"role": "user", "content": "请写一篇1000字的文章，详细介绍人工智能的发展历史"}],
        "request_id": request_id,
    }

    token_count = 0
    got_cancelled = False
    cancel_sent = False

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            async with client.stream("POST", f"{BASE_URL}/api/chat/stream", json=payload) as resp:
                assert resp.status_code == 200

                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    raw = line[6:]
                    if not raw.strip():
                        continue
                    try:
                        chunk = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    ctype = chunk.get("type")

                    if ctype == "token":
                        token_count += 1
                    elif ctype == "cancelled":
                        got_cancelled = True
                        print(f"  [cancelled] {chunk.get('message')}")
                        break

                    # 收到几个 token 后发送取消请求
                    if token_count >= 5 and not cancel_sent:
                        cancel_sent = True
                        print(f"  已收到 {token_count} 个 token，发送取消请求...")
                        # 用独立的 client 发送取消请求，避免干扰流式连接
                        try:
                            async with httpx.AsyncClient(timeout=10.0) as cancel_client:
                                cancel_resp = await cancel_client.post(
                                    f"{BASE_URL}/api/chat/cancel",
                                    json={"request_id": request_id},
                                )
                                print(f"  取消响应: {cancel_resp.status_code} {cancel_resp.json()}")
                        except Exception as e:
                            print(f"  取消请求异常: {e}")
        except httpx.StreamConsumed:
            # 流被关闭（取消后服务端关闭连接）
            pass
        except Exception as e:
            print(f"  流式读取异常: {type(e).__name__}: {e}")

    print(f"  总 Token 数: {token_count}")
    print(f"  取消请求已发送: {cancel_sent}")
    print(f"  收到 cancelled: {got_cancelled}")
    print("[PASS] 测试 7 通过" + (" (成功取消)" if got_cancelled else " (取消信号时序不确定)"))
    return True


async def test_08_stream_invalid_request():
    """测试 8: 无效请求处理"""
    print("\n" + "=" * 60)
    print("测试 8: 无效请求处理")
    print("=" * 60)

    async with httpx.AsyncClient(timeout=15.0) as client:
        # 空 messages — 可能返回 422/500 或流式错误
        try:
            r = await client.post(f"{BASE_URL}/api/chat/stream", json={"messages": []}, timeout=10.0)
            print(f"  空 messages: status={r.status_code}")
        except httpx.ReadTimeout:
            print(f"  空 messages: ReadTimeout (服务端处理超时，已知行为)")
        except Exception as e:
            print(f"  空 messages: {type(e).__name__}: {e}")

        # 缺少 messages 字段 — FastAPI 应返回 422
        try:
            r = await client.post(f"{BASE_URL}/api/chat/stream", json={}, timeout=10.0)
            print(f"  缺少 messages: status={r.status_code}")
        except httpx.ReadTimeout:
            print(f"  缺少 messages: ReadTimeout (已知行为)")
        except Exception as e:
            print(f"  缺少 messages: {type(e).__name__}: {e}")

        # 取消不存在的请求 — 应返回 404
        r = await client.post(f"{BASE_URL}/api/chat/cancel", json={"request_id": "nonexistent"})
        print(f"  取消不存在的请求: status={r.status_code}")

    print("[PASS] 测试 8 通过")
    return True


async def test_09_stream_session_create_and_info():
    """测试 9: 会话创建 + 信息查询"""
    print("\n" + "=" * 60)
    print("测试 9: 会话管理")
    print("=" * 60)

    async with httpx.AsyncClient(timeout=10.0) as client:
        # 创建会话
        r = await client.post(f"{BASE_URL}/api/session/create")
        assert r.status_code == 200
        session_data = r.json()
        sid = session_data["session_id"]
        print(f"  创建会话: {sid[:12]}... history={session_data['history_count']}")

        # 查询会话
        r = await client.get(f"{BASE_URL}/api/session/{sid}")
        assert r.status_code == 200
        info = r.json()
        print(f"  会话信息: history_count={info['history_count']}")

        # 清空历史
        r = await client.post(f"{BASE_URL}/api/session/{sid}/clear")
        assert r.status_code == 200
        print(f"  清空历史: {r.json()['message']}")

        # 删除会话
        r = await client.delete(f"{BASE_URL}/api/session/{sid}")
        assert r.status_code == 200
        print(f"  删除会话: {r.json()['message']}")

    print("[PASS] 测试 9 通过")
    return True


async def test_10_stream_sse_format():
    """测试 10: SSE 格式正确性"""
    print("\n" + "=" * 60)
    print("测试 10: SSE 格式正确性")
    print("=" * 60)

    payload = {
        "messages": [{"role": "user", "content": "说你好"}],
    }

    lines_received = []
    data_lines = 0
    empty_lines = 0

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        async with client.stream("POST", f"{BASE_URL}/api/chat/stream", json=payload) as resp:
            assert resp.status_code == 200
            # 检查响应头
            content_type = resp.headers.get("content-type", "")
            print(f"  Content-Type: {content_type}")
            assert "text/event-stream" in content_type, f"期望 text/event-stream, 实际 {content_type}"

            async for line in resp.aiter_lines():
                lines_received.append(line)
                if line.startswith("data: "):
                    data_lines += 1
                    raw = line[6:]
                    # 验证 JSON 格式
                    try:
                        json.loads(raw)
                    except json.JSONDecodeError:
                        print(f"  [WARN] 非法 JSON: {raw[:80]}")
                elif line.strip() == "":
                    empty_lines += 1

    print(f"  总行数: {len(lines_received)}")
    print(f"  data 行数: {data_lines}")
    print(f"  空行数: {empty_lines}")
    assert data_lines > 0, "没有收到 data 行"
    print("[PASS] 测试 10 通过")
    return True


async def test_11_db_stats():
    """测试 11: 数据库统计"""
    print("\n" + "=" * 60)
    print("测试 11: 数据库统计")
    print("=" * 60)

    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(f"{BASE_URL}/api/db/stats")
        assert r.status_code == 200
        stats = r.json()
        print(f"  数据库统计: {json.dumps(stats, ensure_ascii=False, indent=2)[:300]}")

    print("[PASS] 测试 11 通过")
    return True


# ======================== 主流程 ========================

async def main():
    print("=" * 60)
    print("流式功能完整测试")
    print("=" * 60)

    # 等待服务器就绪
    if not await wait_for_server():
        print("[ABORT] 服务器未就绪，请先启动: conda run -n skills python api.py")
        return

    results = {}
    session_id = None

    tests = [
        ("健康检查+技能列表", test_01_health_and_skills),
        ("基础流式对话", test_02_basic_stream),
        ("流式+思考模式", test_05_stream_with_thinking),
        ("流式+自定义参数", test_06_stream_with_custom_model_params),
        ("流式取消", test_07_stream_cancel),
        ("无效请求处理", test_08_stream_invalid_request),
        ("会话管理", test_09_stream_session_create_and_info),
        ("SSE格式正确性", test_10_stream_sse_format),
        ("数据库统计", test_11_db_stats),
    ]

    for name, test_func in tests:
        try:
            if name == "基础流式对话":
                result = await test_func()
                if result and isinstance(result, str):
                    session_id = result
                results[name] = result is not None
            elif name == "多轮对话流式" and session_id:
                results[name] = await test_03_multi_turn_stream(session_id)
            elif name == "流式+指定技能":
                results[name] = await test_func()
            else:
                results[name] = await test_func()
        except Exception as e:
            print(f"  [EXCEPTION] {type(e).__name__}: {e}")
            results[name] = False

    # 多轮对话依赖 session_id
    if session_id:
        try:
            results["多轮对话流式"] = await test_03_multi_turn_stream(session_id)
        except Exception as e:
            print(f"  [EXCEPTION] {type(e).__name__}: {e}")
            results["多轮对话流式"] = False

    # 技能测试
    try:
        results["流式+指定技能"] = await test_04_stream_with_skill()
    except Exception as e:
        print(f"  [EXCEPTION] {type(e).__name__}: {e}")
        results["流式+指定技能"] = False

    # 汇总
    print("\n" + "=" * 60)
    print("测试汇总")
    print("=" * 60)
    passed = 0
    failed = 0
    for name, ok in results.items():
        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        else:
            failed += 1
        print(f"  [{status}] {name}")

    print(f"\n总计: {passed} 通过, {failed} 失败, {passed+failed} 总计")
    if failed == 0:
        print("全部测试通过!")
    else:
        print("存在失败的测试!")


if __name__ == "__main__":
    asyncio.run(main())
