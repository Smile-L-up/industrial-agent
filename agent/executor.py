"""
Executor - 执行器
负责执行选定的技能或工具

重构说明：
  - 使用 core.logger 替代 print
  - 使用 routing_config.get_city_from_input() 替代硬编码城市列表
  - 使用 BaseSkill.call_tool() 替代 hasattr 检查
  - 清理调试残留
"""

import asyncio
import inspect
from typing import Any, Dict, Optional, AsyncGenerator, List
from .state import AgentState, Task
from .routing_config import get_city_from_input
from core.logger import get_logger

logger = get_logger("agent.executor")


class Executor:
    """执行器类"""

    def __init__(self, llm=None, skills=None):
        """
        初始化执行器

        Args:
            llm: 语言模型实例
            skills: 可用技能列表
        """
        self.llm = llm
        self.skills = skills or []

    async def execute(self, state: AgentState, enable_thinking: Optional[bool] = None) -> AgentState:
        """
        执行当前任务

        Args:
            state: 当前代理状态
            enable_thinking: 是否启用思考模式（可选）

        Returns:
            更新后的状态
        """
        if not state.current_task:
            state.set_error("没有当前任务")
            return state

        # 获取选中的技能
        selected_skill_name = state.context.get("selected_skill")

        # 记录工具调用
        tool_call = {
            "tool": selected_skill_name or "general",
            "args": {
                "task": state.current_task.description,
                "context": state.context.to_dict(),
            },
        }
        state.execution_record.add_tool_call(
            tool=selected_skill_name or "general",
            args=tool_call["args"],
        )

        if selected_skill_name:
            skill = self._find_skill(selected_skill_name)
            if skill:
                result = await self._execute_skill(skill, state)
            else:
                result = await self._execute_general(state, enable_thinking=enable_thinking)
        else:
            result = await self._execute_general(state, enable_thinking=enable_thinking)

        # 记录工具结果
        state.execution_record.add_tool_result(
            tool=selected_skill_name or "general",
            result=result,
            success=not state.error,
        )

        # 更新任务状态
        current_task = state.current_task
        if state.error:
            current_task.status = "failed"
            current_task.error = state.error
        else:
            current_task.status = "completed"
            current_task.result = result
            current_task.completed_at = current_task.created_at

        # 记录动作历史
        state.add_action({
            "task": current_task.description,
            "skill": selected_skill_name,
            "result": result,
        })

        # 添加响应消息
        if result:
            state.add_message("assistant", result)

        return state

    # ── 技能查找 ──────────────────────────────────────

    def _find_skill(self, name: str) -> Optional[Any]:
        """查找技能"""
        for skill in self.skills:
            if skill.name == name:
                return skill
        return None

    # ── 技能执行 ──────────────────────────────────────

    async def _execute_skill(self, skill: Any, state: AgentState) -> str:
        """
        执行特定技能。
        优先使用 BaseSkill 接口，回退到 hasattr 检查以兼容旧技能。
        """
        try:
            # ── 1. 尝试使用 BaseSkill 子工具接口 ──
            tools: List[Dict] = []
            if hasattr(skill, "get_tools") and callable(skill.get_tools):
                tools = skill.get_tools()

            if tools:
                selected_tool = await self._select_tool_with_llm(
                    state.current_task.description, tools, state
                )
                if selected_tool:
                    result = await self._call_tool_method(skill, selected_tool, state)
                    return result

            # ── 2. 调用技能的 execute 方法（通用回退） ──
            result = await skill.execute(
                task=state.current_task.description,
                context=state.context,
                messages=state.messages,
            )
            return result

        except Exception as e:
            logger.error(f"技能执行失败：{e}", exc_info=True)
            state.set_error(f"技能执行失败：{str(e)}")
            return f"执行失败：{str(e)}"

    # ── 子工具选择 ────────────────────────────────────

    async def _select_tool_with_llm(
        self, task: str, tools: List[Dict], state: AgentState
    ) -> Optional[str]:
        """使用 LLM 选择合适的子工具"""
        if not self.llm:
            return self._simple_tool_match(task, tools)

        tool_descriptions = "\n".join(
            [f"- {t['name']}: {t['description']}" for t in tools]
        )
        prompt = f"""你是一个工具选择助手。
请根据用户任务，选择合适的工具来处理。

可用工具：
{tool_descriptions}

用户任务：{task}

请只输出工具名称，不要输出其他内容。如果没有合适的工具，输出 null。"""

        try:
            from llm.llm import Message
            response = await self.llm.chat([Message(role="user", content=prompt)])
            selected_tool = response.content.strip()
            if selected_tool and selected_tool != "null":
                for tool in tools:
                    if tool["name"] == selected_tool:
                        return selected_tool
            return self._simple_tool_match(task, tools)
        except Exception as e:
            logger.error(f"LLM 工具选择失败：{e}")
            return self._simple_tool_match(task, tools)

    def _simple_tool_match(self, task: str, tools: List[Dict]) -> Optional[str]:
        """简单匹配工具 — 基于关键词"""
        task_lower = task.lower()

        weather_query_keywords = ["天气", "气温", "温度", "怎么样", "当前天气", "现在天气"]
        weather_forecast_keywords = ["预报", "预测", "未来", "明天", "后天", "几天"]

        for tool in tools:
            tool_name = tool["name"].lower()

            if any(kw in task_lower for kw in weather_query_keywords):
                if "current" in tool_name or "现在" in tool_name or "当前" in tool_name:
                    return tool["name"]

            if any(kw in task_lower for kw in weather_forecast_keywords):
                if "forecast" in tool_name or "预报" in tool_name:
                    return tool["name"]

        # 默认返回第一个工具
        return tools[0]["name"] if tools else None

    # ── 子工具调用 ────────────────────────────────────

    async def _call_tool_method(self, skill: Any, tool_name: str, state: AgentState) -> str:
        """调用技能的子工具方法"""
        try:
            state.context["current_subtool"] = tool_name

            # 从任务中提取城市（使用配置化的 city 提取）
            city = get_city_from_input(state.current_task.description)

            if not city:
                # 没有城市参数，回退到 execute
                return await skill.execute(
                    task=state.current_task.description,
                    context=state.context,
                    messages=state.messages,
                )

            # ── 优先使用 BaseSkill.call_tool() 接口 ──
            from core.base_skill import BaseSkill
            if isinstance(skill, BaseSkill):
                try:
                    result = await skill.call_tool(
                        tool_name=tool_name,
                        arguments={"city": city},
                        context=state.context.to_dict(),
                    )
                    return self._format_tool_result(tool_name, result)
                except AttributeError:
                    logger.warning(f"BaseSkill.call_tool 未找到子工具 {tool_name}，回退到 execute")

            # ── 回退：兼容旧技能的 hasattr 检查 ──
            if hasattr(skill, tool_name):
                method = getattr(skill, tool_name)
                if callable(method):
                    sig = inspect.signature(method)
                    params = list(sig.parameters.keys())

                    if "city" in params:
                        if asyncio.iscoroutinefunction(method):
                            result = await method(city)
                        else:
                            result = method(city)
                        return self._format_tool_result(tool_name, result)

            # 兜底回退到 execute
            return await skill.execute(
                task=state.current_task.description,
                context=state.context,
                messages=state.messages,
            )
        except Exception as e:
            logger.error(f"子工具调用失败：{e}", exc_info=True)
            return await skill.execute(
                task=state.current_task.description,
                context=state.context,
                messages=state.messages,
            )

    # ── 结果格式化 ────────────────────────────────────

    def _format_tool_result(self, tool_name: str, result: Any) -> str:
        """格式化工具结果"""
        if isinstance(result, dict):
            if "temp" in result and "condition" in result:
                city = result.get("city", "未知")
                return (
                    f"【天气查询结果】\n"
                    f"城市：{city}\n"
                    f"天气：{result['condition']}\n"
                    f"温度：{result['temp']}°C\n"
                    f"湿度：{result['humidity']}%\n"
                    f"风速：{result['wind']} km/h"
                )
        return str(result)

    async def _get_tool_result(
        self, skill: Any, tool_name: str, city: Optional[str]
    ) -> Any:
        """调用工具方法获取原始数据结果"""
        try:
            # 优先使用 BaseSkill.call_tool()
            from core.base_skill import BaseSkill
            if isinstance(skill, BaseSkill):
                args: Dict[str, Any] = {}
                if city:
                    args["city"] = city
                return await skill.call_tool(
                    tool_name=tool_name,
                    arguments=args,
                    context={},
                )

            # 回退：兼容旧技能
            if hasattr(skill, tool_name):
                method = getattr(skill, tool_name)
                if callable(method):
                    if asyncio.iscoroutinefunction(method):
                        return await method(city) if city else await method()
                    else:
                        return method(city) if city else method()
        except Exception as e:
            logger.error(f"工具执行失败：{e}")
        return None

    # ── LLM 生成回复 ──────────────────────────────────

    async def _generate_response_with_tool_result(
        self,
        user_query: str,
        tool_name: str,
        tool_result: Any,
        enable_thinking: Optional[bool] = None,
    ) -> str:
        """使用 LLM 根据工具执行结果生成自然语言回复（非流式）"""
        if not self.llm:
            return self._format_tool_result(tool_name, tool_result)

        from llm.llm import Message

        result_str = self._format_data_for_prompt(tool_result)

        prompt = f"""你是一个智能助手。你已经调用了工具获取了信息，现在需要根据工具返回的数据，用自然语言回答用户的问题。

用户问题：{user_query}
调用的工具：{tool_name}
工具返回的数据：{result_str}

请根据以上数据，用友好、自然的语言回答用户的问题。直接给出回答即可，不需要说明数据来源。"""

        try:
            response = await self.llm.chat(
                [Message(role="user", content=prompt)],
                enable_thinking=enable_thinking,
            )
            return response.content
        except Exception as e:
            logger.error(f"LLM 生成回复失败：{e}")
            return self._format_tool_result(tool_name, tool_result)

    async def _generate_response_with_tool_result_stream(
        self,
        user_query: str,
        tool_name: str,
        tool_result: Any,
        enable_thinking: Optional[bool] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """使用 LLM 根据工具执行结果生成自然语言回复（流式）"""
        if not self.llm:
            yield {"type": "token", "content": self._format_tool_result(tool_name, tool_result)}
            return

        from llm.llm import Message

        result_str = self._format_data_for_prompt(tool_result)

        prompt = f"""你是一个智能助手。你已经调用了工具获取了信息，现在需要根据工具返回的数据，用自然语言回答用户的问题。

用户问题：{user_query}
调用的工具：{tool_name}
工具返回的数据：{result_str}

请根据以上数据，用友好、自然的语言回答用户的问题。直接给出回答即可，不需要说明数据来源。"""

        try:
            async for chunk in self.llm.chat_stream(
                [Message(role="user", content=prompt)],
                enable_thinking=enable_thinking,
            ):
                if isinstance(chunk, dict):
                    chunk_type = chunk.get("type")
                    chunk_content = chunk.get("content", "")
                    if chunk_type == "reasoning_content":
                        if enable_thinking is not False:
                            yield {"type": "reasoning_content", "content": chunk_content}
                    elif chunk_type == "content":
                        yield {"type": "token", "content": chunk_content}
                else:
                    yield {"type": "token", "content": chunk}
        except Exception as e:
            logger.error(f"LLM 流式生成回复失败：{e}")
            yield {"type": "token", "content": self._format_tool_result(tool_name, tool_result)}

    # ── 数据格式化辅助 ────────────────────────────────

    def _format_data_for_prompt(self, data: Any) -> str:
        """统一格式化数据用于提示词"""
        if isinstance(data, dict):
            return self._format_dict_for_prompt(data)
        elif isinstance(data, list):
            return self._format_list_for_prompt(data)
        return str(data)

    def _format_dict_for_prompt(self, data: Dict) -> str:
        """格式化字典数据用于提示词"""
        return "\n".join(f"{key}: {value}" for key, value in data.items())

    def _format_list_for_prompt(self, data: List) -> str:
        """格式化列表数据用于提示词"""
        parts = []
        for i, item in enumerate(data):
            if isinstance(item, dict):
                item_str = self._format_dict_for_prompt(item)
            else:
                item_str = str(item)
            parts.append(f"{i + 1}. {item_str}")
        return "\n".join(parts)

    # ── 通用执行 ──────────────────────────────────────

    async def _execute_general(self, state: AgentState, enable_thinking: Optional[bool] = None) -> str:
        """执行通用任务（使用 LLM 直接回答）"""
        if self.llm is None:
            return "无法处理该请求，请配置语言模型。"

        from llm.llm import Message

        messages = [
            Message(role=msg.get("role", "user"), content=msg.get("content", ""))
            for msg in state.messages
        ]

        logger.debug(f"调用 _execute_general, enable_thinking={enable_thinking}")

        response = await self.llm.chat(messages, enable_thinking=enable_thinking)

        logger.debug(
            f"LLM 返回, thinking_content="
            f"{response.thinking_content[:50] if response.thinking_content else None}..."
        )

        # 保存思考内容到 state
        if response.thinking_content:
            state.context["thinking_content"] = response.thinking_content

        return response.content

    # ── 流式执行 ──────────────────────────────────────

    async def execute_stream(
        self, state: AgentState, enable_thinking: Optional[bool] = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        流式执行当前任务 — 支持思考模式

        Yields:
            流式事件数据：
            - {"type": "reasoning_content", "content": "..."}
            - {"type": "token", "content": "..."}
            - {"type": "error", "content": "..."}
            - {"type": "tool_call", "name": "...", "args": {...}}
            - {"type": "tool_result", "name": "...", "result": {...}}
        """
        if not state.current_task:
            state.set_error("没有当前任务")
            yield {"type": "error", "content": "没有当前任务"}
            return

        selected_skill_name = state.context.get("selected_skill")

        # 记录工具调用
        tool_call_args = {
            "task": state.current_task.description,
            "context": state.context.to_dict(),
        }
        state.execution_record.add_tool_call(
            tool=selected_skill_name or "general",
            args=tool_call_args,
        )

        if selected_skill_name:
            skill = self._find_skill(selected_skill_name)
            if skill:
                # ── 子工具流式路径 ──
                tools: List[Dict] = []
                if hasattr(skill, "get_tools") and callable(skill.get_tools):
                    tools = skill.get_tools()

                if tools:
                    selected_tool = self._simple_tool_match(
                        state.current_task.description, tools
                    )
                    if selected_tool:
                        state.context["current_subtool"] = selected_tool
                        city = get_city_from_input(state.current_task.description)

                        tool_result_data = await self._get_tool_result(
                            skill, selected_tool, city
                        )

                        state.execution_record.add_tool_result(
                            tool=selected_skill_name,
                            result=tool_result_data,
                            success=True,
                        )

                        yield {"type": "tool_result", "name": selected_tool, "result": tool_result_data}

                        # LLM 流式生成自然语言回复
                        full_response = ""
                        full_thinking = ""

                        async for chunk in self._generate_response_with_tool_result_stream(
                            state.current_task.description,
                            selected_tool,
                            tool_result_data,
                            enable_thinking,
                        ):
                            chunk_type = chunk.get("type")
                            chunk_content = chunk.get("content", "")

                            if chunk_type == "reasoning_content":
                                if enable_thinking is not False:
                                    full_thinking += chunk_content
                                    yield {"type": "reasoning_content", "content": chunk_content}
                            elif chunk_type == "token":
                                full_response += chunk_content
                                yield {"type": "token", "content": chunk_content}

                        if full_thinking:
                            state.context["thinking_content"] = full_thinking

                        state.add_message("assistant", full_response)
                        return

                # ── 技能流式执行 ──
                if hasattr(skill, "execute_stream"):
                    async for chunk in skill.execute_stream(
                        task=state.current_task.description,
                        context=state.context,
                        messages=state.messages,
                    ):
                        yield {"type": "token", "content": chunk}
                    return

        # ── 通用 LLM 流式回答 ──
        if self.llm is None:
            yield {"type": "error", "content": "无法处理该请求，请配置语言模型。"}
            return

        from llm.llm import Message

        messages = [
            Message(role=msg.get("role", "user"), content=msg.get("content", ""))
            for msg in state.messages
        ]

        full_response = ""
        full_thinking = ""

        logger.debug(f"调用 llm.chat_stream, enable_thinking={enable_thinking}")

        async for chunk in self.llm.chat_stream(messages, enable_thinking=enable_thinking):
            if isinstance(chunk, dict):
                chunk_type = chunk.get("type")
                chunk_content = chunk.get("content", "")

                if chunk_type == "reasoning_content":
                    if enable_thinking is not False:
                        full_thinking += chunk_content
                        yield {"type": "reasoning_content", "content": chunk_content}
                elif chunk_type == "content":
                    full_response += chunk_content
                    yield {"type": "token", "content": chunk_content}
                elif chunk_type == "usage":
                    state.context["usage"] = chunk.get("usage")
            else:
                full_response += chunk
                yield {"type": "token", "content": chunk}

        if full_thinking:
            state.context["thinking_content"] = full_thinking

        state.execution_record.add_tool_result(
            tool=selected_skill_name or "general",
            result=full_response,
            success=not state.error,
        )

        # 更新任务状态
        current_task = state.current_task
        if state.error:
            current_task.status = "failed"
            current_task.error = state.error
        else:
            current_task.status = "completed"
            current_task.result = full_response
            current_task.completed_at = current_task.created_at

        if full_response:
            state.add_message("assistant", full_response)

    # ── 辅助方法 ──────────────────────────────────────

    def _build_general_prompt(self, state: AgentState) -> str:
        """构建通用提示词（备用方案）"""
        messages = state.messages
        prompt_parts = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if isinstance(content, list):
                text_parts = [
                    item.get("text", "")
                    for item in content
                    if isinstance(item, dict) and item.get("type") == "text"
                ]
                content = " ".join(text_parts) if text_parts else str(content)
            prompt_parts.append(f"{role}: {content}")
        return "\n".join(prompt_parts)

    def add_skill(self, skill: Any):
        """添加技能"""
        self.skills.append(skill)

    def remove_skill(self, skill_name: str):
        """移除技能"""
        self.skills = [s for s in self.skills if s.name != skill_name]