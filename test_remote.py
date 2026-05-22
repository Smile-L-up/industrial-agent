"""测试远程服务器流式功能"""
import requests
import json
import sys
import time
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE_URL = "http://192.168.110.201:18001"


def print_header(title):
    print(f"\n{'='*60}")
    print(f"{title}")
    print(f"{'='*60}")


def print_result(name, passed):
    status = "[PASS]" if passed else "[FAIL]"
    print(f"  {name}: {status}")


def collect_stream(response):
    """收集流式响应的所有事件"""
    events = {
        'skill_invoked': [],
        'tool_call': [],
        'tool_result': [],
        'token': [],
        'complete': [],
        'status': [],
        'error': [],
        'session_id': None,
        'full_response': '',
    }

    start_time = time.time()
    for line in response.iter_lines():
        if line:
            decoded = line.decode('utf-8')
            if decoded.startswith('data: '):
                try:
                    chunk_data = json.loads(decoded[6:])
                    chunk_type = chunk_data.get('type', 'unknown')

                    if chunk_type in events:
                        events[chunk_type].append(chunk_data)

                    if chunk_type == 'token':
                        events['full_response'] += chunk_data.get('content', '')

                    if 'session_id' in chunk_data:
                        events['session_id'] = chunk_data['session_id']

                except json.JSONDecodeError:
                    pass

    events['elapsed'] = time.time() - start_time
    events['chunk_count'] = sum(len(v) for k, v in events.items() if isinstance(v, list))
    return events


def test_streaming_skill(skill_name, query, description, timeout=60):
    """测试指定技能的流式输出"""
    print_header(f"{description}")

    url = f"{BASE_URL}/api/chat/stream"
    data = {
        "messages": [{"role": "user", "content": query}],
        "selected_skills": [skill_name]
    }

    try:
        response = requests.post(url, json=data, stream=True, timeout=timeout)
        print(f"状态码: {response.status_code}")

        events = collect_stream(response)

        print(f"耗时: {events['elapsed']:.2f}s")
        print(f"skill_invoked: {len(events['skill_invoked'])} ({events['skill_invoked'][0].get('skill_name') if events['skill_invoked'] else '-'})")

        if events['tool_call']:
            tc = events['tool_call'][0]
            print(f"tool_call: {tc.get('name')} (service_type={tc.get('service_type')})")

        print(f"tool_result: {len(events['tool_result'])}")
        print(f"token: {len(events['token'])}")
        print(f"complete: {len(events['complete'])}")
        print(f"error: {len(events['error'])}")

        if events['full_response']:
            print(f"响应: {events['full_response'][:120]}...")

        passed = (len(events['skill_invoked']) > 0 and
                  len(events['token']) > 0 and
                  len(events['complete']) > 0 and
                  len(events['error']) == 0)

        print_result(description, passed)
        return passed, events.get('session_id')

    except requests.exceptions.Timeout:
        print(f"超时 ({timeout}s)")
        print_result(description, False)
        return False, None
    except Exception as e:
        print(f"异常: {e}")
        print_result(description, False)
        return False, None


def test_no_skill(query, description):
    """测试无技能（LLM直接回答）"""
    print_header(f"{description}")

    url = f"{BASE_URL}/api/chat/stream"
    data = {
        "messages": [{"role": "user", "content": query}]
    }

    try:
        response = requests.post(url, json=data, stream=True, timeout=60)
        events = collect_stream(response)

        print(f"耗时: {events['elapsed']:.2f}s")
        print(f"token: {len(events['token'])}")
        print(f"complete: {len(events['complete'])}")
        print(f"error: {len(events['error'])}")

        if events['full_response']:
            print(f"响应: {events['full_response'][:120]}...")

        passed = (len(events['token']) > 0 and
                  len(events['complete']) > 0 and
                  len(events['error']) == 0)

        print_result(description, passed)
        return passed, events.get('session_id')

    except Exception as e:
        print(f"异常: {e}")
        print_result(description, False)
        return False, None


def test_multi_turn():
    """测试多轮对话"""
    print_header("多轮对话测试")

    session_id = None
    results = {}

    # 第一轮
    print("\n--- 第一轮：计算器 ---")
    url = f"{BASE_URL}/api/chat/stream"
    data = {
        "messages": [{"role": "user", "content": "帮我计算 100 + 200"}],
        "selected_skills": ["calculator"]
    }

    try:
        response = requests.post(url, json=data, stream=True, timeout=60)
        events = collect_stream(response)
        session_id = events.get('session_id')
        print(f"session_id: {session_id}")
        print(f"响应: {events['full_response'][:80]}...")
        results['turn1'] = len(events['token']) > 0
        print_result("第一轮", results['turn1'])
    except Exception as e:
        print(f"异常: {e}")
        results['turn1'] = False
        print_result("第一轮", False)

    if not session_id:
        print("无法获取 session_id")
        return False

    # 第二轮
    print("\n--- 第二轮：继续对话 ---")
    data = {
        "messages": [{"role": "user", "content": "再加上 50 是多少？"}],
        "session_id": session_id
    }

    try:
        response = requests.post(url, json=data, stream=True, timeout=60)
        events = collect_stream(response)
        print(f"响应: {events['full_response'][:80]}...")
        results['turn2'] = len(events['token']) > 0
        print_result("第二轮", results['turn2'])
    except Exception as e:
        print(f"异常: {e}")
        results['turn2'] = False
        print_result("第二轮", False)

    # 验证会话历史
    print("\n--- 验证会话历史 ---")
    try:
        response = requests.get(f"{BASE_URL}/api/session/{session_id}", timeout=10)
        data = response.json()
        history_count = data.get('history_count', 0)
        print(f"历史消息数: {history_count}")
        results['history'] = history_count > 0
        print_result("会话历史", results['history'])
    except Exception as e:
        print(f"异常: {e}")
        results['history'] = False
        print_result("会话历史", False)

    all_passed = all(results.values())
    print_result("多轮对话", all_passed)
    return all_passed


if __name__ == "__main__":
    print("="*60)
    print(f"远程服务器测试: {BASE_URL}")
    print("="*60)

    results = {}

    # 1. 健康检查
    print_header("健康检查")
    try:
        resp = requests.get(f"{BASE_URL}/health", timeout=10)
        print(f"状态: {resp.json()}")
        results['health'] = resp.status_code == 200
        print_result("健康检查", results['health'])
    except Exception as e:
        print(f"异常: {e}")
        results['health'] = False
        print_result("健康检查", False)

    # 2. 流式技能测试
    skill_tests = [
        ('calculator', '帮我计算 123 + 456', '计算器技能', 60),
        ('time_query', '现在几点了', '时间查询技能', 60),
        ('ragflow_query', '什么是气象数据？', 'RAGFlow知识库', 30),
    ]

    for skill_name, query, desc, timeout in skill_tests:
        passed, _ = test_streaming_skill(skill_name, query, desc, timeout)
        results[desc] = passed

    # 3. 无技能 LLM 直接回答
    results['LLM直接回答'] = test_no_skill('你好', 'LLM直接回答')[0]

    # 4. 多轮对话
    results['多轮对话'] = test_multi_turn()

    # 汇总
    print_header("测试汇总")
    passed_count = sum(1 for v in results.values() if v)
    failed_count = sum(1 for v in results.values() if not v)

    for name, passed in results.items():
        print_result(name, passed)

    print(f"\n总计: {passed_count} 通过, {failed_count} 失败")
    print(f"总体结果: {'全部通过' if failed_count == 0 else '存在失败'}")
    sys.exit(0 if failed_count == 0 else 1)
