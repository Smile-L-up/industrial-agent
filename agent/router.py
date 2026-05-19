"""
Router - 路由器
负责根据当前任务选择合适的技能或工具

重构说明：
  - 全部走 LLM 路由，不再使用关键词匹配
  - 使用 SkillMetadata 轻量元数据进行路由决策
  - 技能按需加载，路由阶段不加载 tool.py
"""

import asyncio
from typing import Optional, List, Dict, Any, AsyncGenerator
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

如果有匹配的技能，只输出技能名称。
如果没有匹配的技能，直接输出回答内容。"""

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

    # ── 流式合并路由 ──────────────────────────────────

    async def route_stream(
        self,
        task_description: str,
        messages: list,
        enable_thinking: Optional[bool] = None,
        cancel_event: Optional[asyncio.Event] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        流式合并路由：一次 LLM 调用同时完成路由和回答。

        - 如果匹配到技能 → yield {"type": "skill_match", "skill": name}
        - 如果无匹配 → yield {"type": "token", "content": ...} 逐 token 输出回答

        Args:
            task_description: 用户任务描述
            messages: 完整对话历史（用于直接回答时构建上下文）
            enable_thinking: 是否启用思考模式
            cancel_event: 取消信号事件
        """
        if not self.llm:
            yield {"type": "token", "content": "抱歉，我暂时无法处理这个问题。"}
            return

        # ── 无技能 → 直接流式回答 ──
        if not self.metadata_list:
            async for chunk in self._stream_answer(messages, enable_thinking, cancel_event=cancel_event):
                yield chunk
            return

        # ── 有技能 → 流式路由 + 按需回答 ──
        skills_info = "\n".join(
            [f"- {m.name}: {m.description}" for m in self.metadata_list]
        )
        prompt = self.prompt_template.format(
            skills=skills_info,
            task=task_description,
        )

        from llm.llm import Message

        # 构建路由消息：完整对话历史 + 路由指令（含图片）
        routing_content = [{"type": "text", "text": prompt}]
        for msg in messages:
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "image_url":
                            routing_content.append(item)

        llm_messages = [
            Message(role=msg.get("role", "user"), content=msg.get("content", ""))
            for msg in messages
        ]
        llm_messages.append(Message(role="user", content=routing_content))

        buffer = ""
        matched_skill = None

        try:
            async for chunk in self.llm.chat_stream(
                llm_messages, cancel_event=cancel_event, enable_thinking=enable_thinking
            ):
                # 检查取消信号
                if cancel_event and cancel_event.is_set():
                    logger.info("路由阶段检测到取消信号")
                    return

                if chunk.get("type") == "reasoning_content":
                    continue

                if chunk.get("type") != "content":
                    continue

                token = chunk["content"]
                buffer += token

                # 已确认匹配到技能 → 不再输出
                if matched_skill is not None:
                    continue

                # 尝试匹配技能名（精确或包含）
                skill = self._try_match_skill(buffer.strip())
                if skill:
                    matched_skill = skill
                    logger.info("流式路由匹配到技能：%s", skill)
                    yield {"type": "skill_match", "skill": skill}
                    continue

                # 检查是否已确定不是技能名（出现空格/标点且无匹配）
                # 技能名都是单词/下划线，一旦出现其他字符就确认是回答
                if self._is_confirmed_answer(buffer):
                    # 缓冲的内容是回答，输出给客户端
                    for ch in buffer:
                        yield {"type": "token", "content": ch}
                    buffer = ""  # 已全部输出，清空

            # 流结束：如果既没匹配技能也没确认为回答
            if matched_skill is None:
                remaining = buffer
                if remaining:
                    # 最终检查
                    skill = self._try_match_skill(remaining.strip())
                    if skill:
                        logger.info("流式路由匹配到技能（末尾）：%s", skill)
                        yield {"type": "skill_match", "skill": skill}
                    else:
                        for ch in remaining:
                            yield {"type": "token", "content": ch}

        except asyncio.CancelledError:
            logger.info("路由阶段被取消")
            return
        except Exception as e:
            logger.error("流式路由失败：%s", e, exc_info=True)
            yield {"type": "token", "content": "抱歉，处理请求时出现问题。"}

    @staticmethod
    def _has_image_content(messages: list) -> bool:
        """检查消息列表中是否包含图片内容"""
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "image_url":
                        return True
        return False

    def _try_match_skill(self, text: str) -> Optional[str]:
        """尝试将文本匹配到已知技能名"""
        text = text.strip().strip('"').strip("'")
        for meta in self.metadata_list:
            if meta.name == text or meta.name.lower() == text.lower():
                return meta.name
        return None

    def _is_confirmed_answer(self, buffer: str) -> bool:
        """
        判断缓冲内容是否已确认为「回答」（而非技能名）。
        技能名只包含字母、数字、下划线、中文，不含空格和标点。
        一旦 buffer 中出现空格或标点，且不匹配任何技能名，就是回答。
        """
        import re
        stripped = buffer.strip()
        if not stripped:
            return False
        # 包含空格或常见标点 → 不可能是技能名
        if re.search(r"[\s,.!?;:，。！？；：]", stripped):
            return True
        # 长度超过最长技能名 → 不可能是技能名
        max_name_len = max((len(m.name) for m in self.metadata_list), default=0)
        if len(stripped) > max_name_len + 5:
            return True
        return False

    async def _stream_answer(
        self,
        messages: list,
        enable_thinking: Optional[bool] = None,
        cancel_event: Optional[asyncio.Event] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """用 LLM 流式直接回答（无技能场景）"""
        from llm.llm import Message

        llm_messages = [
            Message(role=msg.get("role", "user"), content=msg.get("content", ""))
            for msg in messages
        ]

        async for chunk in self.llm.chat_stream(llm_messages, cancel_event=cancel_event, enable_thinking=enable_thinking):
            # 检查取消信号
            if cancel_event and cancel_event.is_set():
                logger.info("流式回答阶段检测到取消信号")
                return
            if isinstance(chunk, dict):
                chunk_type = chunk.get("type")
                if chunk_type == "reasoning_content":
                    yield {"type": "reasoning_content", "content": chunk["content"]}
                elif chunk_type == "content":
                    yield {"type": "token", "content": chunk["content"]}
            else:
                yield {"type": "token", "content": chunk}
