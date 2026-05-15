"""
Calculator Skill - 计算器技能
提供数学计算功能，支持加减乘除四则运算
"""

import re
from typing import Dict, List, Any, Optional

from core.base_skill import BaseSkill


class Skill(BaseSkill):
    """计算器技能类"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._name = (config or {}).get("name", "calculator")
        self._description = (config or {}).get("description", "提供数学计算功能，支持加减乘除四则运算")
        self._keywords: List[str] = (config or {}).get("keywords", [
            "计算", "加", "减", "乘", "除", "等于", "多少", "算"
        ])

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def match_keywords(self) -> List[str]:
        return self._keywords

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "calculate",
                "description": "执行数学计算，支持加减乘除和括号",
                "parameters": {"expression": "数学表达式，如 1+2, 10*3-5"}
            }
        ]

    async def execute(
        self,
        task: str,
        context: Dict[str, Any],
        messages: List[Dict[str, str]]
    ) -> str:
        expression = self._extract_expression(task)
        if not expression:
            return "未能从输入中提取到数学表达式，请提供如 '1+2' 或 '10*3-5' 这样的表达式。"

        result = self._safe_eval(expression)
        if result is None:
            return f"无法计算表达式：{expression}"

        # 格式化结果（整数不显示小数点）
        if isinstance(result, float) and result == int(result):
            result = int(result)

        return f"{expression} = {result}"

    async def calculate(self, expression: str = "", **kwargs) -> Dict[str, Any]:
        """执行数学计算"""
        expr = expression or kwargs.get("expression", "")
        if not expr:
            return {"success": False, "error": "未提供表达式"}

        result = self._safe_eval(expr)
        if result is None:
            return {"success": False, "error": f"无法计算：{expr}"}

        if isinstance(result, float) and result == int(result):
            result = int(result)

        return {
            "success": True,
            "expression": expr,
            "result": result
        }

    def _extract_expression(self, text: str) -> Optional[str]:
        """从用户输入中提取数学表达式"""
        # 移除常见中文词汇
        text = text.strip()
        replacements = {
            "加": "+", "减": "-", "乘": "*", "除以": "/", "除": "/",
            "等于": "=", "是多少": "", "多少": "", "计算": "", "算一下": "",
            "算算": "", "请问": "", "帮我": "", "求": "",
        }
        expr = text
        for cn, en in replacements.items():
            expr = expr.replace(cn, en)

        # 尝试匹配数学表达式
        # 匹配数字、运算符、括号、小数点、空格
        pattern = r'[\d\.\+\-\*\/\(\)\s]+'
        matches = re.findall(pattern, expr)
        if matches:
            # 取最长的匹配
            expr = max(matches, key=len).strip()
            # 验证表达式是否包含至少一个运算符
            if re.search(r'[\+\-\*\/]', expr):
                return expr

        # 尝试直接从原始文本中提取
        matches = re.findall(pattern, text)
        if matches:
            expr = max(matches, key=len).strip()
            if re.search(r'[\+\-\*\/]', expr):
                return expr

        return None

    def _safe_eval(self, expression: str) -> Optional[float]:
        """
        安全计算数学表达式
        只允许数字、运算符、括号、空格、小数点
        """
        # 清理表达式
        expression = expression.strip()
        expression = expression.replace("×", "*").replace("÷", "/")

        # 验证只包含安全字符
        if not re.match(r'^[\d\.\+\-\*\/\(\)\s]+$', expression):
            return None

        # 检查括号匹配
        if expression.count("(") != expression.count(")"):
            return None

        try:
            # 使用 compile + eval 限制可用函数
            code = compile(expression, "<calc>", "eval")
            # 禁止访问任何属性或调用任何函数
            result = eval(code, {"__builtins__": {}}, {})
            return float(result)
        except (ZeroDivisionError, ValueError, SyntaxError, TypeError):
            return None
