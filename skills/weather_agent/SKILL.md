---
name: weather_agent
description: "调用气象智能体回答气象相关问题（台风、气候知识、气象科普等）"

services:
  - name: chat
    description: "调用气象领域智能体回答问题"
    service_type: dify
    endpoint: http://192.168.110.201/v1/chat-messages
    headers:
      Authorization: "Bearer app-PPtrwsQLizjdR6HDOW7eGzp6"
    inputs:
      query:
        type: string
        description: 用户提出的气象相关问题
        required: true
---

# 气象智能体问答

## 功能描述
- 调用气象领域智能体（Agent RAG），回答气象相关问题
- 支持台风、气候知识、气象科普等各类气象问题
- 智能体会结合知识库给出专业回答

## 可用参数
- query：用户提出的气象相关问题（必填）

## 使用示例
- 台风一般什么时候来？
- 什么是厄尔尼诺现象？
- 气象预警信号有哪些等级？
- 福建地区常见的气象灾害有哪些？
