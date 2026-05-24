"""
McpSkill - MCP 服务技能
通过 MCP (Model Context Protocol) 调用外部 MCP 服务（如 Dify 工作流发布的 MCP 服务）
用户只需编写 SKILL.md，无需写 Python 代码

传输方式：Streamable HTTP（POST JSON-RPC）
"""

import json
import logging
import re
from typing import Dict, List, Any, Optional

from core.base_skill import BaseSkill

logger = logging.getLogger("industrial_agent.mcp_skill")


class McpSkill(BaseSkill):
    """MCP 服务技能 — 配置驱动，通过 MCP 协议调用外部工具"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._name = config.get("name", "mcp_skill")
        self._description = config.get("description", "MCP 服务技能")
        self._keywords: List[str] = config.get("keywords", [])

        # MCP 服务配置（兼容新旧格式）
        # 新格式：service 对象中
        service = config.get("service", {})
        # 旧格式：mcp 对象中
        mcp = config.get("mcp", {})

        # 优先从 service 获取，回退到 mcp
        self._endpoint = service.get("endpoint") or mcp.get("endpoint", "")
        self._timeout = service.get("timeout") or mcp.get("timeout", 120)
        self._tool_name = service.get("tool_name", "")

        # 参数配置（可选，来自 SKILL.md inputs，用于默认值/必填校验/描述覆盖）
        self._inputs: Dict[str, Any] = service.get("inputs") or config.get("inputs", {})

        # MCP 工具缓存（首次调用时从服务端获取）
        self._tools_cache: Optional[List[Dict[str, Any]]] = None

        # LLM 实例（运行时由 executor 注入）
        self._llm = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def match_keywords(self) -> List[str]:
        return self._keywords

    def get_tools(self) -> List[Dict[str, Any]]:
        """返回 MCP 服务端暴露的工具列表（同步版本，返回缓存）"""
        if self._tools_cache is not None:
            return [
                {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("inputSchema", {}),
                }
                for t in self._tools_cache
            ]
        return []

    # ── 子工具调用 ──────────────────────────────────────

    async def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Any:
        """通过 MCP 协议调用远程工具，而非查找本地方法"""
        import httpx

        # 注入 LLM
        if self._llm is None:
            if hasattr(context, "get"):
                self._llm = context.get("_llm")

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            await self._mcp_initialize(client)

            # 如果缓存为空，先获取工具列表
            if not self._tools_cache:
                tools = await self._mcp_list_tools(client)
                self._tools_cache = tools

            # 如果指定了 tool_name 限制，校验调用方传入的工具名是否匹配
            if self._tool_name and tool_name != self._tool_name:
                return {"success": False, "error": f"不允许调用工具 {tool_name}，仅允许: {self._tool_name}"}

            tool = next((t for t in self._tools_cache if t["name"] == tool_name), None)
            if not tool:
                return {"success": False, "error": f"MCP 工具不存在: {tool_name}"}

            # 合并 MCP inputSchema + SKILL.md inputs
            merged_schema = self._build_merged_schema(tool.get("inputSchema", {}))

            # 如果参数为空，用 LLM 从上下文提取
            if not arguments:
                task = context.get("task", "") if isinstance(context, dict) else ""
                if self._llm:
                    arguments = await self._extract_arguments(task, [], merged_schema)
                else:
                    arguments = self._fallback_extract(task, merged_schema)

            # 填充默认值
            arguments = self._fill_defaults(arguments, merged_schema)

            # 校验必填参数
            missing = self._find_missing_required(arguments, merged_schema)
            if missing:
                return self._build_missing_params_question(missing)

            result = await self._mcp_call_tool(client, tool_name, arguments)
            return self._format_result(result)

    # ── 核心执行 ──────────────────────────────────────

    async def execute(
        self,
        task: str,
        context: Dict[str, Any],
        messages: List[Dict[str, str]],
    ) -> str:
        import httpx

        # 注入 LLM
        if self._llm is None:
            if hasattr(context, "get"):
                self._llm = context.get("_llm")
            elif hasattr(context, "extra"):
                self._llm = context.extra.get("_llm")

        # 优先使用 executor 预提取的参数
        extracted = {}
        if hasattr(context, "get"):
            extracted = context.get("extracted_args", {})
        elif hasattr(context, "extra"):
            extracted = context.extra.get("extracted_args", {})

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            # 1. 初始化 MCP 连接
            await self._mcp_initialize(client)

            # 2. 获取工具列表
            tools = await self._mcp_list_tools(client)
            if not tools:
                return "MCP 服务未暴露任何工具"

            self._tools_cache = tools

            # 如果指定了 tool_name，只保留匹配的工具
            if self._tool_name:
                tools = [t for t in tools if t.get("name") == self._tool_name]
                if not tools:
                    return f"MCP 服务中未找到指定工具: {self._tool_name}"

            # 3. 选择工具 + 提取参数
            tool_name, arguments = await self._resolve_tool_call(
                task, messages, tools, pre_extracted=extracted
            )

            # 4. 调用工具
            result = await self._mcp_call_tool(client, tool_name, arguments)

            return self._format_result(result)

    # ── MCP 协议交互 ──────────────────────────────────

    async def _mcp_initialize(self, client) -> None:
        """发送 MCP initialize 请求"""
        payload = {
            "jsonrpc": "2.0",
            "method": "initialize",
            "id": 1,
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "industrial-agent", "version": "1.0.0"},
            },
        }
        logger.info("[McpSkill] initialize 请求：%s", json.dumps(payload, ensure_ascii=False))
        resp = await client.post(
            self._endpoint,
            json=payload,
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        logger.info("[McpSkill] initialize 响应内容：%s", resp.text[:1000])
        resp.raise_for_status()

        # 发送 initialized 通知
        notification = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        logger.info("[McpSkill] notifications/initialized 通知已发送")
        await client.post(
            self._endpoint,
            json=notification,
            headers={"Content-Type": "application/json; charset=utf-8"},
        )

    async def _mcp_list_tools(self, client) -> List[Dict[str, Any]]:
        """获取 MCP 服务端的工具列表"""
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/list",
            "id": 2,
            "params": {},
        }
        logger.info("[McpSkill] tools/list 请求：%s", json.dumps(payload, ensure_ascii=False))
        resp = await client.post(
            self._endpoint,
            json=payload,
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        logger.info("[McpSkill] tools/list 响应内容（前2000字符）：%s", resp.text[:2000])
        resp.raise_for_status()
        data = resp.json()
        tools = data.get("result", {}).get("tools", [])
        logger.info("[McpSkill] 获取到 %d 个工具", len(tools))
        return tools

    async def _mcp_call_tool(
        self, client, tool_name: str, arguments: Dict[str, Any]
    ) -> Any:
        """调用 MCP 工具"""
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": 3,
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
        }
        logger.info("[McpSkill] tools/call 请求：%s", json.dumps(payload, ensure_ascii=False, default=str)[:2000])
        resp = await client.post(
            self._endpoint,
            json=payload,
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        logger.info("[McpSkill] tools/call 响应内容（前2000字符）：%s", resp.text[:2000])
        resp.raise_for_status()
        data = resp.json()

        result = data.get("result", {})
        if result.get("isError"):
            contents = result.get("content", [])
            error_text = " ".join(c.get("text", "") for c in contents if c.get("type") == "text")
            logger.error("[McpSkill] MCP 工具执行失败: %s", error_text)
            return f"MCP 工具执行失败: {error_text}"

        extracted = self._extract_content(result)
        logger.info("[McpSkill] 提取结果（前1000字符）：%s", str(extracted)[:1000])
        return extracted

    def _extract_content(self, result: Dict[str, Any]) -> Any:
        """从 MCP 响应中提取内容"""
        contents = result.get("content", [])
        if not contents:
            return ""

        # 单个 text 类型：尝试解析 JSON
        if len(contents) == 1 and contents[0].get("type") == "text":
            text = contents[0]["text"]
            try:
                return json.loads(text)
            except (json.JSONDecodeError, ValueError):
                return text

        # 多个内容：拼接文本
        parts = []
        for c in contents:
            if c.get("type") == "text":
                parts.append(c["text"])
        return "\n".join(parts)

    # ── 工具选择 + 参数提取 ───────────────────────────

    async def _resolve_tool_call(
        self,
        task: str,
        messages: List[Dict[str, str]],
        tools: List[Dict[str, Any]],
        pre_extracted: Optional[Dict[str, Any]] = None,
    ) -> tuple:
        """
        选择要调用的 MCP 工具并提取参数。
        返回 (tool_name, arguments)
        """
        # 单工具场景：直接用，只提取参数
        if len(tools) == 1:
            tool = tools[0]
            tool_name = tool["name"]
            merged_schema = self._build_merged_schema(tool.get("inputSchema", {}))
            arguments = await self._prepare_arguments(
                task, messages, merged_schema, pre_extracted
            )
            return tool_name, arguments

        # 多工具场景：先选工具，再提取参数
        tool_name = await self._select_tool(task, tools)
        selected = next((t for t in tools if t["name"] == tool_name), tools[0])
        merged_schema = self._build_merged_schema(selected.get("inputSchema", {}))
        arguments = await self._prepare_arguments(
            task, messages, merged_schema, pre_extracted
        )
        return tool_name, arguments

    async def _select_tool(self, task: str, tools: List[Dict[str, Any]]) -> str:
        """用 LLM 从多个 MCP 工具中选择一个"""
        if not self._llm:
            return tools[0]["name"]

        tool_descs = "\n".join(
            f"- {t['name']}: {t.get('description', '')}" for t in tools
        )
        prompt = f"""根据用户任务选择合适的工具，只输出工具名称。

