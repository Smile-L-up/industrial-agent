---
name: weather_map
description: 气象色斑图生成服务，根据地区、要素类型和时间范围生成气象数据色斑图
keywords:
  - 气象
  - 色斑图
  - 温度
  - 降水
  - 天气图
  - 气温
  - 平均温度
  - 最高温度
  - 最低温度

# 服务类型：http（通用 HTTP）/ dify（Dify 工作流）
service_type: dify

# 服务端点
endpoint: http://192.168.110.201:18080/v1/workflows/run

# 请求方法
method: POST

# 请求头（支持环境变量 ${VAR}）
headers:
  Authorization: "Bearer app-MJAlwJk6Hp428NTzt5EBxBVf"

# 超时时间（秒）
timeout: 120

# 输入参数定义
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

# 请求体模板（{param} 会被替换为实际参数值）
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

# 响应结果提取路径（点分隔的 JSON 路径）
response_path: data.outputs
---

# 气象色斑图生成

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
