"""
Router - 路由器
负责根据当前任务选择合适的技能或工具

重构说明：
  - 全部走 LLM 路由，不再使用关键词匹配
  - 使用 SkillMetadata 轻量元数据进行路由决策
  - 技能按需加载，路由阶段不加载 tool.py
"""

from typing import Optional, List
from .state import AgentState, Task
from core.skill_loader import SkillMetadata
from core.logger import get_logger

logger = get_logger("agent.router")


class Router:
    """路由器类 — LLM 路由"""

    def __init__(self, llm=None, metadata_list: List[SkillMetadata] = None):
        """
        初始化路由器

        Args:
            llm: 语言模型实例
            metadata_list: 技能元数据列表（轻量，不含 tool.py）
        """
        self.llm = llm
        self.metadata_list = metadata_list or []
        self.prompt_template = self._load_prompt()

    def _load_prompt(self) -> str:
        """加载路由提示词"""
        try:
            with open("prompts/router.txt", "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return """你是一个任务路由助手。
根据用户任务，从可用技能中选择最合适的技能。

可用技能：
{skills}

用户任务：{task}

请只输出技能名称。如果没有合适的技能，输出 None。"""

    def update_metadata(self, metadata_list: List[SkillMetadata]):
        """更新技能元数据列表"""
        self.metadata_list = metadata_list

    async def route(self, state: AgentState) -> AgentState:
        """
        路由到合适的技能（LLM 路由）

        Args:
            state: 当前代理状态

        Returns:
            更新后的状态
        """
        if not state.tasks:
            state.set_error("没有待处理的任务")
            return state

        # 获取第一个待处理任务
        pending_tasks = [t for t in state.tasks if t.status == "pending"]
        if not pending_tasks:
            state.is_complete = True
            return state

        current_task = pending_tasks[0]
        state.current_task = current_task
        current_task.status = "in_progress"

        # ── 用户指定技能：跳过 LLM 路由 ──
        user_selected_skills = state.context.get("selected_skills")
        if user_selected_skills:
            selected = self._match_user_skills(user_selected_skills)
            if selected:
                logger.info("使用用户指定的技能：%s（候选：%s）", selected, user_selected_skills)
                state.context["selected_skill"] = selected
                state.current_tool = selected
                state.add_message("assistant", f"使用用户指定的技能：{selected}")
                return state
            else:
                logger.warning("用户指定的技能均无效：%s，回退到 LLM 路由", user_selected_skills)

        # ── LLM 路由 ──
        selected_skill = await self._route_with_llm(current_task.description)

        state.context["selected_skill"] = selected_skill
        state.current_tool = selected_skill
        if selected_skill:
            state.add_message("assistant", f"选择技能：{selected_skill}")
        else:
            logger.info("无匹配技能，将由 graph 直接流式回答")

        return state

    # ── 用户指定技能匹配 ──────────────────────────────

    def _match_user_skills(self, user_selected_skills: List[str]) -> Optional[str]:
        """从用户指定的技能列表中选择第一个有效的技能"""
        available_names = {meta.name for meta in self.metadata_list}
        for skill_name in user_selected_skills:
            if skill_name in available_names:
                return skill_name
        return None

    # ── LLM 路由 ──────────────────────────────────────

    async def _route_with_llm(self, task_description: str) -> Optional[str]:
        """使用 LLM 选择合适的技能"""
        if not self.metadata_list:
            return None

        if not self.llm:
            logger.warning("LLM 未初始化，无法进行路由")
            return None

        # 构建技能描述列表
        skills_info = "\n".join(
            [f"- {m.name}: {m.description}" for m in self.metadata_list]
        )

        prompt = self.prompt_template.format(
            skills=skills_info,
            task=task_description,
        )

        try:
            from llm.llm import Message
            response = await self.llm.chat([Message(role="user", content=prompt)])
            selected = self._parse_skill_selection(response.content.strip())
            if selected:
                logger.info("LLM 路由结果：%s", selected)
            else:
                logger.info("LLM 路由结果：None（无匹配技能）")
            return selected
        except Exception as e:
            logger.error("LLM 路由失败：%s", e, exc_info=True)
            return None

    def _parse_skill_selection(self, response: str) -> Optional[str]:
        """解析 LLM 路由结果"""
        response = response.strip().strip('"').strip("'")

        # 检查是否匹配已知技能名
        for meta in self.metadata_list:
            if meta.name == response:
                return meta.name

        # 尝试从响应中提取技能名
        response_lower = response.lower()
        for meta in self.metadata_list:
            if meta.name.lower() in response_lower:
                return meta.name

        # LLM 返回 None / none / 无
        if response_lower in ("none", "null", "无", "无匹配", ""):
            return None

        return None
