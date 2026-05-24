"""
CompositeSkill - 复合技能基类
LLM 一次规划，系统批量执行子技能。

用户只需在 SKILL.md 中声明 sub_skills 列表，LLM 自行决定：
  - 调用哪些子技能、按什么顺序
  - 每步传什么参数
  - 如何从中间结果推导后续参数

执行流程（仅 2 次 LLM 调用）：
  1. LLM 规划 → 返回执行计划（steps 列表）
  2. 系统按计划批量执行子技能
  3. LLM 整合所有结果 → 返回最终答案
"""

import json
import re
import logging
from datetime import date
from typing import Any, Dict, List, Optional

from core.base_skill import BaseSkill

logger = logging.getLogger("industrial_agent.composite_skill")


class CompositeSkill(BaseSkill):
    """
    复合技能 — LLM 规划 + 系统批量执行。

    SKILL.md 中通过 sub_skills 声明可用子技能：
        sub_skills:
          - time_query
          - weather_map
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._name = (config or {}).get("name", "composite_skill")
        self._description = (config or {}).get("description", "复合技能")
        self._sub_skills: List[str] = (config or {}).get("sub_skills", [])
        self._skill_loader = (config or {}).get("_skill_loader")
        self._llm = (config or {}).get("_llm")

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
        """
        执行流程：
        1. LLM 一次性规划所有步骤
        2. 系统按计划依次执行子技能
        3. LLM 整合结果给出最终答案
        """
        llm = self._resolve_llm(context)
        if not llm:
            return "复合技能需要 LLM 支持，请确保已配置语言模型"

        if not self._sub_skills:
            return "复合技能未配置子技能列表"

        sub_skills_info = self._collect_sub_skills_info()
        if not sub_skills_info:
            return "无法加载任何子技能"

        from llm.llm import Message

        # ── 第 1 步：LLM 规划执行计划 ──
        plan_prompt = self._build_plan_prompt(task, sub_skills_info)
        plan_response = await llm.chat([Message(role="user", content=plan_prompt)])
        plan = self._parse_plan(plan_response.content)

        if not plan:
            return plan_response.content

        logger.info("复合技能执行计划：%s", json.dumps(plan, ensure_ascii=False))

        # ── 第 2 步：按计划批量执行子技能 ──
        results: List[Dict[str, Any]] = []
        for step in plan:
            skill_name = step.get("skill", "")
            args = step.get("args", {})
            desc = step.get("description", skill_name)

            sub_skill = self._load_sub_skill(skill_name)
            if not sub_skill:
                results.append({"step": desc, "skill": skill_name, "error": f"子技能加载失败"})
                continue

            sub_result = await self._execute_sub_skill(
                sub_skill, task, context, messages, args
            )
            results.append({
                "step": desc,
                "skill": skill_name,
                "args": args,
                "result": sub_result if len(str(sub_result)) < 2000 else str(sub_result)[:2000],
            })

        logger.info("子技能执行完毕，共 %d 步", len(results))

        # ── 第 3 步：LLM 整合结果 ──
        answer_prompt = self._build_answer_prompt(task, results)
        answer_response = await llm.chat([Message(role="user", content=answer_prompt)])
        return answer_response.content

    # ── 子技能执行 ─────────────────────────────────────

    def _load_sub_skill(self, skill_name: str) -> Optional[BaseSkill]:
        if not self._skill_loader:
            return None
        return self._skill_loader.load_skill_full(skill_name)

    def _collect_sub_skills_info(self) -> List[Dict[str, Any]]:
        info = []
        for skill_name in self._sub_skills:
            meta = self._skill_loader.get_metadata(skill_name) if self._skill_loader else None
            desc = meta.description if meta else ""
            tools = []
            inputs = {}

            skill = self._load_sub_skill(skill_name)
            if skill:
                if not desc:
                    desc = skill.description
                if hasattr(skill, "get_tools"):
                    tools = skill.get_tools()
                # 提取 HttpSkill / 配置模式技能的输入参数定义
                raw_inputs = getattr(skill, "_inputs", None)
                if raw_inputs:
                    inputs = {
                        k: {
                            "description": v.get("description", ""),
                            "required": v.get("required", False),
                            "default": v.get("default", ""),
                        }
                        for k, v in raw_inputs.items()
                    }

            entry: Dict[str, Any] = {"name": skill_name, "description": desc}
            if tools:
                entry["tools"] = [
                    {"name": t["name"], "description": t.get("description", "")}
                    for t in tools
                ]
            if inputs:
                entry["inputs"] = inputs
            info.append(entry)
        return info

    async def _execute_sub_skill(
        self,
        sub_skill: BaseSkill,
        task: str,
        parent_context: Any,
        messages: List[Dict[str, str]],
        args: Dict[str, Any],
    ) -> str:
        sub_context = self._build_sub_context(parent_context, args)
        logger.info("[CompositeSkill] 执行子技能: %s, 参数: %s", sub_skill.name, json.dumps(args, ensure_ascii=False, default=str))
        try:
            result = await sub_skill.execute(
                task=task, context=sub_context, messages=messages
            )
            logger.info("[CompositeSkill] 子技能 %s 执行结果（前1000字符）: %s", sub_skill.name, str(result)[:1000])
            return str(result)
        except Exception as e:
            logger.error("子技能 %s 执行失败: %s", sub_skill.name, e, exc_info=True)
            return f"执行失败: {e}"

    def _build_sub_context(self, parent_context: Any, args: Dict[str, Any]) -> Dict[str, Any]:
        sub_context: Dict[str, Any] = {}
        if hasattr(parent_context, "get"):
            llm = parent_context.get("_llm")
            if llm:
                sub_context["_llm"] = llm
        elif isinstance(parent_context, dict):
            if "_llm" in parent_context:
                sub_context["_llm"] = parent_context["_llm"]
        if args:
            sub_context["extracted_args"] = args
        return sub_context

    # ── Prompt 构建 ────────────────────────────────────

    def _build_plan_prompt(self, task: str, sub_skills_info: List[Dict[str, Any]]) -> str:
        skills_desc = "\n".join(self._format_skill_info(s) for s in sub_skills_info)
        return f"""你是一个任务编排助手。根据用户任务，制定一个执行计划。

