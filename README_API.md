# 智能体 API 服务

智能体系统的 FastAPI 服务，支持流式和非流式两种输出模式。

## 快速启动

```bash
# 安装依赖
pip install -r requirements.txt

# 启动 API 服务
python api.py
```

服务将在 http://localhost:18000 启动。

## API 端点

### 1. 根路径
- **GET /** - 返回前端演示页面
- **GET /api** - 返回 API 信息

### 2. 健康检查
- **GET /health** - 检查服务状态

```bash
curl http://localhost:18000/health
```

响应示例：
```json
{
  "status": "healthy",
  "llm": "ready",
  "memory": "ready",
  "skills_count": 2
}
```

### 3. 聊天接口（非流式）
- **POST /api/chat** - 处理用户查询并返回完整结果

```bash
curl -X POST http://localhost:18000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "北京天气怎么样？", "stream": false}'
```

响应示例：
```json
{
  "query": "北京天气怎么样？",
  "result": {...},
  "final_result": "北京当前天气晴朗，气温 25°C..."
}
```

### 4. 聊天接口（流式）
- **POST /api/chat/stream** - 使用 SSE 实时返回处理进度

```bash
curl -X POST http://localhost:18000/api/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"query": "北京天气怎么样？", "stream": true}'
```

流式数据格式（SSE）：
```
data: {"type": "text", "content": "📋 正在规划任务...\n"}

data: {"type": "text", "content": "✓ 规划完成\n\n## 任务目标..."}
```

### 5. 技能列表
- **GET /api/skills** - 获取可用技能列表

```bash
curl http://localhost:18000/api/skills
```

## 前端演示

访问 http://localhost:18000 打开前端演示页面，可以：
- 输入查询内容
- 选择是否启用流式输出
- 实时查看处理进度

## Python 客户端示例

```python
import asyncio
import httpx

# 非流式调用
async def chat_non_stream():
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:18000/api/chat",
            json={"query": "北京天气怎么样？"}
        )
        return response.json()

# 流式调用
async def chat_stream():
    async with httpx.AsyncClient() as client:
        async with client.stream(
            "POST",
            "http://localhost:18000/api/chat/stream",
            json={"query": "北京天气怎么样？"}
        ) as response:
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    print(line[6:])

asyncio.run(chat_non_stream())
```

## 配置说明

在 `.env` 文件中配置 LLM 参数：

```
DASHSCOPE_API_KEY=your_api_key
DASHSCOPE_MODEL=qwen-plus
```

## 请求参数说明

### ChatRequest 参数

| 参数名 | 类型 | 必填 | 默认值 | 说明 |
|--------|------|------|--------|------|
| query | string | 是 | - | 用户查询内容 |
| session_id | string | 否 | null | 会话 ID（用于多轮对话） |
| stream | boolean | 否 | false | 是否启用流式输出 |
| image | string | 否 | null | 图片的 Base64 编码（用于多模态理解） |
| image_url | string | 否 | null | 图片的 URL（用于多模态理解） |
| model | string | 否 | null | 指定使用的模型（覆盖默认配置） |
| vl_model | string | 否 | null | 指定使用的视觉语言模型（覆盖默认配置） |
| thinking | boolean | 否 | null | 是否启用思考模式（用于 Qwen 等支持思考的模型） |
| enable_thinking | boolean | 否 | null | thinking 的别名参数 |

### thinking 参数说明

部分模型（如 Qwen）支持思考模式，通过 `thinking` 参数控制：

- `thinking: true` - 启用思考模式，模型会进行更深入的推理和分析
- `thinking: false` - 关闭思考模式，模型直接给出答案
- `thinking: null` 或未提供 - 使用模型默认行为

**注意**：思考内容的返回取决于模型和 API 提供商的支持情况：
- 通过 DashScope OpenAI 兼容接口调用时，使用 `extra_body: {"enable_thinking": true}` 参数
- 支持思考模式的模型（如 Qwen-Max）会返回 `reasoning_content` 字段
- 当启用思考模式但模型不支持时，`thinking_content` 字段将为 `null`

```bash
# 启用思考模式
curl -X POST http://localhost:18000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "请解释量子力学的基本原理", "thinking": true}'

# 关闭思考模式
curl -X POST http://localhost:18000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "请解释量子力学的基本原理", "thinking": false}'

# 流式模式启用思考
curl -X POST http://localhost:18000/api/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"query": "请解释量子力学的基本原理", "thinking": true}'
```

### 响应中的 thinking_content 字段

当模型支持并启用思考模式时，响应中会包含 `thinking_content` 字段：

```json
{
  "query": "请解释量子力学的基本原理",
  "session_id": "xxx",
  "result": {
    "context": {
      "thinking_content": "首先，我需要理解用户询问的是量子力学的基本原理。这是一个复杂的物理理论..."
    },
    "final_result": "量子力学是描述微观粒子行为的基本物理理论..."
  },
  "final_result": "量子力学是描述微观粒子行为的基本物理理论..."
}
```

## 项目结构

```
industrial-agent/
├── api.py              # FastAPI 服务主文件
├── api_client.py       # Python 客户端示例
├── static/
│   └── index.html      # 前端演示页面
├── test_api.py         # API 测试脚本
├── test_chat.py        # 聊天 API 测试脚本
└── README_API.md       # 本文档
```

## 注意事项

1. 服务启动时会初始化 LLM、记忆系统和技能模块，约需 5-10 秒
2. 流式输出使用 SSE (Server-Sent Events) 协议
3. 确保 `.env` 文件中配置了正确的 API 密钥
4. 默认端口为 18000，可通过修改 `api.py` 中的 `uvicorn.run()` 更改
