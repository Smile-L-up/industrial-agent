---
name: weather_map_recent
description: "生成最近N天的气象色斑图（用户说'最近三天/近一周/近一个月'等相对时间时使用）"
type: composite

sub_skills:
  - time_query
  - weather_map
---

# 最近N天气象色斑图

## 功能描述
- 自动查询当前日期，推算"最近N天"的起止时间
- 调用 weather_map 技能生成对应时段的气象色斑图
- 支持"最近三天"、"近一周"、"近一个月"等相对时间表达

## 使用示例
- 福州市最近三天平均气温色斑图
- 厦门市近一周降水量色斑图
- 最近一个月最高温度色斑图
