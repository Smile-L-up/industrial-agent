"""测试纯 Prompt 技能"""
import requests
import json
import sys
import time
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE_URL = "http://localhost:18000"


def test_prompt_skill():
    """测试翻译助手 Prompt 技能"""
    print("="*60)
    print("测试纯 Prompt 技能 - 翻译助手")
    print("="*60)

    # 1. 检查技能是否加载
    print("\n--- 检查技能列表 ---")
    try:
        resp = requests.get(f"{BASE_URL}/api/skills", timeout=10)
        skills = resp.json().get('skills', [])
        skill_names = [s['name'] for s in skills]
        print(f"已加载技能: {skill_names}")

        if 'translator' not in skill_names:
            print("[FAIL] translator 技能未加载")
            return False
        print("[PASS] translator 技能已加载")
    except Exception as e:
        print(f"[FAIL] 获取技能列表失败: {e}")
        return False

    # 2. 测试流式调用
    print("\n--- 测试流式调用 ---")
    url = f"{BASE_URL}/api/chat/stream"
    data = {
        "messages": [{"role": "user", "content": "把这个翻译成英文：今天天气真好，适合出去散步"}],
        "selected_skills": ["translator"]
    }

    try:
        response = requests.post(url, json=data, stream=True, timeout=60)
        print(f"状态码: {response.status_code}")

        full_response = ""
        has_skill_invoked = False
        has_tool_call = False
        has_token = False
        has_complete = False

        for line in response.iter_lines():
            if line:
                decoded = line.decode('utf-8')
                if decoded.startswith('data: '):
                    try:
                        chunk_data = json.loads(decoded[6:])
                        chunk_type = chunk_data.get('type', 'unknown')

                        if chunk_type == 'skill_invoked':
                            has_skill_invoked = True
                            print(f"  [skill_invoked] {chunk_data.get('content')}")
                        elif chunk_type == 'tool_call':
                            has_tool_call = True
                            print(f"  [tool_call] {chunk_data.get('name')} (service_type={chunk_data.get('service_type')})")
                        elif chunk_type == 'token':
                            has_token = True
                            full_response += chunk_data.get('content', '')
                        elif chunk_type == 'complete':
                            has_complete = True
                            print(f"  [complete] 响应完成")
                        elif chunk_type == 'error':
                            print(f"  [error] {chunk_data.get('content')}")

                    except json.JSONDecodeError:
                        pass

        print(f"\n--- 统计 ---")
        print(f"skill_invoked: {has_skill_invoked}")
        print(f"tool_call: {has_tool_call}")
        print(f"token: {has_token}")
        print(f"complete: {has_complete}")
        print(f"响应: {full_response[:200]}...")

        passed = has_skill_invoked and has_token and has_complete
        print(f"\n结果: {'[PASS]' if passed else '[FAIL]'}")
        return passed

    except Exception as e:
        print(f"[FAIL] 异常: {e}")
        return False


if __name__ == "__main__":
    result = test_prompt_skill()
    sys.exit(0 if result else 1)
