"""
MultiServiceSkill - 多服务端点技能
一个 SKILL.md 中声明多个服务端点，LLM 规划调用哪些、传什么参数。

与 CompositeSkill 的区别：
  - CompositeSkill: 子技能是独立的 skill 目录，可被其他组合复用
  - MultiServiceSkill: 服务端点在同一个 SKILL.md 里声明，强内聚

执行流程（2 次 LLM 调用）：
  1. LLM 规划 → 选择要调用的 services + 参数
  2. 系统按计划执行各服务
  3. LLM 整合所有结果 → 返回最终答案
"""

import json
import os
import re
import logging
from datetime import date
from typing import Any, Dict, List, Optional

from core.base_skill import BaseSkill

logger = logging.getLogger("industrial_agent.multi_service_skill")


class MultiServiceSkill(BaseSkill):
    """
    多服务端点技能 — 一个技能内声明多个服务，LLM 规划执行。

    SKILL.md 中通过 services 声明多个端点：
        services:
          - name: map
            description: 生成色斑图
            service_type: dify
            endpoint: http://...
          - name: report
            description: 生成报告
            service_type: mcp
            endpoint: http://...
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._name = (config or {}).get("name", "multi_service_skill")
        self._description = (config or {}).get("description", "多服务技能")
        self._services: List[Dict[str, Any]] = (config or {}).get("services", [])
        self._llm = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    async def execute(
        self,
        task: str,
        context: Dict[str, Any],
        messages: List[Dict[str, str]],
    ) -> str:
        llm = self._resolve_llm(context)
        if not llm:
            return "多服务技能需要 LLM 支持，请确保已配置语言模型"

        if not self._services:
            return "技能未配置任何服务端点"

        # ── 第 1 步：LLM 规划 ──
        services_info = self._collect_services_info()
        plan_prompt = self._build_plan_prompt(task, services_info)
        from llm.llm import Message
        plan_response = await llm.chat([Message(role="user", content=plan_prompt)])
        plan = self._parse_plan(plan_response.content)

        if not plan:
            return plan_response.content

        logger.info("多服务执行计划：%s", json.dumps(plan, ensure_ascii=False))

        # ── 第 2 步：按计划执行各服务 ──
        results: List[Dict[str, Any]] = []
        for step in plan:
            service_name = step.get("service", "")
            args = step.get("args", {})
            desc = step.get("description", service_name)

            svc_config = self._find_service(service_name)
            if not svc_config:
                results.append({"step": desc, "service": service_name, "error": "服务不存在"})
                continue

            try:
                result = await self._execute_service(svc_config, args)
                results.append({
                    "step": desc,
                    "service": service_name,
                    "args": args,
                    "result": result if len(str(result)) < 2000 else str(result)[:2000],
                })
            except Exception as e:
                logger.error("服务 %s 执行失败: %s", service_name, e, exc_info=True)
                results.append({"step": desc, "service": service_name, "error": str(e)})

        logger.info("服务执行完毕，共 %d 步", len(results))

        # ── 第 3 步：LLM 整合结果 ──
        answer_prompt = self._build_answer_prompt(task, results)
        answer_response = await llm.chat([Message(role="user", content=answer_prompt)])
        return answer_response.content

    # ── 服务信息收集 ──────────────────────────────────

    def _collect_services_info(self) -> List[Dict[str, Any]]:
        """收集所有服务端点的描述和参数信息"""
        info = []
        for svc in self._services:
            entry: Dict[str, Any] = {
                "name": svc.get("name", ""),
                "description": svc.get("description", ""),
                "service_type": svc.get("service_type", "http"),
            }
            inputs = svc.get("inputs", {})
            if inputs:
                entry["inputs"] = {
                    k: {
                        "description": v.get("description", ""),
                        "required": v.get("required", False),
                        "default": v.get("default", ""),
                    }
                    for k, v in inputs.items()
                }
            info.append(entry)
        return info

    def _find_service(self, name: str) -> Optional[Dict[str, Any]]:
        """按名称查找服务配置"""
        for svc in self._services:
            if svc.get("name") == name:
                return svc
        return None

    # ── 服务执行 ─────────────────────────────────────

    async def _execute_service(
        self, svc_config: Dict[str, Any], args: Dict[str, Any]
    ) -> Any:
        """根据 service_type 分发执行"""
        service_type = svc_config.get("service_type", "http")
        inputs = svc_config.get("inputs", {})

        # 填充默认值
        for key, cfg in inputs.items():
            if key not in args and "default" in cfg:
                args[key] = cfg["default"]

        # 校验必填
        missing = [
            k for k, v in inputs.items()
            if v.get("required", False) and k not in args
        ]
        if missing:
            descs = [inputs[k].get("description", k) for k in missing]
            return f"缺少必填参数：{', '.join(descs)}"

        if service_type in ("http", "dify"):
            return await self._execute_http(svc_config, args)
        elif service_type == "mcp":
            return await self._execute_mcp(svc_config, args)
        else:
            return f"不支持的服务类型: {service_type}"

    async def _execute_http(
        self, svc_config: Dict[str, Any], args: Dict[str, Any]
    ) -> Any:
        """执行 HTTP/Dify 类型服务"""
        import httpx

        endpoint = svc_config.get("endpoint", "")
        method = svc_config.get("method", "POST").upper()
        timeout = svc_config.get("timeout", 120)
        body_template = svc_config.get("body_template")
        response_path = svc_config.get("response_path", "")

        # 构建请求头
        raw_headers = svc_config.get("headers", {})
        headers = {"Content-Type": "application/json; charset=utf-8"}
        for k, v in raw_headers.items():
            headers[k] = os.path.expandvars(v)

        # 构建请求体
        body = self._build_body(args, body_template)

        logger.info("[MultiService] HTTP %s %s", method, endpoint)
        logger.debug("[MultiService] 请求体: %s", json.dumps(body, ensure_ascii=False)[:500])

        async with httpx.AsyncClient(timeout=timeout) as client:
            kwargs = {"url": endpoint, "headers": headers}
            if method == "POST":
                kwargs["json"] = body
            elif method == "GET":
                kwargs["params"] = body if isinstance(body, dict) else {}

            resp = await client.request(method, **kwargs)

            if resp.status_code != 200:
                logger.error("[MultiService] HTTP 失败: %d %s", resp.status_code, resp.text[:300])
                return f"服务调用失败（HTTP {resp.status_code}）：{resp.text[:200]}"

            try:
                data = resp.json()
            except Exception:
                return resp.text

            if response_path:
                extracted = self._extract_by_path(data, response_path)
                if extracted is not None:
                    return extracted
                logger.warning("[MultiService] response_path '%s' 未匹配", response_path)

            return data

    async def _execute_mcp(
        self, svc_config: Dict[str, Any], args: Dict[str, Any]
    ) -> Any:
        """执行 MCP 类型服务"""
        import httpx

        endpoint = svc_config.get("endpoint", "")
        timeout = svc_config.get("timeout", 120)
        tool_name = svc_config.get("tool_name", "")

        async with httpx.AsyncClient(timeout=timeout) as client:
            # MCP initialize
            init_payload = {
                "jsonrpc": "2.0", "method": "initialize", "id": 1,
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "industrial-agent", "version": "1.0.0"},
                },
            }
            await client.post(
                endpoint, json=init_payload,
                headers={"Content-Type": "application/json; charset=utf-8"},
            )

            # initialized notification
            await client.post(
                endpoint,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                headers={"Content-Type": "application/json; charset=utf-8"},
            )

            # 如果没指定 tool_name，先列出工具取第一个
            if not tool_name:
                list_payload = {"jsonrpc": "2.0", "method": "tools/list", "id": 2, "params": {}}
                resp = await client.post(
                    endpoint, json=list_payload,
                    headers={"Content-Type": "application/json; charset=utf-8"},
                )
                tools = resp.json().get("result", {}).get("tools", [])
                if not tool_name and tools:
                    tool_name = tools[0]["name"]

            if not tool_name:
                return "MCP 服务未暴露任何工具"

            # 调用工具
            call_payload = {
                "jsonrpc": "2.0", "method": "tools/call", "id": 3,
                "params": {"name": tool_name, "arguments": args},
            }
            logger.info("[MultiService] MCP 调用 %s, 参数: %s", tool_name, args)
            resp = await client.post(
                endpoint, json=call_payload,
                headers={"Content-Type": "application/json; charset=utf-8"},
            )
            data = resp.json()

            result = data.get("result", {})
            if result.get("isError"):
                contents = result.get("content", [])
                error_text = " ".join(c.get("text", "") for c in contents if c.get("type") == "text")
                return f"MCP 工具执行失败: {error_text}"

            return self._extract_mcp_content(result)

    # ── 辅助方法 ─────────────────────────────────────

    def _build_body(self, params: Dict[str, Any], body_template: Any) -> Any:
        """根据 body_template 和参数构建请求体"""
        if not body_template:
            return params

        def _fill(obj):
            if isinstance(obj, str):
                result = obj
                for k, v in params.items():
                    result = result.replace(f"{{{k}}}", str(v))
                try:
                    return json.loads(result)
                except (json.JSONDecodeError, ValueError):
                    return result
            elif isinstance(obj, dict):
                return {k: _fill(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [_fill(item) for item in obj]
            return obj

        return _fill(body_template)

    def _extract_by_path(self, data: Any, path: str) -> Any:
        """按点分路径提取嵌套字段"""
        current = data
        for key in path.split("."):
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return None
        return current

    def _extract_mcp_content(self, result: Dict[str, Any]) -> Any:
        """从 MCP 响应中提取内容"""
        contents = result.get("content", [])
        if not contents:
            return ""
        if len(contents) == 1 and contents[0].get("type") == "text":
            text = contents[0]["text"]
            try:
                return json.loads(text)
            except (json.JSONDecodeError, ValueError):
                return text
        parts = [c["text"] for c in contents if c.get("type") == "text"]
        return "\n".join(parts)

    # ── Prompt 构建 ──────────────────────────────────

    def _build_plan_prompt(self, task: str, services_info: List[Dict[str, Any]]) -> str:
        services_desc = "\n".join(self._format_service_info(s) for s in services_info)
        return f"""你是一个任务编排助手。根据用户任务，从可用服务中选择需要调用的服务。

