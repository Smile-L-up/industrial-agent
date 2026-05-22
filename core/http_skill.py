"""
HttpSkill - 通用 HTTP 服务技能
根据 SKILL.md 中的配置调用外部 HTTP 服务（如 Dify 工作流）
用户只需编写 SKILL.md，无需写 Python 代码
"""

import os
import json
import logging
import re
from typing import Dict, List, Any, Optional

from core.base_skill import BaseSkill

logger = logging.getLogger("industrial_agent.http_skill")


class HttpSkill(BaseSkill):
    """通用 HTTP 服务技能 — 配置驱动，无需编写代码"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._name = config.get("name", "http_skill")
        self._description = config.get("description", "HTTP 服务技能")
        self._keywords: List[str] = config.get("keywords", [])

        # HTTP 服务配置
        service = config.get("service", {})
        # 兼容两种字段名：service_type 和 type
        self._service_type = service.get("service_type") or service.get("type", "http")
        self._endpoint = service.get("endpoint", "")
        self._method = service.get("method", "POST").upper()
        self._timeout = service.get("timeout", 120)
        self._inputs = service.get("inputs", {})
        self._body_template = service.get("body_template", {})
        self._response_path = service.get("response_path", "")
        # Dify 智能体端点默认提取 answer 字段
        if not self._response_path and self._service_type == "dify" and "chat-messages" in self._endpoint:
            self._response_path = "answer"

        # 请求头（支持环境变量替换）
        self._headers = self._resolve_headers(service.get("headers", {}))

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
        # HttpSkill 不声明子工具，路由由 Router 基于 SKILL.md 元数据完成，
        # 执行直接走 execute()，不需要 executor 的子工具选择机制。
        return []

    # ── 核心执行 ──────────────────────────────────────

    async def execute(
        self,
        task: str,
        context: Dict[str, Any],
        messages: List[Dict[str, str]],
    ) -> str:
        logger.info("[HttpSkill] 开始执行：%s → %s", self._name, self._endpoint)

        # 1. 优先使用 executor 层预提取的参数（LLM tool calling 结果）
        params = self._get_extracted_args(context)
        logger.info("[HttpSkill] executor 预提取参数：%s", params)

        # 2. 如果 executor 没有预提取，HttpSkill 自行提取
        if not params:
            if self._llm is None and hasattr(context, "extra"):
                self._llm = context.extra.get("_llm")
            params = await self._extract_params(task, messages)

        # 2. 填充默认值
        for key, cfg in self._inputs.items():
            if key not in params and "default" in cfg:
                params[key] = cfg["default"]

        # 3. 校验必填参数，缺的则向用户追问
        missing = [
            k
            for k, v in self._inputs.items()
            if v.get("required", True) and k not in params
        ]
        if missing:
            return self._build_missing_params_question(missing)

        # 4. 构建请求体、调用、返回
        body = self._build_body(params)
        logger.info("[HttpSkill] 最终参数：%s", params)
        logger.info("[HttpSkill] 请求体：%s", json.dumps(body, ensure_ascii=False)[:500])
        result = await self._call_service(body)
        logger.info("[HttpSkill] 响应结果（前200字符）：%s", str(result)[:200])
        return self._format_result(result)

    # ── 参数提取 ──────────────────────────────────────

    def _get_extracted_args(self, context: Any) -> Dict[str, Any]:
        """从 context 中读取 executor 预提取的参数"""
        if hasattr(context, "get"):
            return context.get("extracted_args", {})
        if hasattr(context, "extra"):
            return context.extra.get("extracted_args", {})
        return {}

    async def _extract_params(
        self, task: str, messages: Optional[List[Dict[str, str]]] = None
    ) -> Dict[str, Any]:
        """从对话历史中提取参数，支持多轮对话逐步补充"""
        if not self._inputs:
            return {}

        # 尝试 LLM 提取（传入完整对话历史）
        if self._llm:
            try:
                return await self._extract_params_with_llm(task, messages)
            except Exception as e:
                logger.warning("LLM 参数提取失败，回退到正则：%s", e)

        return self._extract_params_with_regex(task)

    async def _extract_params_with_llm(
        self, task: str, messages: Optional[List[Dict[str, str]]] = None
    ) -> Dict[str, Any]:
        """用 LLM 从对话历史中提取结构化参数（支持多轮补充）"""
        from llm.llm import Message

        param_lines = []
        for name, cfg in self._inputs.items():
            desc = cfg.get("description", cfg.get("type", "string"))
            default = cfg.get("default", "")
            if default:
                param_lines.append(f"  - {name}: {desc}（默认值：{default}）")
            else:
                param_lines.append(f"  - {name}: {desc}")
        params_desc = "\n".join(param_lines)

        # 构建对话上下文
        conversation = ""
        if messages:
            for msg in messages[-6:]:  # 最近 6 条消息
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if isinstance(content, str):
                    conversation += f"{role}: {content}\n"
        else:
            conversation = f"user: {task}\n"

        prompt = f"""从以下对话中提取参数值，返回 JSON 对象。
