"""
Router - 路由器
负责根据当前任务选择合适的技能或工具

重构说明：
  - 使用 routing_config 中的关键词配置，消除硬编码
  - 使用 core.logger 替代 print
  - 支持 BaseSkill 的 match_keywords() 接口
"""

from typing import Optional, Any, List
from .state import AgentState, Task
from .routing_config import SKILL_KEYWORDS, get_skill_keywords
from core.logger import get_logger

logger = get_logger("agent.router")


class Router:
    """路由器类（简化版）"""

    def __init__(self, llm=None, skills=None):
        """
        初始化路由器（简化版）

        Args:
            llm: 语言模型实例
            skills: 可用技能列表
        """
        self.llm = llm
        self.skills = skills or []
        self.prompt_template = self._load_prompt()

    def _load_prompt(self) -> str:
        """加载路由提示词"""
        try:
            with open("prompts/router.txt", "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return """你是一个任务路由助手。
请根据当前任务，选择合适的技能或工具来处理。

可用技能：
{skills}

当前任务：{task}

请输出应该使用的技能名称，如果没有合适的技能，输出"general"。"""

    async def route(self, state: AgentState) -> AgentState:
        """
        路由到合适的技能（简化版）

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

        # 更新任务状态
        current_task.status = "in_progress"

        # 选择合适的技能（简化版：优先使用关键词匹配）
        selected_skill = self._simple_match(current_task.description)

        # 将选中的技能信息存入上下文和 current_tool
        state.context["selected_skill"] = selected_skill
        state.current_tool = selected_skill
        if selected_skill:
            state.add_message("assistant", f"选择技能：{selected_skill or '无'}")

        return state

    # ── 关键词匹配（使用 routing_config） ──────────────

    def _get_keywords_for_skill(self, skill_name: str) -> List[str]:
        """
        获取技能的关键词列表。优先使用 BaseSkill.match_keywords()，
        回退到 routing_config.SKILL_KEYWORDS。
        """
        # 1. 优先使用技能自身的 match_keywords()
        for skill in self.skills:
            if skill.name == skill_name and hasattr(skill, "match_keywords"):
                keywords = skill.match_keywords()
                if keywords:
                    return keywords

        # 2. 回退到 routing_config
        return get_skill_keywords(skill_name)

    # 问候语列表 — 这些输入应直接走通用 LLM，不触发技能路由
    GREETING_KEYWORDS = ["你好", "hello", "hi", "嗨", "您好", "hey", "早上好", "下午好", "晚上好"]

    def _simple_match(self, task_description: str) -> Optional[str]:
        """
        简单匹配技能 — 基于关键词匹配（主要方式）。
        关键词来源：routing_config.SKILL_KEYWORDS + BaseSkill.match_keywords()
        """
        task_lower = task_description.lower().strip()

        # ── 0. 问候语检测 — 直接跳过路由，走通用 LLM ──
        if task_lower in self.GREETING_KEYWORDS or len(task_lower) <= 4 and any(
            g in task_lower for g in self.GREETING_KEYWORDS
        ):
            logger.debug(f"检测到问候语，跳过技能路由：{task_description}")
            return None

        # ── 1. 直接匹配技能名称 ──
        for skill in self.skills:
            if skill.name.lower() in task_lower:
                return skill.name

        # ── 2. 基于配置化关键词匹配 ──

        # 收集所有技能的关键词（合并 routing_config 和 BaseSkill）
        skill_keyword_map: dict[str, List[str]] = {}
        all_skill_names: set = set(SKILL_KEYWORDS.keys())
        for skill in self.skills:
            all_skill_names.add(skill.name)

        for name in all_skill_names:
            skill_keyword_map[name] = self._get_keywords_for_skill(name)

        # 检查每个技能的关键词命中情况
        matched_scores: dict[str, int] = {}
        for name, keywords in skill_keyword_map.items():
            if not keywords:
                continue
            score = sum(1 for kw in keywords if kw in task_lower)
            if score > 0:
                matched_scores[name] = score

        # ── 3. 特殊优先级规则 ──

        # 区域/地图相关技能优先于单城市天气
        map_skills = [
            name for name in matched_scores
            if "map" in name.lower() or "地图" in name.lower()
        ]
        weather_skills = [
            name for name in matched_scores
            if "weather" in name.lower() and "map" not in name.lower()
        ]
        time_skills = [
            name for name in matched_scores
            if "time" in name.lower() or "时间" in name.lower()
        ]

        # 如果同时命中地图和天气关键词，优先返回地图技能
        if map_skills:
            return max(map_skills, key=lambda n: matched_scores[n])

        if weather_skills:
            return max(weather_skills, key=lambda n: matched_scores[n])

        if time_skills:
            return max(time_skills, key=lambda n: matched_scores[n])

        # ── 4. 通用回退：返回得分最高的技能 ──
        if matched_scores:
            return max(matched_scores, key=lambda n: matched_scores[n])

        return None

    # ── LLM 备用方案 ────────────────────────────────────

    async def _select_skill_with_llm(self, task_description: str) -> Optional[str]:
        """使用 LLM （备用方案）"""
        if not self.skills:
            return None

        skills_info = "\n".join([f"- {s.name}: {s.description}" for s in self.skills])
        prompt = self.prompt_template.format(
            skills=skills_info,
            task=task_description
        )

        try:
            response = await self.llm.generate(prompt)
            return self._parse_skill_selection(response)
        except Exception as e:
            logger.error(f"LLM 技能选择失败：{e}")
            return None

    def _parse_skill_selection(self, response: str) -> Optional[str]:
        """解析技能选择结果（简化版）"""
        response = response.strip()

        for skill in self.skills:
            if skill.name in response:
                return skill.name

        return None

    def add_skill(self, skill: Any):
        """添加技能"""
        self.skills.append(skill)

    def remove_skill(self, skill_name: str):
        """移除技能"""
        self.skills = [s for s in self.skills if s.name != skill_name]