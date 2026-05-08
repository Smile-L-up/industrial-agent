"""
BaseSkill - 技能抽象基类
定义所有技能必须实现的统一接口，替代 hasattr 检查的模式
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, AsyncGenerator


class BaseSkill(ABC):
    """技能抽象基类 — 所有技能必须继承此类"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        初始化技能

        Args:
            config: 技能配置（来自 SKILL.md 或 skill.json）
        """
        self._config = config or {}

    # ── 必须实现的属性 ──────────────────────────────

    @property
    @abstractmethod
    def name(self) -> str:
        """技能的唯一标识名"""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """技能描述（用于路由/展示）"""
        ...

    # ── 子工具声明（可选） ──────────────────────────

    def get_tools(self) -> List[Dict[str, Any]]:
        """
        返回该技能提供的子工具列表。
        子类可覆写此方法来声明子工具。

        Returns:
            子工具列表，每个元素形如：
            [
                {
                    "name": "tool_name",
                    "description": "工具描述",
                    "parameters": { ... }   # JSON Schema 可选
                }
            ]
        """
        return []

    # ── 路由辅助 ────────────────────────────────────

    def match_keywords(self) -> List[str]:
        """
        返回与该技能匹配的关键词列表，供 Router 做关键词路由。
        子类可覆写，按技能类型返回相关关键词。

        Returns:
            关键词列表，例如 ["天气", "气温", "预报"]
        """
        return []

    # ── 必须实现的执行方法 ──────────────────────────

    @abstractmethod
    async def execute(
        self,
        task: str,
        context: Dict[str, Any],
        messages: List[Dict[str, str]]
    ) -> str:
        """
        同步执行技能（非流式）

        Args:
            task: 任务描述
            context: 执行上下文
            messages: 对话历史

        Returns:
            执行结果文本
        """
        ...

    # ── 可选的流式执行 ──────────────────────────────

    async def execute_stream(
        self,
        task: str,
        context: Dict[str, Any],
        messages: List[Dict[str, str]]
    ) -> AsyncGenerator[str, None]:
        """
        流式执行技能（可选）。
        子类如需流式输出可覆写此方法。

        Args:
            task: 任务描述
            context: 执行上下文
            messages: 对话历史

        Yields:
            文本片段
        """
        # 默认实现：调用 execute 并一次性 yield
        result = await self.execute(task, context, messages)
        yield result

    # ── 工具调用辅助 ────────────────────────────────

    async def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        context: Dict[str, Any]
    ) -> Any:
        """
        调用技能内的子工具。子类可覆写以提供自定义分发逻辑。
        默认实现尝试调用 self.<tool_name> 方法。

        Args:
            tool_name: 子工具名称
            arguments: 子工具参数
            context: 执行上下文

        Returns:
            子工具返回结果

        Raises:
            AttributeError: 子工具不存在
            RuntimeError: 子工具执行失败
        """
        method = getattr(self, tool_name, None)
        if method is None or not callable(method):
            raise AttributeError(f"技能 {self.name} 没有子工具: {tool_name}")

        import asyncio
        if asyncio.iscoroutinefunction(method):
            return await method(**arguments)
        return method(**arguments)