只返回 JSON，不要其他文字。如果某个参数在对话中未提及，不要包含它。
请综合所有对话轮次的信息，不要遗漏之前已经提供的参数。

参数说明：
{params_desc}

对话记录：
{conversation}
提取结果（JSON）："""

        response = await self._llm.chat([Message(role="user", content=prompt)])
        text = response.content.strip()

        # 清除 markdown 代码块标记
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

        return json.loads(text)

    def _build_missing_params_question(self, missing_keys: List[str]) -> str:
        """构建参数追问消息，引导用户提供缺失信息"""
        lines = []
        for key in missing_keys:
            cfg = self._inputs.get(key, {})
            desc = cfg.get("description", key)
            lines.append(f"- {desc}")
        params_list = "\n".join(lines)
        return f"我还需要以下信息才能完成操作，请提供：\n{params_list}"

    def _extract_params_with_regex(self, task: str) -> Dict[str, Any]:
        """回退：用正则从用户输入中提取参数（简单匹配）"""
        params: Dict[str, Any] = {}

        # 尝试提取日期
        dates = re.findall(r"\d{4}-\d{2}-\d{2}", task)
        date_keys = [
            k for k, v in self._inputs.items() if v.get("type") == "date"
        ]
        for i, key in enumerate(date_keys):
            if i < len(dates):
                params[key] = dates[i]

        # 尝试提取引号中的字符串
        quoted = re.findall(r'[""「」]([^""「」]+)[""「」]', task)

        return params

    # ── HTTP 请求 ─────────────────────────────────────

    def _resolve_headers(self, headers: Dict[str, str]) -> Dict[str, str]:
        """解析请求头，支持环境变量 ${VAR}"""
        resolved = {"Content-Type": "application/json; charset=utf-8"}
        for k, v in headers.items():
            resolved[k] = os.path.expandvars(v)
        return resolved

    def _build_body(self, params: Dict[str, Any]) -> Any:
        """根据 body_template 和参数构建请求体"""
        if not self._body_template:
            # Dify 智能体端点（chat-messages）自动构建标准请求体
            if self._service_type == "dify" and "chat-messages" in self._endpoint:
                query = params.get("query", "")
                if not query and params:
                    query = next(iter(params.values()), "")
                return {
                    "inputs": {},
                    "query": str(query),
                    "response_mode": "blocking",
                    "conversation_id": "",
                    "user": "agent-user",
                }
            return params

        def _fill(obj):
            if isinstance(obj, str):
                # 替换 {param} 占位符
                result = obj
                for k, v in params.items():
                    result = result.replace(f"{{{k}}}", str(v))
                # 尝试解析为 JSON（处理数字、布尔等）
                try:
                    return json.loads(result)
                except (json.JSONDecodeError, ValueError):
                    return result
            elif isinstance(obj, dict):
                return {k: _fill(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [_fill(item) for item in obj]
            return obj

        return _fill(self._body_template)

    async def _call_service(self, body: Any) -> Any:
        """发送 HTTP 请求并返回解析后的结果"""
        import httpx

        logger.info("调用 HTTP 服务 [%s] %s", self._method, self._endpoint)
        logger.debug("请求体：%s", json.dumps(body, ensure_ascii=False)[:500])

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            kwargs = {
                "url": self._endpoint,
                "headers": self._headers,
            }
            if self._method == "POST":
                kwargs["json"] = body
            elif self._method == "GET":
                kwargs["params"] = body if isinstance(body, dict) else {}

            resp = await client.request(self._method, **kwargs)

            if resp.status_code != 200:
                logger.error("HTTP 请求失败：%d %s", resp.status_code, resp.text[:300])
                return f"服务调用失败（HTTP {resp.status_code}）：{resp.text[:200]}"

            try:
                data = resp.json()
            except Exception:
                return resp.text

            # 按 response_path 提取结果
            if self._response_path:
                extracted = self._extract_by_path(data, self._response_path)
                if extracted is not None:
                    return extracted
                logger.warning(
                    "response_path '%s' 未匹配，返回完整响应",
                    self._response_path,
                )

            return data

    def _extract_by_path(self, data: Any, path: str) -> Any:
        """按点分路径提取嵌套字段，如 'data.outputs.result'"""
        current = data
        for key in path.split("."):
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return None
        return current

    # ── 结果格式化 ────────────────────────────────────

    def _format_result(self, result: Any) -> str:
        if isinstance(result, str):
            return result
        if isinstance(result, dict):
            # 检查是否有 Dify 风格的错误
            if result.get("status") == "failed":
                error = result.get("error", "未知错误")
                return f"工作流执行失败：{error}"
            return json.dumps(result, ensure_ascii=False, indent=2)
        return str(result)