可用工具：
{tool_descs}

用户任务：{task}

工具名："""

        try:
            from llm.llm import Message

            response = await self._llm.chat([Message(role="user", content=prompt)])
            selected = response.content.strip()
            for t in tools:
                if t["name"] == selected:
                    return selected
        except Exception as e:
            logger.warning("LLM 工具选择失败: %s", e)

        return tools[0]["name"]

    # ── Schema 合并 + 参数准备 ─────────────────────────

    def _build_merged_schema(self, mcp_schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        合并 MCP inputSchema + SKILL.md inputs。
        SKILL.md 的配置优先：description 覆盖、required 补充、default 新增。
        """
        if not self._inputs:
            return mcp_schema

        merged = json.loads(json.dumps(mcp_schema))  # deep copy
        mcp_props = merged.get("properties", {})
        mcp_required = set(merged.get("required", []))

        for param_name, cfg in self._inputs.items():
            if param_name in mcp_props:
                # 覆盖已有属性
                if "description" in cfg:
                    mcp_props[param_name]["description"] = cfg["description"]
                if "type" in cfg:
                    mcp_props[param_name]["type"] = cfg["type"]
            else:
                # 补充新参数
                mcp_props[param_name] = {
                    "type": cfg.get("type", "string"),
                    "description": cfg.get("description", param_name),
                }
            # default 始终写入（MCP inputSchema 通常没有 default）
            if "default" in cfg:
                mcp_props[param_name]["default"] = cfg["default"]

            # required 合并
            if cfg.get("required", False):
                mcp_required.add(param_name)

        merged["properties"] = mcp_props
        if mcp_required:
            merged["required"] = list(mcp_required)

        return merged

    async def _prepare_arguments(
        self,
        task: str,
        messages: List[Dict[str, str]],
        merged_schema: Dict[str, Any],
        pre_extracted: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """完整的参数准备链路：预提取 → LLM提取 → 默认值 → 必填校验"""
        # 1. 优先使用 executor 预提取的参数
        arguments = dict(pre_extracted) if pre_extracted else {}

        # 2. 缺少的参数用 LLM 补充提取
        properties = merged_schema.get("properties", {})
        missing_keys = [k for k in properties if k not in arguments]
        if missing_keys and self._llm:
            try:
                extracted = await self._extract_with_llm(task, messages, merged_schema)
                for k, v in extracted.items():
                    if k not in arguments:
                        arguments[k] = v
            except Exception as e:
                logger.warning("LLM 参数提取失败，回退: %s", e)
                if not arguments:
                    arguments = self._fallback_extract(task, merged_schema)

        # 3. 填充默认值
        arguments = self._fill_defaults(arguments, merged_schema)

        # 4. 校验必填参数
        missing = self._find_missing_required(arguments, merged_schema)
        if missing:
            logger.warning("缺少必填参数: %s", missing)
            # 不阻塞，交给 call_tool 的返回值处理

        return arguments

    def _fill_defaults(
        self, arguments: Dict[str, Any], schema: Dict[str, Any]
    ) -> Dict[str, Any]:
        """用 SKILL.md inputs 中的 default 值填充缺失参数"""
        result = dict(arguments)
        for param_name, prop in schema.get("properties", {}).items():
            if param_name not in result and "default" in prop:
                result[param_name] = prop["default"]
        return result

    def _find_missing_required(
        self, arguments: Dict[str, Any], schema: Dict[str, Any]
    ) -> List[str]:
        """找出缺少的必填参数"""
        required = schema.get("required", [])
        return [k for k in required if k not in arguments]

    def _build_missing_params_question(self, missing_keys: List[str]) -> str:
        """构建参数追问消息"""
        lines = []
        for key in missing_keys:
            cfg = self._inputs.get(key, {})
            desc = cfg.get("description", key)
            lines.append(f"- {desc}")
        params_list = "\n".join(lines)
        return f"我还需要以下信息才能完成操作，请提供：\n{params_list}"

    # ── 参数提取 ─────────────────────────────────────

    async def _extract_arguments(
        self,
        task: str,
        messages: List[Dict[str, str]],
        schema: Dict[str, Any],
    ) -> Dict[str, Any]:
        """从用户消息中提取 MCP 工具参数"""
        properties = schema.get("properties", {})
        if not properties:
            return {}

        # 尝试 LLM 提取
        if self._llm:
            try:
                return await self._extract_with_llm(task, messages, schema)
            except Exception as e:
                logger.warning("LLM 参数提取失败，回退: %s", e)

        # 回退：直接把用户输入作为 query 参数
        return self._fallback_extract(task, schema)

    async def _extract_with_llm(
        self,
        task: str,
        messages: List[Dict[str, str]],
        schema: Dict[str, Any],
    ) -> Dict[str, Any]:
        """用 LLM 从对话中提取结构化参数"""
        from llm.llm import Message

        properties = schema.get("properties", {})
        required = schema.get("required", [])

        param_lines = []
        for name, prop in properties.items():
            desc = prop.get("description", prop.get("type", "string"))
            req = "（必填）" if name in required else "（可选）"
            param_lines.append(f'  "{name}": {desc}{req}')
        params_desc = "\n".join(param_lines)

        # 构建对话上下文
        conversation = ""
        if messages:
            for msg in messages[-6:]:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if isinstance(content, str):
                    conversation += f"{role}: {content}\n"
        else:
            conversation = f"user: {task}\n"

        prompt = f"""从以下对话中提取参数值，返回 JSON 对象。
只返回 JSON，不要其他文字。未提及的参数不要包含。

参数说明：
{params_desc}

对话记录：
{conversation}
JSON："""

        response = await self._llm.chat([Message(role="user", content=prompt)])
        text = response.content.strip()

        # 清除 markdown 代码块标记
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

        return json.loads(text)

    def _fallback_extract(self, task: str, schema: Dict[str, Any]) -> Dict[str, Any]:
        """回退：将用户输入填入第一个 string 类型参数"""
        properties = schema.get("properties", {})
        required = schema.get("required", [])

        # 找第一个 string 类型参数（优先 required 的）
        target_key = None
        for key in required:
            if properties.get(key, {}).get("type") == "string":
                target_key = key
                break
        if not target_key:
            for key, prop in properties.items():
                if prop.get("type") == "string":
                    target_key = key
                    break

        if target_key:
            return {target_key: task}
        return {}

    # ── 结果格式化 ────────────────────────────────────

    def _format_result(self, result: Any) -> str:
        if isinstance(result, str):
            return result
        if isinstance(result, dict):
            return json.dumps(result, ensure_ascii=False, indent=2)
        return str(result)
