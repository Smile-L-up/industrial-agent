---
name: weather_map
description: "生成气象色斑图（用户明确给出具体日期时使用，相对时间如'最近三天'请用 weather_map_recent）"

services:
  - name: map
    description: "生成气象色斑图（温度分布图、降水分布图）"
    service_type: dify
    endpoint: http://192.168.110.201:18080/v1/workflows/run
    method: POST
    headers:
      Authorization: "Bearer app-MJAlwJk6Hp428NTzt5EBxBVf"
    timeout: 120
    inputs:
      areaName:
        type: string
        description: 地区名称，如"福州市"、"厦门市"
        required: true
      elementType:
        type: string
        description: 气象要素类型，如 temAvg(平均温度)、temMax(最高温度)、temMin(最低温度)、precip(降水量)
        required: true
      startTime:
        type: date
        description: 开始日期，格式 YYYY-MM-DD
        required: true
      endTime:
        type: date
        description: 结束日期，格式 YYYY-MM-DD
        required: true
      statistics:
        type: string
        description: 统计方式，如 avg(平均)、max(最大)、min(最小)、sum(累计)
        default: avg
      chart_type:
        type: string
        description: 图表类型，如"色斑图"。
        default: 色斑图
    body_template:
      inputs:
        areaName: "{areaName}"
        elementType: "{elementType}"
        startTime: "{startTime}"
        endTime: "{endTime}"
        statistics: "{statistics}"
        chart_type: "{chart_type}"
      response_mode: blocking
      user: "agent-user"
    response_path: data.outputs
---

# 气象色斑图生成

## 路由说明
- 用户明确给出具体日期时使用本技能
- 用户使用相对时间表达（最近三天、近一周、近一个月）时，改用 weather_map_recent
- 调用前必须确认参数完整：地区、气象要素、开始时间、结束时间
- 如果用户缺少必要参数，必须主动向用户询问

## 功能描述
- 根据用户指定的地区、气象要素和时间范围，调用 Dify 工作流生成色斑图
- 支持平均温度、最高温度、最低温度、降水量等多种气象要素
- 返回生成的图片地址

## 可用参数
- areaName：地区名称（如"福州市"）
- elementType：气象要素（temAvg/temMax/temMin/precip）
- startTime：开始日期
- endTime：结束日期
- statistics：统计方式（avg/max/min/sum）
- chart_type：图表类型

## 使用示例
- 福州市最近一个月的平均温度色斑图
- 查询厦门市2026年4月的降水量色斑图
- 生成厦门市从2026-04-01到2026-05-01的最高温度色斑图
