"""
Planner - 规划器
负责将用户请求转换为执行计划
"""

from typing import Optional
from .state import AgentState, Task
import uuid


class Planner:
    """规划器类"""
    
    def __init__(self, llm=None):
        """
        初始化规划器
        
        Args:
            llm: 语言模型实例
        """
        self.llm = llm
        self.prompt_template = self._load_prompt()
    
    def _load_prompt(self) -> str:
        """加载规划提示词"""
        try:
            with open("prompts/planner.txt", "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return """你是一个任务规划助手。
请分析用户的请求，并制定一个清晰的执行计划。

用户请求：{user_input}

请输出：
1. 任务目标
2. 需要执行的步骤
3. 可能需要的工具或技能"""
    
    async def plan(self, state: AgentState) -> AgentState:
        """
        生成执行计划
        
        Args:
            state: 当前代理状态
            
        Returns:
            更新后的状态
        """
        if self.llm is None:
            # 如果没有 LLM，创建一个简单的计划
            state.plan = f"处理用户请求：{state.user_input}"
            state.add_task(Task(
                id=str(uuid.uuid4()),
                description=state.user_input
            ))
            return state
        
        # 使用 LLM 生成计划
        prompt = self.prompt_template.format(user_input=state.user_input)
        response = await self.llm.generate(prompt)
        
        state.plan = response
        state.add_message("assistant", f"已制定计划：{response}")
        
        # 从计划中提取任务
        tasks = self._parse_tasks(response, state.user_input)
        for task_desc in tasks:
            state.add_task(Task(
                id=str(uuid.uuid4()),
                description=task_desc
            ))
        
        return state
    
    def _parse_tasks(self, plan: str, user_input: str) -> list:
        """从计划中解析出任务列表"""
        # 简单实现，可以根据实际计划格式进行解析
        return [user_input]