## 用户任务
{task}

## 可用子技能
{skills_desc}

## 输出规则
输出一个 JSON 数组，每个元素代表一个执行步骤：
[{{"skill": "技能名", "args": {{"参数名": "参数值"}}, "description": "步骤说明"}}]

注意：
- args 中的参数值必须是具体的，不能是"从上一步获取"之类的描述
- 如果需要根据当前日期推算，请直接计算出具体日期
- 今天是 {date.today().strftime("%Y-%m-%d")}
- 只输出 JSON 数组，不要输出其他内容"""

    def _build_answer_prompt(self, task: str, results: List[Dict[str, Any]]) -> str:
        results_text = "\n".join(
            f"步骤{i+1} [{r['skill']}]: {r.get('result', r.get('error', '无结果'))}"
            for i, r in enumerate(results)
        )
        return f"""根据以下子技能的执行结果，回答用户的问题。

## 用户问题
{task}

## 执行结果
{results_text}

## 回答要求
1. 保留所有结果中的 URL 链接（如图片地址、文件链接），不要省略
2. 如果结果中包含色斑图、图表等可视化内容，请展示其 URL
3. 如果结果包含报告文本，请完整引用关键内容
4. 按子技能分别展示结果，结构清晰
5. 直接给出回答，不需要重复用户的问题"""

    def _format_skill_info(self, info: Dict[str, Any]) -> str:
        desc = info.get("description", "")
        tools = info.get("tools", [])
        inputs = info.get("inputs", {})
        lines = [f"- **{info['name']}**: {desc}"]
        if inputs:
            params = []
            for k, v in inputs.items():
                req = "必填" if v.get("required") else "可选"
                default = f"，默认={v['default']}" if v.get("default") else ""
                params.append(f"    - {k}: {v['description']}（{req}{default}）")
            lines.append("  参数：")
            lines.extend(params)
        if tools:
            for t in tools:
                lines.append(f"  - 工具 {t['name']}: {t['description']}")
        return "\n".join(lines)

    # ── 响应解析 ──────────────────────────────────────

    def _parse_plan(self, content: str) -> List[Dict[str, Any]]:
        """解析 LLM 返回的执行计划（JSON 数组）"""
        content = content.strip()

        # 直接解析
        try:
            result = json.loads(content)
            if isinstance(result, list):
                return result
            if isinstance(result, dict):
                return [result]
        except json.JSONDecodeError:
            pass

        # 从 markdown 代码块提取
        match = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", content, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        # 提取第一个 JSON 数组
        match = re.search(r"\[.*?\]", content, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

        return []

    # ── LLM 获取 ──────────────────────────────────────

    def _resolve_llm(self, context: Any) -> Any:
        if self._llm:
            return self._llm
        if hasattr(context, "get"):
            return context.get("_llm")
        if isinstance(context, dict):
            return context.get("_llm")
        return None
