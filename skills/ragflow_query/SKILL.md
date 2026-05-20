---
name: ragflow_query
description: "从 RAGFlow 知识库中检索相关信息，回答用户关于知识库内容的问题。当用户提问需要查阅知识库资料时使用。"
service_type: http
endpoint: http://192.168.110.201:9383/api/v1/retrieval
method: POST
headers:
  Authorization: "Bearer ragflow-yD_aZWc9SxOSq__d9XPYEYRKhZR3Im0Ww2Rkm9T3D1w"
timeout: 30
inputs:
  question:
    type: string
    description: 用户提出的问题
    required: true
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
keywords:
  - 知识库
  - RAG
  - 检索
  - RAGFlow
  - 问答
---

# RAGFlow 知识库检索

## 功能描述
- 根据用户提出的问题，从 RAGFlow 知识库中检索相关文档片段
- 返回检索结果，供 LLM 整合生成最终回答

## 可用参数
- question：用户提出的问题（必填）

## 使用示例
- RAG是什么？
- 帮我查一下知识库里关于气象数据的内容
- 从知识库中检索工业物联网的相关信息
