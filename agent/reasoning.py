"""
Reasoning - 推理模块
负责对执行结果进行分析和推理，更新代理状态
"""

from typing import Dict, Any
from .state import AgentState


class Reasoning:
    """推理模块类"""
    
    def __init__(self, llm=None):
        """
        初始化推理模块
        
        Args:
            llm: 语言模型实例
        """
        self.llm = llm
    
    async def reason(self, state: AgentState) -> AgentState:
        """
        进行推理分析
        
        Args:
            state: 当前代理状态
            
        Returns:
            更新后的状态
        """
        # 检查是否有待处理的任务
        pending_tasks = [t for t in state.tasks if t.status == "pending"]
        completed_tasks = [t for t in state.tasks if t.status == "completed"]
        failed_tasks = [t for t in state.tasks if t.status == "failed"]
        
        # 如果有失败的任务，尝试重试或报告错误
        if failed_tasks:
            return await self._handle_failures(state, failed_tasks)
        
        # 如果所有任务都完成了，标记为完成
        if not pending_tasks and completed_tasks:
            state.set_complete()
            return await self._summarize(state)
        
        # 如果有待处理的任务，继续处理
        if pending_tasks:
            return state
        
        # 没有任务但有输入，创建新任务
        if state.user_input and not state.tasks:
            return await self._create_initial_task(state)
        
        return state
    
    async def _handle_failures(self, state: AgentState, failed_tasks: list) -> AgentState:
        """处理失败的任务"""
        if self.llm is None:
            state.set_error(f"任务执行失败：{failed_tasks[0].error}")
            return state
        
        # 使用 LLM 分析失败原因并决定下一步
        prompt = self._build_failure_prompt(state, failed_tasks)
        response = await self.llm.generate(prompt)
        
        # 分析是否需要重试
        if "重试" in response or "retry" in response.lower():
            # 重置失败任务的状态
            for task in failed_tasks:
                task.status = "pending"
                task.error = None
            state.error = None
            state.add_message("assistant", "正在重试执行...")
        else:
            state.set_error(f"无法完成任务：{response}")
        
        return state
    
    def _build_failure_prompt(self, state: AgentState, failed_tasks: list) -> str:
        """构建失败分析提示词"""
        task_info = "\n".join([f"- {t.description}: {t.error}" for t in failed_tasks])
        return f"""任务执行失败，请分析原因并决定下一步：

失败的任务：
{task_info}

当前上下文：
{state.context}

请判断是否应该重试，或者向用户报告错误。"""
    
    async def _summarize(self, state: AgentState) -> AgentState:
        """总结执行结果"""
        if self.llm is None:
            results = [t.result for t in state.tasks if t.result]
            summary = "\n".join(results) if results else "任务已完成。"
            state.add_message("assistant", summary)
            state.final_result = summary
            return state
        
        # 使用 LLM 生成总结
        prompt = self._build_summary_prompt(state)
        response = await self.llm.generate(prompt)
        state.add_message("assistant", response)
        state.final_result = response
        
        return state
    
    def _build_summary_prompt(self, state: AgentState) -> str:
        """构建总结提示词"""
        task_results = []
        for task in state.tasks:
            if task.status == "completed":
                task_results.append(f"任务：{task.description}\n结果：{task.result}")
        
        return f"""请总结以下任务的执行结果：

{"\n\n".join(task_results)}

请提供一个简洁的总结回复给用户。"""
    
    async def _create_initial_task(self, state: AgentState) -> AgentState:
        """创建初始任务"""
        from .state import Task
        import uuid
        
        task = Task(
            id=str(uuid.uuid4()),
            description=state.user_input
        )
        state.add_task(task)
        state.current_task = task
        
        return state
    
    def update_context(self, state: AgentState, key: str, value: Any):
        """更新上下文信息"""
        state.context[key] = value