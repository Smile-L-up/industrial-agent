"""
Time Query Skill - 时间查询技能
提供当前时间查询服务
"""

from typing import Dict, List, Any, Optional
from datetime import datetime, timezone, timedelta

from core.base_skill import BaseSkill


class Skill(BaseSkill):
    """时间查询技能类"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        初始化技能

        Args:
            config: 技能配置（来自 SKILL.md 的 YAML front matter）
        """
        super().__init__(config)
        self._name = (config or {}).get("name", "time_query")
        self._description = (config or {}).get("description", "提供当前时间查询服务")
        self._keywords: List[str] = (config or {}).get("keywords", [
            "时间", "几点", "日期", "星期", "现在"
        ])

    # ── BaseSkill 必须实现的属性 ──────────────────────

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    # ── 路由辅助 ──────────────────────────────────────

    def match_keywords(self) -> List[str]:
        return self._keywords

    # ── 子工具声明 ────────────────────────────────────

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "get_current_time",
                "description": "获取当前的日期和时间",
                "parameters": {}
            }
        ]

    # ── 执行方法 ──────────────────────────────────────

    async def execute(
        self,
        task: str,
        context: Dict[str, Any],
        messages: List[Dict[str, str]]
    ) -> str:
        data = await self.get_current_time()
        return (
            f"当前时间：{data['year']}年{data['month']}月{data['day']}日 "
            f"{data['hour']}:{data['minute']:02d}:{data['second']:02d} "
            f"{data['weekday']}"
        )

    # ── 子工具实现 ────────────────────────────────────

    async def get_current_time(self) -> Dict[str, Any]:
        """获取当前时间（北京时间 UTC+8），返回结构化数据"""
        beijing_tz = timezone(timedelta(hours=8))
        now = datetime.now(beijing_tz)

        weekday_map = {
            0: "星期一",
            1: "星期二",
            2: "星期三",
            3: "星期四",
            4: "星期五",
            5: "星期六",
            6: "星期日"
        }
        print(f"当前时间：{now}，星期：{weekday_map[now.weekday()]}")
        return {
            "year": now.year,
            "month": now.month,
            "day": now.day,
            "hour": now.hour,
            "minute": now.minute,
            "second": now.second,
            "weekday": weekday_map[now.weekday()],
            "timestamp": now.isoformat(),
        }
