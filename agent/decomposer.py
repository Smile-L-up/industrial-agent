"""
Decomposer - 任务分解器
负责将复杂任务分解为可执行的子任务
"""

from typing import List
from .state import AgentState, Task
import uuid


class Decomposer:
    """任务分解器类"""
    
    def __init__(self, llm=None):
        """
        初始化分解器
        
        Args:
            llm: 语言模型实例
        """
        self.llm = llm
    
    async def decompose(self, state: AgentState) -> AgentState:
        """
        分解任务为子任务
        
        Args:
            state: 当前代理状态
            
        Returns:
            更新后的状态
        """
        if not state.tasks:
            return state
        
        # 获取第一个待处理任务
        pending_tasks = [t for t in state.tasks if t.status == "pending"]
        if not pending_tasks:
            return state
        
        current_task = pending_tasks[0]
        
        # 判断是否需要分解
        if self._needs_decomposition(current_task.description):
            sub_tasks = await self._generate_sub_tasks(current_task.description)
            
            # 将子任务插入到当前任务之前
            current_index = state.tasks.index(current_task)
            for i, sub_task_desc in enumerate(reversed(sub_tasks)):
                state.tasks.insert(current_index, Task(
                    id=str(uuid.uuid4()),
                    description=sub_task_desc,
                    status="pending"
                ))
            
            # 标记原任务为需要分解后的结果
            current_task.description = f"整合：{current_task.description}"
            
            # 更新 steps 属性
            state.steps = sub_tasks
        else:
            # 如果不需要分解，也设置 steps 为当前任务
            state.steps = [current_task.description]
        
        return state
    
    def _needs_decomposition(self, task_description: str) -> bool:
        """判断任务是否需要分解"""
        # 简单规则：如果任务描述包含多个动作或条件，则需要分解
        keywords = ["并且", "然后", "如果", "同时", "先", "再", "和"]
        return any(kw in task_description for kw in keywords)
    
    async def _generate_sub_tasks(self, task_description: str) -> List[str]:
        """生成子任务列表"""
        if self.llm is None:
            # 简单分解
            return [f"步骤 1: {task_description}"]
        
        prompt = f"""请将以下任务分解为可执行的子任务：
任务：{task_description}

请输出子任务列表，每个子任务应该是独立可执行的。"""
        
        response = await self.llm.generate(prompt)
        
        # 解析响应，提取子任务
        sub_tasks = self._parse_sub_tasks(response)
        return sub_tasks
    
    def _parse_sub_tasks(self, response: str) -> List[str]:
        """从响应中解析子任务"""
        sub_tasks = []
        for line in response.split("\n"):
            line = line.strip()
            if line and not line.startswith("#"):
                # 移除序号
                if line[0].isdigit() or line.startswith("-"):
                    line = line.split(".", 1)[-1].split("：", 1)[-1].strip()
                sub_tasks.append(line)
        return sub_tasks