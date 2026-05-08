# 多模态图片支持 - 内网图片访问解决方案

## 问题描述

当你使用通义千问等多模态 API 时，如果图片 URL 是内网地址（如 `http://192.168.110.200/...`），会遇到以下错误：

```json
{
    "type": "error",
    "message": "Error code: 400 - {'error': {'message': '<400> InternalError.Algo.InvalidParameter: Download multimodal file timed out', ...}}"
}
```

**原因**：通义千问 API 服务器在阿里云公网，无法访问你的内网资源。

## 解决方案

本项目已集成图片自动转换功能，会自动将内网图片 URL 转换为 base64 编码嵌入请求中。

### 自动转换（推荐）

API 服务会自动处理消息中的图片 URL，无需修改客户端代码。

**请求示例**：
```json
{
    "messages": [{
        "role": "user",
        "content": [
            {"type": "text", "text": "对比这两张图片"},
            {"type": "image_url", "image_url": {"url": "http://192.168.110.200:46300/ai-center/files/image1.png"}},
            {"type": "image_url", "image_url": {"url": "http://192.168.110.200:46300/ai-center/files/image2.png"}}
        ]
    }],
    "model": "qwen3.5-plus"
}
```

服务端会自动将内网图片转换为 base64 格式：
```
data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAA...
```

### 手动转换（可选）

你也可以在客户端手动转换图片：

```python
from core.image_uploader import ImageUploader

# 从内网 URL 下载并转换为 base64
async def send_request_with_images():
    image_url_1 = await ImageUploader.download_to_base64_url(
        "http://192.168.110.200:46300/ai-center/files/image1.png"
    )
    image_url_2 = await ImageUploader.download_to_base64_url(
        "http://192.168.110.200:46300/ai-center/files/image2.png"
    )
    
    # 发送请求
    response = await client.post("/api/chat/stream", json={
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": "对比这两张图片"},
                {"type": "image_url", "image_url": {"url": image_url_1}},
                {"type": "image_url", "image_url": {"url": image_url_2}}
            ]
        }],
        "model": "qwen3.5-plus"
    })
```

## 安装依赖

确保安装了以下依赖：

```bash
pip install httpx pillow
```

或更新项目依赖：

```bash
pip install -r requirements.txt
```

## 配置选项

在 `core/image_uploader.py` 中可以配置：

- `MAX_IMAGE_SIZE`: 最大图片大小（默认 20MB）
- `timeout`: 下载超时时间（默认 30 秒）

## 支持的图片格式

- JPEG / JPG
- PNG
- GIF
- WebP
- BMP

## 注意事项

1. **图片大小限制**：单张图片最大 20MB，过大的图片会导致转换失败
2. **超时设置**：内网下载超时默认 30 秒，可根据网络情况调整
3. **base64 开销**：base64 编码会使数据大小增加约 33%
4. **公网图片**：如果图片 URL 已经是公网可访问的，可以不转换直接使用

## 其他替代方案

如果自动转换仍无法满足需求，可以考虑：

### 方案 1：上传到公网存储

将图片上传到阿里云 OSS、七牛云等公网可访问的存储服务。

### 方案 2：配置网络代理

如果你的环境有公网代理，可以配置让 API 服务器通过代理访问内网。

### 方案 3：使用本地部署模型

在内网部署本地多模态模型，避免网络访问问题。