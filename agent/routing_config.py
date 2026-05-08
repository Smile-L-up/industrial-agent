"""
Routing Config - 路由配置
将 Router 和 Executor 中硬编码的关键词/城市列表集中管理。
添加新技能时只需修改此文件，无需改动 Router 或 Executor 代码。
"""

from typing import Dict, List, Optional


# ── 技能路由关键词 ──────────────────────────────────
# key   = 技能名称（与 skill 目录名一致）
# value = 该技能关联的关键词列表（全部小写）

SKILL_KEYWORDS: Dict[str, List[str]] = {
    "weather_report": ["天气", "气温", "温度", "下雨", "晴天", "多云", "台风", "暴雨"],
    "time_query":     ["时间", "几点", "日期", "今天", "现在"],
    "knowledge_qa":   ["知识", "问答", "什么是", "解释"],
    "text_analysis":  ["分析", "统计", "文本"],
    "image_analysis": ["图片", "图像", "照片"],
}

# ── 城市别名映射 ─────────────────────────────────────
# 用于从用户输入中提取城市名。
# key   = 用户可能输入的短名称
# value = 标准城市名称

CITY_ALIASES: Dict[str, str] = {
    "北京":   "北京",
    "beijing": "北京",
    "bj":     "北京",
    "上海":   "上海",
    "shanghai": "上海",
    "sh":     "上海",
    "广州":   "广州",
    "guangzhou": "广州",
    "gz":     "广州",
    "深圳":   "深圳",
    "shenzhen": "深圳",
    "sz":     "深圳",
    "杭州":   "杭州",
    "hangzhou": "杭州",
    "hz":     "杭州",
    "成都":   "成都",
    "chengdu": "成都",
    "cd":     "成都",
    "武汉":   "武汉",
    "wuhan":  "武汉",
    "南京":   "南京",
    "nanjing": "南京",
    "nj":     "南京",
    "西安":   "西安",
    "xian":   "西安",
    "xa":     "西安",
    "重庆":   "重庆",
    "chongqing": "重庆",
    "cq":     "重庆",
    "天津":   "天津",
    "tianjin": "天津",
    "tj":     "天津",
    "苏州":   "苏州",
    "suzhou": "苏州",
    "sz2":    "苏州",
    "长沙":   "长沙",
    "changsha": "长沙",
    "cs":     "长沙",
    "郑州":   "郑州",
    "zhengzhou": "郑州",
    "zz":     "郑州",
    "厦门":   "厦门",
    "xiamen": "厦门",
    "xm":     "厦门",
}

# ── 获取所有已知城市名称（用于正则匹配） ────────────
KNOWN_CITIES: List[str] = list(set(CITY_ALIASES.values()))


def get_city_from_input(text: str) -> Optional[str]:
    """
    从用户输入中提取城市名称。
    优先精确匹配，再回退到子串包含。

    Args:
        text: 用户输入文本

    Returns:
        标准城市名称，未匹配则返回 None
    """
    text_lower = text.lower().strip()

    # 1. 精确匹配（别名 → 标准名）
    for alias, city in CITY_ALIASES.items():
        if alias in text_lower:
            return city

    # 2. 子串包含（针对标准中文名）
    for city in KNOWN_CITIES:
        if city in text:
            return city

    return None


def get_skill_keywords(skill_name: str) -> List[str]:
    """
    获取指定技能的路由关键词列表。

    Args:
        skill_name: 技能名称

    Returns:
        关键词列表，若技能未配置则返回空列表
    """
    return SKILL_KEYWORDS.get(skill_name, [])