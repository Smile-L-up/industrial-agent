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
        services_info = await self._collect_services_info()
        plan_prompt = self._build_plan_prompt(task, services_info)
        from llm.llm import Message
        plan_response = await llm.chat([Message(role="user", content=plan_prompt)])
        plan = self._parse_plan(plan_response.content)

        if not plan:
            return plan_response.content

        # 过滤掉不存在的服务名
        valid_names = {svc.get("name") for svc in self._services}
        plan = [s for s in plan if s.get("service", "") in valid_names]
        logger.info("多服务执行计划：%s", json.dumps(plan, ensure_ascii=False))

        if not plan:
            logger.warning("过滤后无有效服务调用，回退到 LLM 直接回答")
            from llm.llm import Message as _Msg
            fallback_resp = await llm.chat([_Msg(role="user", content=task)])
            return fallback_resp.content

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

    async def _collect_services_info(self) -> List[Dict[str, Any]]:
        """收集所有服务端点的描述和参数信息，MCP 服务自动查询参数 schema"""
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

            # MCP 服务：自动查询 tools/list 获取参数 schema
            if svc.get("service_type") == "mcp":
                try:
                    tools = await self._query_mcp_tools(svc)
                    if tools:
                        entry["mcp_tools"] = tools
                except Exception as e:
                    logger.warning("查询 MCP 工具列表失败 (%s): %s", svc.get("name"), e)

            info.append(entry)
        return info

    async def _query_mcp_tools(self, svc_config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """查询 MCP 服务的 tools/list，返回工具及其参数 schema"""
        import httpx

        endpoint = svc_config.get("endpoint", "")
        timeout = svc_config.get("timeout", 30)
        target_tool = svc_config.get("tool_name", "")

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
            logger.info("[MultiService] query_mcp_tools initialize 请求: %s", json.dumps(init_payload, ensure_ascii=False))
            await client.post(
                endpoint, json=init_payload,
                headers={"Content-Type": "application/json; charset=utf-8"},
            )
            await client.post(
                endpoint,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                headers={"Content-Type": "application/json; charset=utf-8"},
            )

            # tools/list
            list_payload = {"jsonrpc": "2.0", "method": "tools/list", "id": 2, "params": {}}
            logger.info("[MultiService] query_mcp_tools tools/list 请求: %s", json.dumps(list_payload, ensure_ascii=False))
            resp = await client.post(
                endpoint, json=list_payload,
                headers={"Content-Type": "application/json; charset=utf-8"},
            )
            logger.info("[MultiService] query_mcp_tools tools/list 响应内容（前2000字符）: %s", resp.text[:2000])
            all_tools = resp.json().get("result", {}).get("tools", [])

        # 如果指定了 tool_name，只保留匹配的
        if target_tool:
            all_tools = [t for t in all_tools if t.get("name") == target_tool]

        # 精简输出：只保留 name, description, inputSchema
        return [
            {
                "name": t.get("name", ""),
                "description": t.get("description", ""),
                "parameters": t.get("inputSchema", {}).get("properties", {}),
                "required": t.get("inputSchema", {}).get("required", []),
            }
            for t in all_tools
        ]

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
        logger.info("[MultiService] 请求头: %s", json.dumps(headers, ensure_ascii=False))
        logger.info("[MultiService] 请求体: %s", json.dumps(body, ensure_ascii=False, default=str)[:2000])

        async with httpx.AsyncClient(timeout=timeout) as client:
            kwargs = {"url": endpoint, "headers": headers}
            if method == "POST":
                kwargs["json"] = body
            elif method == "GET":
                kwargs["params"] = body if isinstance(body, dict) else {}

            resp = await client.request(method, **kwargs)

            logger.info("[MultiService] HTTP 响应内容（前2000字符）: %s", resp.text[:2000])

            if resp.status_code != 200:
                logger.error("[MultiService] HTTP 失败: %d %s", resp.status_code, resp.text[:500])
                return f"服务调用失败（HTTP {resp.status_code}）：{resp.text[:200]}"

            try:
                data = resp.json()
            except Exception:
                logger.info("[MultiService] 响应非 JSON，返回原始文本")
                return resp.text

            if response_path:
                extracted = self._extract_by_path(data, response_path)
                if extracted is not None:
                    logger.info("[MultiService] response_path '%s' 提取结果（前1000字符）: %s", response_path, str(extracted)[:1000])
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
            logger.info("[MultiService] MCP initialize 请求: %s", json.dumps(init_payload, ensure_ascii=False))
            init_resp = await client.post(
                endpoint, json=init_payload,
                headers={"Content-Type": "application/json; charset=utf-8"},
            )
            logger.info("[MultiService] MCP initialize 响应内容: %s", init_resp.text[:500])

            # initialized notification
            await client.post(
                endpoint,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                headers={"Content-Type": "application/json; charset=utf-8"},
            )
            logger.info("[MultiService] MCP notifications/initialized 已发送")

            # 获取工具列表（用于自动选择 + 参数校验）
            list_payload = {"jsonrpc": "2.0", "method": "tools/list", "id": 2, "params": {}}
            logger.info("[MultiService] MCP tools/list 请求: %s", json.dumps(list_payload, ensure_ascii=False))
            resp = await client.post(
                endpoint, json=list_payload,
                headers={"Content-Type": "application/json; charset=utf-8"},
            )
            logger.info("[MultiService] MCP tools/list 响应内容（前2000字符）: %s", resp.text[:2000])
            tools = resp.json().get("result", {}).get("tools", [])

            if not tool_name and tools:
                tool_name = tools[0]["name"]

            if not tool_name:
                return "MCP 服务未暴露任何工具"

            # 参数校验：对比 MCP tool schema 中的 required 字段与实际 args
            tool_schema = next((t for t in tools if t.get("name") == tool_name), None)
            if tool_schema:
                input_schema = tool_schema.get("inputSchema", {})
                required_params = input_schema.get("required", [])
                param_properties = input_schema.get("properties", {})
                missing = [
                    p for p in required_params
                    if p not in args or args[p] in (None, "", [])
                ]
                if missing:
                    descs = []
                    for p in missing:
                        prop = param_properties.get(p, {})
                        desc = prop.get("description", p) if isinstance(prop, dict) else p
                        descs.append(desc)
                    svc_name = svc_config.get("name", tool_name)
                    logger.warning("[MultiService] MCP 服务 %s 缺少必填参数: %s", svc_name, missing)
                    return (
                        f"【需要补充信息】服务「{svc_name}」调用工具「{tool_name}」时缺少必填参数，"
                        f"需要用户提供以下信息：{', '.join(descs)}。"
                        f"请向用户询问这些信息。"
                    )

            # 调用工具
            call_payload = {
                "jsonrpc": "2.0", "method": "tools/call", "id": 3,
                "params": {"name": tool_name, "arguments": args},
            }
            logger.info("[MultiService] MCP tools/call 请求: %s", json.dumps(call_payload, ensure_ascii=False, default=str)[:2000])
            resp = await client.post(
                endpoint, json=call_payload,
                headers={"Content-Type": "application/json; charset=utf-8"},
            )
            logger.info("[MultiService] MCP tools/call 响应内容（前2000字符）: %s", resp.text[:2000])
            data = resp.json()

            result = data.get("result", {})
            if result.get("isError"):
                contents = result.get("content", [])
                error_text = " ".join(c.get("text", "") for c in contents if c.get("type") == "text")
                logger.error("[MultiService] MCP 工具执行失败: %s", error_text)
                return f"MCP 工具执行失败: {error_text}"

            extracted = self._extract_mcp_content(result)
            logger.info("[MultiService] MCP 提取结果（前1000字符）: %s", str(extracted)[:1000])
            return extracted

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
- service 字段只能填上述"可用服务"中列出的服务名，禁止使用其他名称
- 只选择与用户任务相关的服务，不要全部调用
- args 中的参数值必须是具体的，不能是描述性文字
- **重要：如果用户没有提供某个必填参数的信息，该参数值必须留空字符串 ""，不要猜测或编造，系统会自动向用户追问**
- 严格按照"技能详细说明"中的参数填写规则来生成 args
- 如果需要根据当前日期推算，请直接计算出具体日期
- 今天是 {date.today().strftime("%Y-%m-%d")}
- 只输出 JSON 数组，不要输出其他内容"""

    def _build_answer_prompt(self, task: str, results: List[Dict[str, Any]]) -> str:
        results_text = "\n".join(
            f"步骤{i+1} [{r['service']}]: {r.get('result', r.get('error', '无结果'))}"
            for i, r in enumerate(results)
        )
        raw_content = self._config.get("raw_content", "")
        context_section = f"\n## 技能说明\n{raw_content}\n" if raw_content else ""
        return f"""根据以下服务的执行结果，回答用户的问题。
{context_section}
## 用户问题
{task}

## 执行结果
{results_text}

## 回答要求
1. **优先检查**：如果执行结果中包含"需要补充信息"或"缺少必填参数"，说明用户提供的信息不足，请直接、友好地向用户询问缺失的信息，不要尝试编造数据或跳过。
2. 保留所有结果中的 URL 链接（如图片地址、文件链接），不要省略
3. 如果结果中包含色斑图、图表等可视化内容，请展示其 URL
4. 如果结果包含报告文本，请完整引用关键内容
5. 按服务分别展示结果，结构清晰
6. 直接给出回答，不需要重复用户的问题"""

    def _format_service_info(self, info: Dict[str, Any]) -> str:
        desc = info.get("description", "")
        svc_type = info.get("service_type", "http")
        inputs = info.get("inputs", {})
        mcp_tools = info.get("mcp_tools", [])
        lines = [f"- **{info['name']}**（{svc_type}）: {desc}"]
        if inputs:
            params = []
            for k, v in inputs.items():
                req = "必填" if v.get("required") else "可选"
                default = f"，默认={v['default']}" if v.get("default") else ""
                params.append(f"    - {k}: {v['description']}（{req}{default}）")
            lines.append("  参数：")
            lines.extend(params)
        if mcp_tools:
            for tool in mcp_tools:
                tool_name = tool.get("name", "")
                tool_desc = tool.get("description", "")
                required = tool.get("required", [])
                params = tool.get("parameters", {})
                lines.append(f"  MCP 工具: {tool_name}")
                if tool_desc:
                    lines.append(f"  说明: {tool_desc}")
                if params:
                    lines.append("  参数：")
                    for pname, pinfo in params.items():
                        p_desc = pinfo.get("description", "") if isinstance(pinfo, dict) else str(pinfo)
                        p_type = pinfo.get("type", "") if isinstance(pinfo, dict) else ""
                        req = "必填" if pname in required else "可选"
                        type_str = f"，类型={p_type}" if p_type else ""
                        lines.append(f"    - {pname}: {p_desc}（{req}{type_str}）")
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
