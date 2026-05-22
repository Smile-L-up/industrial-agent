"""
PromptSkill - 纯 Prompt 技能
无需 tool.py，无需 services，SKILL.md 内容作为 system prompt 注入到 LLM
"""

import logging
from typing import Dict, List, Any, Optional

from core.base_skill import BaseSkill

logger = logging.getLogger("industrial_agent.prompt_skill")


class PromptSkill(BaseSkill):
    """纯 Prompt 技能 — SKILL.md 内容作为 system prompt，LLM 直接回答"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._name = config.get("name", "prompt_skill")
        self._description = config.get("description", "Prompt 技能")
        self._keywords: List[str] = config.get("keywords", [])

        # SKILL.md 的正文内容（去除 front matter）
        self._raw_content = config.get("raw_content", "")

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def match_keywords(self) -> List[str]:
        return self._keywords

    def get_tools(self) -> List[Dict[str, Any]]:
        # Prompt 技能没有子工具
        return []

    async def execute(
        self,
        task: str,
        context: Dict[str, Any],
        messages: List[Dict[str, str]],
    ) -> str:
        """
        执行 Prompt 技能：将 SKILL.md 内容作为 prompt，调用 LLM 回答。
        """
        llm = context.get("_llm")
        if not llm:
            logger.warning("[PromptSkill] 未注入 LLM，返回原始提示")
            return f"技能 '{self._name}' 的提示内容：\n{self._raw_content}"

        # 构建 prompt：SKILL.md 内容 + 用户问题
        prompt = f"""你是一个智能助手，请严格按照以下技能说明来回答用户的问题。

## 技能说明
{self._raw_content}

## 用户问题
{task}

请根据上述技能说明，回答用户的问题。"""

        try:
            from llm.llm import Message
            response = await llm.chat([Message(role="user", content=prompt)])
            return response.content
        except Exception as e:
            logger.error("[PromptSkill] LLM 调用失败：%s", e, exc_info=True)
            return f"技能执行失败：{str(e)}"
