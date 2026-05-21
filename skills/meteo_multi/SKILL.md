---
name: meteo_multi
description: "综合气象分析：色斑图、天气报告、知识库检索三合一"
keywords:
  - 综合分析
  - 气象分析
  - 多服务
  - 色斑图
  - 气象报告

services:
  - name: map
    description: "生成气象色斑图（温度分布图、降水分布图），支持平均温度、最高温度、最低温度、降水量"
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
        description: 气象要素，temAvg(平均温度)/temMax(最高温度)/temMin(最低温度)/precip(降水量)
        required: true
      startTime:
        type: date
        description: 开始日期 YYYY-MM-DD
        required: true
      endTime:
        type: date
        description: 结束日期 YYYY-MM-DD
        required: true
      statistics:
        type: string
        description: 统计方式，avg/max/min/sum
        default: avg
      chart_type:
        type: string
        description: 图表类型
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

  - name: report
    description: "生成福建省地市的重要天气报告"
    service_type: mcp
    endpoint: http://192.168.110.201:18080/mcp/server/fuH8MDaMuFZhIaWc/mcp
    timeout: 60
    tool_name: "我的重要天气报告生成"
    inputs:
      query:
        type: string
        description: 用户输入，包含城市信息
        required: true

  - name: knowledge
    description: "从 RAGFlow 知识库检索气象相关资料和文档"
    service_type: http
    endpoint: http://192.168.110.201:9383/api/v1/retrieval
    method: POST
    headers:
      Authorization: "Bearer ragflow-yD_aZWc9SxOSq__d9XPYEYRKhZR3Im0Ww2Rkm9T3D1w"
    timeout: 30
    inputs:
      question:
        type: string
        description: 知识库检索问题
        default: 气象数据分析方法
    body_template:
      question: "{question}"
      dataset_ids:
        - "41a10475023611f1855a0242ac140006"
      similarity_threshold: 0.1
      vector_similarity_weight: 0.3
      top_k: 3
      page: 1
      page_size: 3
    response_path: data
---

# 综合气象分析（多服务模式）

## 功能描述
- 一个技能集成三个服务端点，根据用户意图自动规划调用
- 色斑图生成：支持温度、降水等多种气象要素的可视化
- 气象报告：生成福建省地市的重要天气报告
- 知识库检索：从 RAGFlow 知识库检索气象相关资料

## 使用示例
- 帮我做福州市的综合气象分析
- 生成厦门市最近三天的平均气温色斑图，并查一下知识库
- 生成福州天气报告
