"""
Executor - 执行器
负责执行选定的技能或工具

重构说明：
  - 使用 SkillLoader 按需加载技能，不再持有完整技能列表
  - 移除 routing_config 依赖，城市提取保留在本地
"""

import asyncio
import inspect
from typing import Any, Dict, Optional, AsyncGenerator, List
from .state import AgentState
from core.skill_loader import SkillLoader
from core.composite_skill import CompositeSkill
from core.logger import get_logger

logger = get_logger("agent.executor")


def _get_city_from_input(text: str) -> Optional[str]:
    """从用户输入中提取常见城市名称"""
    city_map = {
        "北京": "北京", "上海": "上海", "广州": "广州", "深圳": "深圳",
        "杭州": "杭州", "成都": "成都", "武汉": "武汉", "南京": "南京",
        "西安": "西安", "重庆": "重庆", "天津": "天津", "苏州": "苏州",
        "长沙": "长沙", "郑州": "郑州", "厦门": "厦门",
    }
    for alias, city in city_map.items():
        if alias in text:
            return city
    return None


class Executor:
    """执行器类 — 按需加载技能"""

    def __init__(self, llm=None, skill_loader: SkillLoader = None):
        """
        初始化执行器

        Args:
            llm: 语言模型实例
            skill_loader: 技能加载器（用于按需加载技能）
        """
        self.llm = llm
        self.skill_loader = skill_loader

    def _find_skill(self, name: str) -> Optional[Any]:
        """
        查找技能 — 优先从缓存获取，未命中则按需加载。

        Args:
            name: 技能名称

        Returns:
            BaseSkill 实例，未找到返回 None
        """
        if not self.skill_loader:
            return None
        return self.skill_loader.load_skill_full(name)

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
            if not isinstance(result, str):
                result = str(result)
            state.add_message("assistant", result)

        return state

    # ── 技能执行 ──────────────────────────────────────

    async def _execute_skill(self, skill: Any, state: AgentState) -> str:
        """
        执行特定技能。
        优先使用 BaseSkill 子工具接口，回退到 execute。
        对配置模式技能（有 inputs 但无子工具），先用 LLM 提取结构化参数。
        """
        try:
            # ── 复合技能：按步骤编排执行 ──
            if isinstance(skill, CompositeSkill) or (
                hasattr(skill, "_steps") and skill._steps
            ):
                return await self._execute_composite(skill, state)

            # 注入 LLM 到 context，供 HttpSkill 等配置模式技能使用
            if self.llm:
                state.context["_llm"] = self.llm

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

            # ── 2. 配置模式技能：用 LLM 提取结构化参数 ──
            skill_inputs = getattr(skill, "_inputs", None)
            if skill_inputs and self.llm:
                extracted = await self._extract_http_params(
                    state.current_task.description, skill_inputs
                )
                logger.info("配置模式技能参数提取结果：%s", extracted)
                if extracted:
                    state.context["extracted_args"] = extracted

            # ── 3. 调用技能的 execute 方法 ──
            result = await skill.execute(
                task=state.current_task.description,
                context=state.context,
                messages=state.messages,
            )
            return result

        except Exception as e:
            logger.error("技能执行失败：%s", e, exc_info=True)
            state.set_error(f"技能执行失败：{str(e)}")
            return f"执行失败：{str(e)}"

    # ── 复合技能执行 ──────────────────────────────────

    async def _execute_composite(self, skill: Any, state: AgentState) -> str:
        """
        执行复合技能：按 steps 顺序串联执行子技能，
        前一步的结果自动注入到后续步骤的参数模板中。
        """
        try:
            if self.llm:
                state.context["_llm"] = self.llm

            result = await skill.execute(
                task=state.current_task.description,
                context=state.context,
                messages=state.messages,
            )
            return result
        except Exception as e:
            logger.error("复合技能执行失败：%s", e, exc_info=True)
            state.set_error(f"复合技能执行失败：{str(e)}")
            return f"执行失败：{str(e)}"

    async def _execute_composite_stream(
        self,
        skill: Any,
        state: AgentState,
        enable_thinking: Optional[bool] = None,
        cancel_event: Optional[asyncio.Event] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """复合技能流式执行：逐个输出子技能调用状态，最后用 LLM 流式生成回复"""
        try:
            if self.llm:
                state.context["_llm"] = self.llm

            # ── 第 1 步：LLM 规划 ──
            from llm.llm import Message
            import json as _json

            sub_skills_info = skill._collect_sub_skills_info()
            if not sub_skills_info:
                yield {"type": "error", "content": "无法加载任何子技能"}
                return

            plan_prompt = skill._build_plan_prompt(state.current_task.description, sub_skills_info)
            plan_response = await self.llm.chat([Message(role="user", content=plan_prompt)])
            plan = skill._parse_plan(plan_response.content)

            if not plan:
                yield {"type": "token", "content": plan_response.content}
                return

            logger.info("复合技能执行计划：%s", _json.dumps(plan, ensure_ascii=False))

            # ── 第 2 步：逐个执行子技能，每次执行前 yield tool_call ──
            results = []
            for i, step in enumerate(plan):
                if cancel_event and cancel_event.is_set():
                    yield {"type": "cancelled", "content": "请求已被用户取消"}
                    return

                skill_name = step.get("skill", "")
                args = step.get("args", {})
                desc = step.get("description", skill_name)

                yield {
                    "type": "tool_call",
                    "name": skill_name,
                    "args": {"step": f"{i + 1}/{len(plan)}", "description": desc},
                }

                sub_skill = skill._load_sub_skill(skill_name)
                if not sub_skill:
                    results.append({"step": desc, "skill": skill_name, "error": "子技能加载失败"})
                    continue

                sub_result = await skill._execute_sub_skill(
                    sub_skill, state.current_task.description, state.context, state.messages, args
                )
                results.append({
                    "step": desc,
                    "skill": skill_name,
                    "args": args,
                    "result": sub_result if len(str(sub_result)) < 2000 else str(sub_result)[:2000],
                })

            logger.info("子技能执行完毕，共 %d 步", len(results))

            # ── 第 3 步：LLM 整合结果 ──
            answer_prompt = skill._build_answer_prompt(state.current_task.description, results)
            answer_response = await self.llm.chat([Message(role="user", content=answer_prompt)])
            result = answer_response.content

            state.execution_record.add_tool_result(
                tool=state.context.get("selected_skill", "composite"),
                result=result,
                success=True,
            )

            # 用 LLM 流式生成自然语言回复
            if self.llm:
                async for chunk in self._generate_response_with_tool_result_stream(
                    state.current_task.description,
                    state.context.get("selected_skill", "composite"),
                    result,
                    enable_thinking,
                    cancel_event=cancel_event,
                ):
                    if cancel_event and cancel_event.is_set():
                        return
                    chunk_type = chunk.get("type")
                    chunk_content = chunk.get("content", "")
                    if chunk_type == "reasoning_content":
                        if enable_thinking is not False:
                            yield {"type": "reasoning_content", "content": chunk_content}
                    elif chunk_type == "token":
                        yield {"type": "token", "content": chunk_content}
            else:
                yield {"type": "token", "content": str(result)}

        except Exception as e:
            logger.error("复合技能流式执行失败：%s", e, exc_info=True)
            yield {"type": "error", "content": f"复合技能执行失败：{str(e)}"}

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
            logger.error("LLM 工具选择失败：%s", e)
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

    # ── 配置模式技能：LLM 参数提取 ──────────────────────

    async def _extract_http_params(
        self, task: str, skill_inputs: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        使用 LLM 从用户消息中提取结构化参数（JSON）。
        用于配置模式技能（如 HttpSkill），让 LLM 直接生成工具调用参数。
        """
        import json
        import re

        param_lines = []
        for name, cfg in skill_inputs.items():
            desc = cfg.get("description", cfg.get("type", "string"))
            default = cfg.get("default", "")
            if default:
                param_lines.append(f'  "{name}": "{desc}"（默认值：{default}）')
            else:
                param_lines.append(f'  "{name}": "{desc}"')
        params_desc = "\n".join(param_lines)

        prompt = f"""请从用户消息中提取以下参数，返回 JSON 对象。
只返回 JSON，不要其他文字。未提及的参数不要包含。
对于日期类参数如"昨天"，请转换为 YYYY-MM-DD 格式。

参数说明：
{params_desc}

用户消息：{task}

JSON："""

        logger.info("LLM 参数提取，用户消息：%s", task)
        logger.debug("参数提取 prompt：%s", prompt)

        try:
            from llm.llm import Message
            response = await self.llm.chat([Message(role="user", content=prompt)])
            text = response.content.strip()
            logger.info("LLM 参数提取原始返回：%s", text[:200])
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
            result = json.loads(text)
            logger.info("LLM 参数提取成功：%s", result)
            return result
        except json.JSONDecodeError as e:
            logger.warning("LLM 参数提取 JSON 解析失败：%s，原始返回：%s", e, text[:200])
            return {}
        except Exception as e:
            logger.warning("LLM 参数提取失败：%s", e, exc_info=True)
            return {}

    # ── 子工具调用 ────────────────────────────────────

    async def _call_tool_method(self, skill: Any, tool_name: str, state: AgentState) -> str:
        """调用技能的子工具方法"""
        try:
            state.context["current_subtool"] = tool_name
            task = state.current_task.description

            # 优先使用 BaseSkill.call_tool() 接口
            from core.base_skill import BaseSkill
            if isinstance(skill, BaseSkill):
                try:
                    arguments = self._extract_tool_arguments(skill, tool_name, task)
                    result = await skill.call_tool(
                        tool_name=tool_name,
                        arguments=arguments,
                        context=state.context.to_dict(),
                    )
                    # 如果工具返回了错误，回退到 execute
                    if isinstance(result, dict) and result.get("success") is False:
                        logger.info("子工具 %s 返回错误，回退到 execute: %s", tool_name, result.get("error"))
                        return await skill.execute(
                            task=task, context=state.context, messages=state.messages,
                        )
                    return self._format_tool_result(tool_name, result)
                except AttributeError:
                    logger.warning("BaseSkill.call_tool 未找到子工具 %s，回退到 execute", tool_name)

            # 回退：兼容旧技能
            if hasattr(skill, tool_name):
                method = getattr(skill, tool_name)
                if callable(method):
                    sig = inspect.signature(method)
                    params = [p for p in sig.parameters.keys() if p not in ("self", "kwargs", "context", "messages")]

                    arguments = self._extract_tool_arguments(skill, tool_name, task)
                    call_args = {k: v for k, v in arguments.items() if k in params}
                    if call_args:
                        if inspect.iscoroutinefunction(method):
                            result = await method(**call_args)
                        else:
                            result = method(**call_args)
                        if isinstance(result, dict) and result.get("success") is False:
                            logger.info("子工具 %s 返回错误，回退到 execute", tool_name)
                        else:
                            return self._format_tool_result(tool_name, result)

            # 兜底回退到 execute
            return await skill.execute(
                task=task, context=state.context, messages=state.messages,
            )
        except Exception as e:
            logger.error("子工具调用失败：%s", e, exc_info=True)
            return await skill.execute(
                task=state.current_task.description,
                context=state.context,
                messages=state.messages,
            )

    def _extract_tool_arguments(self, skill: Any, tool_name: str, task: str) -> Dict[str, Any]:
        """根据工具参数定义从用户输入中提取参数"""
        arguments = {}

        # 获取工具期望的参数列表
        expected_params = set()
        if hasattr(skill, "get_tools") and callable(skill.get_tools):
            for t in skill.get_tools():
                if t.get("name") == tool_name:
                    params = t.get("parameters", {})
                    if isinstance(params, dict):
                        expected_params = set(params.keys())
                    break

        # 如果没找到参数定义，检查方法签名
        if not expected_params and hasattr(skill, tool_name):
            method = getattr(skill, tool_name)
            if callable(method):
                sig = inspect.signature(method)
                expected_params = {
                    p for p in sig.parameters.keys()
                    if p not in ("self", "kwargs", "context", "messages")
                }

        # 根据期望参数提取值
        for param in expected_params:
            if param == "city":
                city = _get_city_from_input(task)
                if city:
                    arguments["city"] = city
            elif param == "expression":
                expr = self._extract_expression(task)
                if expr:
                    arguments["expression"] = expr

        logger.debug("工具 %s 参数提取: expected=%s, extracted=%s", tool_name, expected_params, arguments)
        return arguments

    @staticmethod
    def _extract_expression(text: str) -> Optional[str]:
        """从用户输入中提取数学表达式"""
        import re
        # 移除常见中文词汇，保留运算符和数字
        # 按长度降序排列，确保 "乘以" 先于 "乘" 被替换
        replacements = [
            ("乘以", "*"), ("除以", "/"), ("等于", "="),
            ("是多少", ""), ("算一下", ""),
            ("加", "+"), ("减", "-"), ("乘", "*"), ("除", "/"),
            ("多少", ""), ("计算", ""), ("算算", ""), ("请问", ""), ("帮我", ""), ("求", ""),
        ]
        expr = text
        for cn, en in replacements:
            expr = expr.replace(cn, en)

        # 匹配包含数字和运算符的表达式
        pattern = r'[\d\.\+\-\*\/\(\)\s]+'
        matches = re.findall(pattern, expr)
        if matches:
            expr = max(matches, key=len).strip()
            if re.search(r'[\+\-\*\/]', expr):
                return expr

        # 从原始文本中尝试提取
        matches = re.findall(pattern, text)
        if matches:
            expr = max(matches, key=len).strip()
            if re.search(r'[\+\-\*\/]', expr):
                return expr

        return None

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

            if hasattr(skill, tool_name):
                method = getattr(skill, tool_name)
                if callable(method):
                    if inspect.iscoroutinefunction(method):
                        return await method(city) if city else await method()
                    else:
                        return method(city) if city else method()
        except Exception as e:
            logger.error("工具执行失败：%s", e)
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
            logger.error("LLM 生成回复失败：%s", e)
            return self._format_tool_result(tool_name, tool_result)

    async def _generate_response_with_tool_result_stream(
        self,
        user_query: str,
        tool_name: str,
        tool_result: Any,
        enable_thinking: Optional[bool] = None,
        cancel_event: Optional[asyncio.Event] = None,
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
                cancel_event=cancel_event,
                enable_thinking=enable_thinking,
            ):
                # 检查取消信号
                if cancel_event and cancel_event.is_set():
                    logger.info("工具结果生成阶段检测到取消信号")
                    return
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
        except asyncio.CancelledError:
            logger.info("工具结果生成阶段被取消")
            return
        except Exception as e:
            logger.error("LLM 流式生成回复失败：%s", e)
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

        messages = self._build_messages(state)

        logger.debug("调用 _execute_general, enable_thinking=%s", enable_thinking)

        response = await self.llm.chat(messages, enable_thinking=enable_thinking)

        logger.debug(
            "LLM 返回, thinking_content=%s...",
            response.thinking_content[:50] if response.thinking_content else None,
        )

        if response.thinking_content:
            state.context["thinking_content"] = response.thinking_content

        return response.content

    # ── 流式执行 ──────────────────────────────────────

    async def execute_stream(
        self, state: AgentState, enable_thinking: Optional[bool] = None,
        cancel_event: Optional[asyncio.Event] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        流式执行当前任务 — 支持思考模式

        Args:
            state: 当前代理状态
            enable_thinking: 是否启用思考模式
            cancel_event: 取消信号事件

        Yields:
            流式事件数据
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
                logger.info("[executor] 已加载技能：%s (类型: %s)", selected_skill_name, type(skill).__name__)

                # ── 复合技能流式执行 ──
                if isinstance(skill, CompositeSkill) or (
                    hasattr(skill, "_steps") and skill._steps
                ):
                    logger.info("[executor] 走复合技能路径")
                    async for chunk in self._execute_composite_stream(
                        skill, state, enable_thinking=enable_thinking,
                        cancel_event=cancel_event
                    ):
                        yield chunk
                    return

                # ── 子工具流式路径 ──
                tools: List[Dict] = []
                if hasattr(skill, "get_tools") and callable(skill.get_tools):
                    tools = skill.get_tools()

                if tools:
                    logger.info("[executor] 走子工具路径，工具数: %d", len(tools))
                    selected_tool = self._simple_tool_match(
                        state.current_task.description, tools
                    )
                    if selected_tool:
                        state.context["current_subtool"] = selected_tool

                        # 使用通用参数提取
                        arguments = self._extract_tool_arguments(skill, selected_tool, state.current_task.description)
                        from core.base_skill import BaseSkill
                        if isinstance(skill, BaseSkill):
                            tool_result_data = await skill.call_tool(
                                tool_name=selected_tool,
                                arguments=arguments,
                                context=state.context.to_dict(),
                            )
                        else:
                            tool_result_data = await self._get_tool_result(skill, selected_tool, None)

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
                            cancel_event=cancel_event,
                        ):
                            # 检查取消信号
                            if cancel_event and cancel_event.is_set():
                                logger.info("子工具执行阶段检测到取消信号")
                                return

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

                # ── 配置模式技能（如 HttpSkill）：LLM 提取参数 + 调用服务 ──
                skill_inputs = getattr(skill, "_inputs", None)
                if skill_inputs:
                    logger.info("[executor] 走配置模式路径，inputs: %s", list(skill_inputs.keys()))
                    if self.llm:
                        state.context["_llm"] = self.llm

                    # 用 LLM 从用户消息中提取结构化参数
                    if self.llm:
                        yield {"type": "status", "content": "正在提取参数......"}
                        extracted = await self._extract_http_params(
                            state.current_task.description, skill_inputs
                        )
                        if extracted:
                            state.context["extracted_args"] = extracted
                            logger.info("LLM 参数提取结果：%s", extracted)
                        else:
                            logger.warning("LLM 参数提取返回空")

                    # 执行技能（HTTP 调用）
                    yield {"type": "status", "content": f"正在调用 {selected_skill_name} 服务......"}
                    try:
                        result = await skill.execute(
                            task=state.current_task.description,
                            context=state.context,
                            messages=state.messages,
                        )
                    except Exception as e:
                        logger.error("配置模式技能执行失败：%s", e, exc_info=True)
                        result = f"服务调用失败：{str(e)}"

                    state.execution_record.add_tool_result(
                        tool=selected_skill_name,
                        result=result,
                        success=True,
                    )

                    logger.info("[executor] 技能执行完成：%s（结果长度: %d）", selected_skill_name, len(str(result)))
                    yield {"type": "tool_result", "name": selected_skill_name, "result": result}

                    # 流式输出结果
                    if self.llm:
                        async for chunk in self._generate_response_with_tool_result_stream(
                            state.current_task.description,
                            selected_skill_name,
                            result,
                            enable_thinking,
                            cancel_event=cancel_event,
                        ):
                            # 检查取消信号
                            if cancel_event and cancel_event.is_set():
                                logger.info("配置模式技能执行阶段检测到取消信号")
                                return
                            chunk_type = chunk.get("type")
                            chunk_content = chunk.get("content", "")
                            if chunk_type == "reasoning_content":
                                if enable_thinking is not False:
                                    yield {"type": "reasoning_content", "content": chunk_content}
                            elif chunk_type == "token":
                                yield {"type": "token", "content": chunk_content}
                    else:
                        yield {"type": "token", "content": str(result)}

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

        messages = self._build_messages(state)

        full_response = ""
        full_thinking = ""

        logger.debug("调用 llm.chat_stream, enable_thinking=%s", enable_thinking)

        async for chunk in self.llm.chat_stream(messages, cancel_event=cancel_event, enable_thinking=enable_thinking):
            # 检查取消信号
            if cancel_event and cancel_event.is_set():
                logger.info("通用执行阶段检测到取消信号")
                return

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

    def _build_messages(self, state: AgentState) -> list:
        """从 state.messages 构建 LLM Message 列表"""
        from llm.llm import Message
        return [
            Message(role=msg.get("role", "user"), content=msg.get("content", ""))
            for msg in state.messages
        ]

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
