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

        # MCP 服务配置
        mcp = config.get("mcp", {})
        self._endpoint = mcp.get("endpoint", "")
        self._timeout = mcp.get("timeout", 120)

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

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            # 1. 初始化 MCP 连接
            await self._mcp_initialize(client)

            # 2. 获取工具列表
            tools = await self._mcp_list_tools(client)
            if not tools:
                return "MCP 服务未暴露任何工具"

            self._tools_cache = tools

            # 3. 选择工具 + 提取参数
            tool_name, arguments = await self._resolve_tool_call(task, messages, tools)

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
        resp = await client.post(
            self._endpoint,
            json=payload,
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        resp.raise_for_status()

        # 发送 initialized 通知
        notification = {"jsonrpc": "2.0", "method": "notifications/initialized"}
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
        resp = await client.post(
            self._endpoint,
            json=payload,
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("result", {}).get("tools", [])

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
        logger.info("调用 MCP 工具: %s, 参数: %s", tool_name, arguments)
        resp = await client.post(
            self._endpoint,
            json=payload,
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        resp.raise_for_status()
        data = resp.json()

        result = data.get("result", {})
        if result.get("isError"):
            contents = result.get("content", [])
            error_text = " ".join(c.get("text", "") for c in contents if c.get("type") == "text")
            return f"MCP 工具执行失败: {error_text}"

        return self._extract_content(result)

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
    ) -> tuple:
        """
        选择要调用的 MCP 工具并提取参数。
        返回 (tool_name, arguments)
        """
        # 单工具场景：直接用，只提取参数
        if len(tools) == 1:
            tool = tools[0]
            tool_name = tool["name"]
            schema = tool.get("inputSchema", {})
            arguments = await self._extract_arguments(task, messages, schema)
            return tool_name, arguments

        # 多工具场景：先选工具，再提取参数
        tool_name = await self._select_tool(task, tools)
        selected = next((t for t in tools if t["name"] == tool_name), tools[0])
        schema = selected.get("inputSchema", {})
        arguments = await self._extract_arguments(task, messages, schema)
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
