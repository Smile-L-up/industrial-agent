"""
Industrial Agent - Main Entry Point
智能体系统主入口

简化版本：移除了复杂的记忆系统等组件
"""

import asyncio
import sys
import json
import logging

# 导入配置
from config import LLM_CONFIG

logger = logging.getLogger("industrial_agent.main")
from llm.llm import get_llm
from agent.graph import AgentGraph
from core.skill_loader import SkillLoader
from core.streaming import StreamingResponse, StreamHandler, EventType, ResponseFormatter


async def main(stream: bool = False, query: str = "你是谁？", interactive: bool = False):
    """主函数（简化版）"""
    logger.info("=" * 50)
    logger.info("智能体系统启动中...（简化版）")
    logger.info("=" * 50)
    
    # 初始化 LLM
    logger.info("[1/3] 初始化语言模型：%s - %s", LLM_CONFIG['provider'], LLM_CONFIG['model'])
    try:
        llm = get_llm(
            provider=LLM_CONFIG["provider"],
            model=LLM_CONFIG["model"],
            api_key=LLM_CONFIG.get("api_key"),
            base_url=LLM_CONFIG.get("base_url"),
            system_prompt=LLM_CONFIG.get("system_prompt")  # 使用统一的 system prompt
        )
        logger.info("      ✓ 语言模型初始化成功")
    except Exception as e:
        logger.error("      ✗ 语言模型初始化失败：%s", e, exc_info=True)
        llm = None
    
    # 加载技能
    logger.info("[2/3] 加载技能模块")
    skill_loader = SkillLoader()
    skills = skill_loader.load_all()
    logger.info("      ✓ 已加载 %d 个技能:", len(skills))
    for skill in skills:
        logger.info("        - %s: %s", skill.name, skill.description)
    
    # 初始化代理图（简化版，不需要记忆系统）
    logger.info("[3/3] 初始化代理图")
    agent_graph = AgentGraph(skills=skills, llm=llm)
    logger.info("      ✓ 代理图初始化成功")
    
    logger.info("=" * 50)
    logger.info("系统启动完成！（简化版）")
    logger.info("=" * 50)
    
    # 测试运行
    if llm:
        logger.info("[测试] 正在连接大模型进行测试...")
        try:
            # 简单测试 LLM 连接
            test_response = await llm.generate("你好，请用一句话介绍你自己。")
            logger.info("大模型响应：%s", test_response)
            logger.info("✓ 大模型连接测试成功！")
        except Exception as e:
            logger.error("✗ 大模型连接测试失败：%s", e, exc_info=True)
    
    # 交互式模式
    if interactive:
        logger.info("=" * 50)
        logger.info("进入交互式多轮对话模式（输入 'quit' 或 'exit' 退出，'clear' 清空历史）")
        logger.info("=" * 50)
        await run_interactive_mode(agent_graph, stream)
        return {"status": "exited"}
    
    # 运行查询
    print("\n" + "-" * 50)
    print(f"运行查询：'{query}'")
    print("-" * 50)
    
    if stream:
        # 流式模式
        print("\n[流式模式] 正在执行...\n")
        result = await run_stream_mode(agent_graph, query)
    else:
        # 普通模式
        result = await agent_graph.run(query)
        print("\n执行结果:")
        print(result)
    
    return result


async def run_interactive_mode(agent_graph: AgentGraph, stream: bool = False):
    """
    运行交互式多轮对话模式
    
    Args:
        agent_graph: 代理图
        stream: 是否使用流式输出
    """
    while True:
        try:
            # 获取用户输入
            user_input = input("\n👤 你：").strip()
            
            if not user_input:
                continue
            
            # 检查退出命令
            if user_input.lower() in ['quit', 'exit']:
                print("\n👋 再见！")
                break
            
            # 检查清空历史命令
            if user_input.lower() == 'clear':
                agent_graph.clear_history()
                print("🗑️ 对话历史已清空")
                continue
            
            # 处理用户输入
            if stream:
                # 流式模式
                response = await run_stream_mode(agent_graph, user_input)
                print("\n🤖 助手：", end="")
                await consume_stream(response)
            else:
                # 普通模式
                result = await agent_graph.run(user_input)
                print(f"\n🤖 助手：{result.get('final_result', '')}")
                
        except KeyboardInterrupt:
            print("\n\n👋 再见！")
            break
        except Exception as e:
            print(f"\n❌ 发生错误：{e}")


async def run_stream_mode(agent_graph: AgentGraph, user_input: str) -> StreamingResponse:
    """
    运行流式模式
    
    Args:
        agent_graph: 代理图
        user_input: 用户输入
        
    Returns:
        流式响应对象
    """
    from core.streaming import StreamingResponse, ResponseFormatter
    
    response = StreamingResponse()
    formatter = ResponseFormatter()
    
    async def process_stream():
        """处理流式输出"""
        try:
            async for chunk in agent_graph.run_stream(user_input):
                await response.write(chunk)
            await response.end()
        except Exception as e:
            await response.error(str(e))
    
    # 启动处理任务
    asyncio.create_task(process_stream())
    
    return response


async def consume_stream(response: StreamingResponse):
    """
    消费流式响应（用于打印输出）
    
    Args:
        response: 流式响应对象
    """
    async for chunk in response:
        if isinstance(chunk, dict) and "content" in chunk:
            content = chunk["content"]
            # 逐字打印内容
            for char in content:
                print(char, end="", flush=True)
                await asyncio.sleep(0.01)  # 模拟逐字输出效果
    print()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="智能体系统")
    parser.add_argument("--stream", action="store_true", help="启用流式输出")
    parser.add_argument("--query", type=str, default="你是谁？", help="查询内容")
    parser.add_argument("--interactive", "-i", action="store_true", help="启用交互式多轮对话模式")
    args = parser.parse_args()
    
    async def run_with_args():
        """带参数运行"""
        result = await main(stream=args.stream, query=args.query, interactive=args.interactive)
        
        # 如果是流式模式，消费流
        if args.stream and isinstance(result, StreamingResponse):
            print("\n[流式输出]\n")
            await consume_stream(result)
        
        return result
    
    asyncio.run(run_with_args())