## 用户任务
{task}

## 可用服务
{services_desc}

## 输出规则
输出一个 JSON 数组，每个元素代表一个服务调用：
[{{"service": "服务名", "args": {{"参数名": "参数值"}}, "description": "步骤说明"}}]

注意：
- 只选择与用户任务相关的服务，不要全部调用
- args 中的参数值必须是具体的，不能是描述性文字
- 如果需要根据当前日期推算，请直接计算出具体日期
- 今天是 {date.today().strftime("%Y-%m-%d")}
- 只输出 JSON 数组，不要输出其他内容"""

    def _build_answer_prompt(self, task: str, results: List[Dict[str, Any]]) -> str:
        results_text = "\n".join(
            f"步骤{i+1} [{r['service']}]: {r.get('result', r.get('error', '无结果'))}"
            for i, r in enumerate(results)
        )
        return f"""根据以下服务的执行结果，回答用户的问题。

## 用户问题
{task}

## 执行结果
{results_text}

## 回答要求
1. 保留所有结果中的 URL 链接（如图片地址、文件链接），不要省略
2. 如果结果中包含色斑图、图表等可视化内容，请展示其 URL
3. 如果结果包含报告文本，请完整引用关键内容
4. 按服务分别展示结果，结构清晰
5. 直接给出回答，不需要重复用户的问题"""

    def _format_service_info(self, info: Dict[str, Any]) -> str:
        desc = info.get("description", "")
        svc_type = info.get("service_type", "http")
        inputs = info.get("inputs", {})
        lines = [f"- **{info['name']}**（{svc_type}）: {desc}"]
        if inputs:
            params = []
            for k, v in inputs.items():
                req = "必填" if v.get("required") else "可选"
                default = f"，默认={v['default']}" if v.get("default") else ""
                params.append(f"    - {k}: {v['description']}（{req}{default}）")
            lines.append("  参数：")
            lines.extend(params)
        return "\n".join(lines)

    # ── 响应解析 ─────────────────────────────────────

    def _parse_plan(self, content: str) -> List[Dict[str, Any]]:
        """解析 LLM 返回的执行计划（JSON 数组）"""
        content = content.strip()

        try:
            result = json.loads(content)
            if isinstance(result, list):
                return result
            if isinstance(result, dict):
                return [result]
        except json.JSONDecodeError:
            pass

        match = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", content, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        match = re.search(r"\[.*?\]", content, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

        return []

    # ── LLM 获取 ─────────────────────────────────────

    def _resolve_llm(self, context: Any) -> Any:
        if self._llm:
            return self._llm
        if hasattr(context, "get"):
            return context.get("_llm")
        if isinstance(context, dict):
            return context.get("_llm")
        return None
