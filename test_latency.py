"""延迟对比测试：直接调 Qwen API vs 走项目 API"""

import asyncio
import time
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

API_KEY = "sk-da3613b86fe84367926bcda009297dac"
BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
MODEL = "qwen3.5-plus"
PROJECT_URL = "http://127.0.0.1:18000/api/chat/stream"

PROMPT = "你好，你是谁"


async def test_direct_qwen():
    """直接调 Qwen API，测量首 token 延迟"""
    print("=" * 50)
    print("测试1: 直接调 Qwen API (流式)")
    print(f"模型: {MODEL}")
    print(f"提示: {PROMPT}")
    print("=" * 50)

    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=API_KEY, base_url=BASE_URL)

    t_start = time.time()
    first_token_time = None
    full_content = ""
    token_count = 0

    stream = await client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": PROMPT}],
        stream=True,
        max_tokens=4096,
        temperature=0.7,
        extra_body={"enable_thinking": False},
    )

    async for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if delta.content:
            if first_token_time is None:
                first_token_time = time.time()
                ttft = first_token_time - t_start
                print(f"  首 token 延迟: {ttft:.3f} 秒")
            full_content += delta.content
            token_count += 1

    total = time.time() - t_start
    print(f"  总耗时: {total:.3f} 秒")
    print(f"  token 数: {token_count}")
    print(f"  回复: {full_content[:200]}")
    await client.close()
    return first_token_time - t_start if first_token_time else None


async def test_project_api():
    """走项目 API，测量首 token 延迟"""
    print("\n" + "=" * 50)
    print("测试2: 走项目 API (流式)")
    print(f"端点: {PROJECT_URL}")
    print(f"提示: {PROMPT}")
    print("=" * 50)

    import aiohttp

    body = {
        "messages": [{"role": "user", "content": PROMPT}],
        "enable_thinking": False,
    }

    t_start = time.time()
    first_token_time = None
    full_content = ""
    token_count = 0

    async with aiohttp.ClientSession() as session:
        async with session.post(PROJECT_URL, json=body) as resp:
            print(f"  HTTP 状态: {resp.status}")
            async for raw_line in resp.content:
                line_str = raw_line.decode("utf-8", errors="ignore").strip()
                if not line_str.startswith("data: "):
                    continue
                data_str = line_str[6:]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    data = json.loads(data_str)
                    # 项目 API 格式: {"type": "token", "content": "...", "session_id": "..."}
                    if data.get("type") == "token" and data.get("content"):
                        if first_token_time is None:
                            first_token_time = time.time()
                            ttft = first_token_time - t_start
                            print(f"  首 token 延迟: {ttft:.3f} 秒")
                        full_content += data["content"]
                        token_count += 1
                    # 也兼容 reasoning_content
                    elif data.get("type") == "reasoning_content":
                        pass  # 忽略思考内容
                except Exception:
                    pass

    total = time.time() - t_start
    if first_token_time is None:
        print(f"  未收到任何 token！")
        print(f"  总耗时: {total:.3f} 秒")
        return None
    print(f"  总耗时: {total:.3f} 秒")
    print(f"  token 数: {token_count}")
    print(f"  回复: {full_content[:200]}")
    return first_token_time - t_start


async def main():
    print("延迟对比测试")
    print(f"测试内容: '{PROMPT}'")
    print(f"enable_thinking: False\n")

    ttft_direct = await test_direct_qwen()
    ttft_project = await test_project_api()

    print("\n" + "=" * 50)
    print("对比结果")
    print("=" * 50)
    if ttft_direct is not None:
        print(f"  直接 Qwen API  首 token: {ttft_direct:.3f} 秒")
    else:
        print(f"  直接 Qwen API  首 token: 失败")
    if ttft_project is not None:
        print(f"  项目 API       首 token: {ttft_project:.3f} 秒")
    else:
        print(f"  项目 API       首 token: 失败")
    if ttft_direct is not None and ttft_project is not None:
        diff = ttft_project - ttft_direct
        print(f"  差值 (项目 - 直接): {diff:+.3f} 秒")


if __name__ == "__main__":
    asyncio.run(main())
