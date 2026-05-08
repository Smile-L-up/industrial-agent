"""
API Client - 智能体 API 客户端示例
演示如何调用 FastAPI 服务
"""

import asyncio
import httpx
import json


# ==================== 非流式调用 ====================

async def chat_non_stream(query: str) -> dict:
    """
    非流式聊天调用
    
    Args:
        query: 用户查询
        
    Returns:
        响应结果
    """
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            "http://localhost:18000/api/chat",
            json={"query": query, "stream": False}
        )
        response.raise_for_status()
        return response.json()


# ==================== 流式调用 ====================

async def chat_stream(query: str):
    """
    流式聊天调用
    
    Args:
        query: 用户查询
        
    Yields:
        流式数据块
    """
    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream(
            "POST",
            "http://localhost:18000/api/chat/stream",
            json={"query": query, "stream": True}
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data = line[6:]  # 移除 "data: " 前缀
                    if data.strip():
                        yield json.loads(data)


async def consume_stream(query: str):
    """
    消费流式响应（打印输出）
    
    Args:
        query: 用户查询
    """
    print(f"用户查询：{query}\n")
    print("处理进度：")
    print("-" * 50)
    
    async for chunk in chat_stream(query):
        if "content" in chunk:
            print(chunk["content"], end="", flush=True)
    
    print("\n" + "-" * 50)
    print("处理完成！")


# ==================== 主函数 ====================

async def main():
    """主函数 - 演示 API 调用"""
    print("=" * 50)
    print("智能体 API 客户端演示")
    print("=" * 50)
    
    # 检查服务状态
    print("\n[1] 检查服务状态...")
    try:
        async with httpx.AsyncClient() as client:
            health = await client.get("http://localhost:18000/health")
            if health.status_code == 200:
                print(f"服务状态：{health.json()}")
            else:
                print(f"服务状态检查失败：HTTP {health.status_code}")
    except httpx.ConnectError:
        print("错误：无法连接到 API 服务，请确保服务正在运行")
        print("启动命令：python api.py")
        return
    except Exception as e:
        print(f"服务状态检查异常：{e}")
        return
    
    # 获取技能列表
    print("\n[2] 获取可用技能...")
    try:
        async with httpx.AsyncClient() as client:
            skills = await client.get("http://localhost:18000/api/skills")
            for skill in skills.json()["skills"]:
                print(f"  - {skill['name']}: {skill['description']}")
    except Exception as e:
        print(f"获取技能失败：{e}")
    
    # 非流式调用示例
    print("\n[3] 非流式调用示例...")
    query = "北京天气怎么样？"
    print(f"查询：{query}")
    try:
        result = await chat_non_stream(query)
        print(f"最终结果：{result.get('final_result', 'N/A')}")
    except Exception as e:
        print(f"调用失败：{e}")
    
    # 流式调用示例
    print("\n[4] 流式调用示例...")
    query = "北京天气怎么样？"
    await consume_stream(query)


if __name__ == "__main__":
    asyncio.run(main())