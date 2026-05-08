"""
Time Query Skill - 时间查询技能
提供当前时间查询服务
"""

from typing import Dict, List, Any, Optional
from datetime import datetime


class Skill:
    """时间查询技能类"""
    
    def __init__(self, config: Dict[str, Any]):
        """
        初始化技能
        
        Args:
            config: 技能配置
        """
        self.config = config
        self.name = config.get("name", "time_query")
        self.description = config.get("description", "提供当前时间查询服务")
        
        # 定义可用的子工具列表
        self._tools = [
            {
                "name": "get_current_time",
                "description": "获取当前的日期和时间",
                "method": "get_current_time",
                "parameters": {}
            }
        ]
    
    def get_tools(self) -> List[Dict[str, Any]]:
        """
        获取技能包含的工具列表
        
        Returns:
            工具列表
        """
        return self._tools
    
    async def execute(
        self,
        task: str,
        context: Dict[str, Any],
        messages: List[Dict[str, str]]
    ) -> str:
        """
        执行技能
        
        Args:
            task: 任务描述
            context: 上下文
            messages: 消息历史
            
        Returns:
            执行结果
        """
        return await self.get_current_time()
    
    async def get_current_time(self) -> str:
        """
        获取当前时间
        
        Returns:
            当前时间字符串
        """
        now = datetime.now()
        
        # 获取星期信息
        weekday_map = {
            0: "星期一",
            1: "星期二",
            2: "星期三",
            3: "星期四",
            4: "星期五",
            5: "星期六",
            6: "星期日"
        }
        weekday = weekday_map[now.weekday()]
        
        # 判断上午/下午
        hour = now.hour
        if hour < 6:
            period = "凌晨"
        elif hour < 12:
            period = "上午"
        elif hour < 14:
            period = "中午"
        elif hour < 18:
            period = "下午"
        else:
            period = "晚上"
        
        # 使用12小时制格式化时间
        hour_12 = hour % 12
        if hour_12 == 0:
            hour_12 = 12
        
        time_str = f"{now.year} 年 {now.month} 月 {now.day} 日 {period}{hour_12} 点 {now.minute:02d} 分 {now.second:02d} 秒"
        
        return f"当前时间是：{time_str}，{weekday}"


# 便捷函数
async def execute(
    task: str,
    context: Dict[str, Any],
    messages: List[Dict[str, str]]
) -> str:
    """便捷执行函数"""
    skill = Skill({"name": "time_query"})
    return await skill.execute(task, context, messages)