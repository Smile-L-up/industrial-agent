"""
Agent Graph - 代理图状态机
定义代理的工作流程和状态转换

简化说明：
  - 移除 Router，不做自动路由
  - 用户指定技能 → 按需加载并执行
  - 用户未指定技能 → LLM 直接回答
"""

import asyncio
import logging
import uuid
from typing import Dict, Any, Optional, AsyncGenerator, List
from .state import AgentState, Task
from core.image_store import ImageStore
from core.skill_loader import SkillLoader
from core.streaming import StreamHandler, EventType

logger = logging.getLogger("industrial_agent.graph")


class AgentGraph:
    """代理图，管理工作流状态转换"""

    def __init__(
        self,
        memory=None,
        skill_loader: SkillLoader = None,
        llm=None,
        max_history: int = 10,
        session_id: Optional[str] = None,
        db=None
    ):
        """
        初始化代理图

        Args:
            memory: 记忆系统（暂未使用）
            skill_loader: 技能加载器（用于按需加载技能）
            llm: 语言模型实例
            max_history: 最大对话历史条数
            session_id: 会话 ID（用于数据库存储）
            db: 数据库管理器实例
        """
        self.memory = memory
        self.skill_loader = skill_loader
        self.llm = llm
        self.max_history = max_history
        self.session_id = session_id
        self.db = db
        self.conversation_history = []

        # 如果提供了数据库，从数据库加载历史
        if db and session_id:
            self.conversation_history = self._load_history_from_db()

        from .executor import Executor

        self.executor = Executor(llm, self.skill_loader)

    # ==================== 历史管理 ====================

    def _load_history_from_db(self) -> List[Dict[str, Any]]:
        """从数据库加载对话历史"""
        if not self.db or not self.session_id:
            return []

        messages = self.db.get_messages(self.session_id, limit=self.max_history)
        history = []
        for m in messages:
            content = self._decode_history_content(m["content"])
            history.append({
                "role": m["role"],
                "content": ImageStore.refs_to_summary_content(content)
            })
        return history

    def _decode_history_content(self, content: Any) -> Any:
        """Decode JSON history content when possible."""
        if not isinstance(content, str):
            return content
        stripped = content.strip()
        if not stripped or stripped[0] not in "[{":
            return content
        try:
            import json
            return json.loads(stripped)
        except Exception:
            return content

    def _save_message_to_db(self, role: str, content: str):
        """保存消息到数据库"""
        if self.db and self.session_id:
            try:
                self.db.add_message(self.session_id, role, content)
            except Exception as e:
                logger.error("保存消息失败：%s (类型：%s)", e, type(e).__name__)

    def _save_user_messages_to_db(self, storage_messages, original_messages):
        """将用户消息保存到数据库"""
        messages_to_store = storage_messages or original_messages
        for msg in messages_to_store:
            self._save_message_to_db(msg.get("role", "user"), msg.get("content", ""))

    def _save_assistant_response_to_db(self, state: AgentState):
        """将助手响应保存到数据库并更新对话历史"""
        if state.messages:
            last_message = state.messages[-1]
            if last_message["role"] == "assistant":
                self.conversation_history.append(last_message)
                self._save_message_to_db("assistant", last_message.get("content", ""))
                if len(self.conversation_history) > self.max_history:
                    self.conversation_history = self.conversation_history[-self.max_history:]

    def clear_history(self):
        """清空对话历史"""
        self.conversation_history = []
        if self.db and self.session_id:
            self.db.clear_history(self.session_id)

    def get_history(self) -> list:
        """获取对话历史"""
        return self.conversation_history.copy()

    # ==================== 消息解析 ====================

    def _extract_user_input(self, messages: List[Dict[str, Any]]) -> str:
        """从 OpenAI 标准 messages 中提取用户输入文本"""
        user_input = ""
        for msg in messages:
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, list):
                    for item in content:
                        if item.get("type") == "text":
                            user_input += item.get("text", "") + " "
                elif isinstance(content, str):
                    user_input = content
                break
        return user_input

    def _append_messages_to_history(self, messages: List[Dict[str, Any]]):
        """将消息追加到对话历史，并裁剪到最大长度"""
        for msg in messages:
            self.conversation_history.append(msg)
        if len(self.conversation_history) > self.max_history:
            self.conversation_history = self.conversation_history[-self.max_history:]

    # ==================== 多模态工具 ====================

    def _build_multimodal_content(self, text: str, images: List[Dict[str, Any]]) -> list:
        """构建多模态消息内容（文本 + 多张图片）"""
        content = []
        if text:
            content.append({"type": "text", "text": text})
        for img in images:
            content.append(img)
        return content

    # ==================== 核心运行流程 ====================

    async def _prepare_state(
        self,
        messages: List[Dict[str, Any]],
        selected_skills: Optional[List[str]] = None
    ) -> tuple:
        """
        准备 AgentState：解析消息、追加历史、构建状态
        """
        handler = StreamHandler()

        logger.debug("处理 messages=%s", messages)

        # 追加消息到对话历史
        self._append_messages_to_history(messages)

        # 提取用户输入文本
        user_input = self._extract_user_input(messages)

        state = AgentState()
        state.user_input = user_input
        state.messages = self.conversation_history.copy()
        state.image = None

        # 如果用户指定了技能，写入上下文
        if selected_skills:
            state.context["selected_skills"] = selected_skills

        return state, user_input, handler

    async def run_with_messages(
        self,
        messages: List[Dict[str, Any]],
        enable_thinking: Optional[bool] = None,
        storage_messages: Optional[List[Dict[str, Any]]] = None,
        selected_skills: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        运行代理流程 - 使用 OpenAI 标准 messages 格式（支持多模态）

        简化逻辑：
          - 有 selected_skills → 按需加载技能并执行
          - 无 selected_skills → LLM 直接回答
        """
        state, user_input, handler = await self._prepare_state(messages, selected_skills=selected_skills)

        # 添加任务
        task = Task(
            id=str(uuid.uuid4()),
            description=user_input
        )
        state.add_task(task)
        state.current_task = task

        # ── 有指定技能 → 按需加载并执行 ──
        if selected_skills:
            skill_name = selected_skills[0]
            state.context["selected_skill"] = skill_name
            state.current_tool = skill_name

            logger.info("[graph] 用户指定技能：%s，开始执行", skill_name)
            state = await self.executor.execute(state, enable_thinking=enable_thinking)
            state.is_complete = True
            state.final_result = state.messages[-1]["content"] if state.messages else ""

        # ── 无指定技能 → LLM 直接回答 ──
        else:
            logger.info("[graph] 未指定技能，LLM 直接回答")

            if not self.llm:
                state.add_message("assistant", "抱歉，我暂时无法处理这个问题。")
                state.final_result = "抱歉，我暂时无法处理这个问题。"
                state.is_complete = True
            else:
                from llm.llm import Message

                llm_messages = [
                    Message(role=msg.get("role", "user"), content=msg.get("content", ""))
                    for msg in state.messages
                ]

                response = await self.llm.chat(llm_messages, enable_thinking=enable_thinking)

                if response.thinking_content:
                    state.context["thinking_content"] = response.thinking_content

                state.add_message("assistant", response.content)
                state.final_result = response.content
                state.is_complete = True

        # 保存消息到数据库
        self._save_user_messages_to_db(storage_messages, messages)
        self._save_assistant_response_to_db(state)

        return state.to_dict()

    async def run_stream_with_messages(
        self,
        messages: List[Dict[str, Any]],
        enable_thinking: Optional[bool] = None,
        storage_messages: Optional[List[Dict[str, Any]]] = None,
        selected_skills: Optional[List[str]] = None,
        cancel_event: Optional[asyncio.Event] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        运行代理流程（流式版本）

        简化逻辑：
          - 有 selected_skills → 按需加载技能并执行
          - 无 selected_skills → LLM 直接回答
        """
        state, user_input, handler = await self._prepare_state(messages, selected_skills=selected_skills)

        # 添加任务
        task = Task(
            id=str(uuid.uuid4()),
            description=user_input
        )
        state.add_task(task)
        state.current_task = task

        # ── 有指定技能 → 按需加载并执行 ──
        if selected_skills:
            skill_name = selected_skills[0]
            state.context["selected_skill"] = skill_name
            state.current_tool = skill_name

            logger.info("[graph] 用户指定技能：%s，开始执行", skill_name)

            # 发送技能调用提示消息
            yield {
                "type": "skill_invoked",
                "content": f"正在调用技能: {skill_name}",
                "skill_name": skill_name,
            }

            full_response = ""
            full_thinking = ""

            async for chunk in self.executor.execute_stream(state, enable_thinking=enable_thinking, cancel_event=cancel_event):
                # 检查取消信号
                if cancel_event and cancel_event.is_set():
                    logger.info("Agent 流程检测到取消信号（执行阶段）")
                    yield {"type": "cancelled", "content": "请求已被用户取消"}
                    return

                chunk_type = chunk.get("type")
                if chunk_type == "reasoning_content":
                    full_thinking += chunk["content"]
                    if enable_thinking is not False:
                        yield {"type": "reasoning_content", "content": chunk["content"]}
                elif chunk_type == "token":
                    full_response += chunk["content"]
                    yield {"type": "token", "content": chunk["content"]}
                elif chunk_type == "tool_call":
                    logger.info("[graph] 子工具调用：%s", chunk.get("name"))
                    yield chunk
                elif chunk_type == "tool_result":
                    sub_tool = state.context.get("current_subtool")
                    logger.info("[graph] 工具结果返回：%s → %s（结果长度: %d）",
                                state.current_tool, sub_tool, len(str(chunk.get("result", ""))))
                    await handler.emit(EventType.TOOL_RESULT, {
                        "tool": state.current_tool,
                        "sub_tool": sub_tool,
                        "result": chunk.get("result")
                    })
                    yield chunk
                elif chunk_type == "status":
                    logger.info("[graph] 状态：%s", chunk.get("content"))
                    yield chunk
                elif chunk_type == "error":
                    logger.error("[graph] 错误：%s", chunk.get("content"))
                    yield chunk
                elif chunk_type == "cancelled":
                    yield chunk
                    return

            # 获取工具执行结果并显示最终状态
            tool_result = state.tool_results[-1] if state.tool_results else None
            if tool_result and tool_result.get("success", True):
                sub_tool = state.context.get("current_subtool")
                if sub_tool:
                    logger.info("工具执行完成：%s → %s", state.current_tool, sub_tool)
                else:
                    logger.info("工具执行完成：%s", state.current_tool)

            state.is_complete = True

            # 保存消息到数据库
            self._save_user_messages_to_db(storage_messages, messages)
            self._save_assistant_response_to_db(state)

            # 设置最终结果
            state.final_result = full_response
            if not state.final_result and state.messages:
                for msg in reversed(state.messages):
                    if msg.get("role") == "assistant" and msg.get("content"):
                        state.final_result = msg.get("content", "")
                        break
            if not state.final_result:
                state.final_result = ""

            final_result = state.to_dict()
            await handler.emit(EventType.COMPLETE, final_result)

            if state.final_result:
                yield {"type": "complete", "content": state.final_result}
            else:
                yield {"type": "complete", "content": ""}
            return

        # ── 无指定技能 → LLM 直接流式回答 ──
        logger.info("[graph] 未指定技能，LLM 直接回答")

        if not self.llm:
            yield {"type": "token", "content": "抱歉，我暂时无法处理这个问题。"}
            yield {"type": "complete", "content": "抱歉，我暂时无法处理这个问题。"}
            return

        from llm.llm import Message

        llm_messages = [
            Message(role=msg.get("role", "user"), content=msg.get("content", ""))
            for msg in state.messages
        ]

        full_response = ""
        full_thinking = ""

        async for chunk in self.llm.chat_stream(llm_messages, enable_thinking=enable_thinking, cancel_event=cancel_event):
            if cancel_event and cancel_event.is_set():
                yield {"type": "cancelled", "content": "请求已被用户取消"}
                return

            if isinstance(chunk, dict):
                chunk_type = chunk.get("type")
                if chunk_type == "reasoning_content":
                    full_thinking += chunk["content"]
                    if enable_thinking is not False:
                        yield {"type": "reasoning_content", "content": chunk["content"]}
                elif chunk_type == "content":
                    full_response += chunk["content"]
                    yield {"type": "token", "content": chunk["content"]}
            else:
                full_response += chunk
                yield {"type": "token", "content": chunk}

        state.add_message("assistant", full_response)
        state.final_result = full_response
        state.is_complete = True

        self._save_user_messages_to_db(storage_messages, messages)
        self._save_assistant_response_to_db(state)

        await handler.emit(EventType.COMPLETE, state.to_dict())
        yield {"type": "complete", "content": full_response}
