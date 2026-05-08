"""
图片上传器 - 支持将本地图片转换为 base64 编码或上传到图床

解决多模态 API 无法访问内网图片的问题

使用方法：
1. 本地图片转 base64：
   image_url = await ImageUploader.local_to_base64_url("path/to/image.jpg")
   # 返回：data:image/jpeg;base64,/9j/4AAQSkZJRg...

2. 从 HTTP URL 下载并转 base64（适用于内网图片）：
   image_url = await ImageUploader.download_to_base64_url("http://192.168.110.200/image.jpg")

3. 在消息中使用：
   messages = [{
       "role": "user",
       "content": [
           {"type": "text", "text": "对比这两张图片"},
           {"type": "image_url", "image_url": {"url": image_url_1}},
           {"type": "image_url", "image_url": {"url": image_url_2}}
       ]
   }]
"""

import base64
import io
import logging
import mimetypes
import os
import traceback
from typing import Optional, Union
from pathlib import Path

logger = logging.getLogger("industrial_agent.image_uploader")

# 异步 HTTP 客户端（用于下载内网图片）
try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False
    logger.warning("httpx 未安装，无法下载网络图片。请安装：pip install httpx")

# Pillow 用于图片处理
try:
    from PIL import Image
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False
    logger.warning("Pillow 未安装，无法处理图片。请安装：pip install pillow")


class ImageUploader:
    """图片上传器"""
    
    # 支持的最大图片大小（字节），默认 20MB
    MAX_IMAGE_SIZE = 20 * 1024 * 1024
    
    # 支持的图片格式
    SUPPORTED_FORMATS = ["jpeg", "jpg", "png", "gif", "webp", "bmp"]
    
    # MIME 类型映射
    MIME_MAP = {
        "jpeg": "image/jpeg",
        "jpg": "image/jpeg",
        "png": "image/png",
        "gif": "image/gif",
        "webp": "image/webp",
        "bmp": "image/bmp"
    }
    
    @classmethod
    def _get_mime_type(cls, file_path: str) -> str:
        """获取图片 MIME 类型"""
        ext = Path(file_path).suffix.lower().lstrip(".")
        if ext == "jpg":
            ext = "jpeg"
        return cls.MIME_MAP.get(ext, "image/jpeg")
    
    @classmethod
    def _get_mime_type_from_bytes(cls, image_data: bytes) -> str:
        """从图片数据头部识别 MIME 类型"""
        if image_data[:2] == b"\xff\xd8":
            return "image/jpeg"
        elif image_data[:8] == b"\x89PNG\r\n\x1a\n":
            return "image/png"
        elif image_data[:6] in [b"GIF87a", b"GIF89a"]:
            return "image/gif"
        elif image_data[:4] == b"RIFF" and image_data[8:12] == b"WEBP":
            return "image/webp"
        elif image_data[:2] == b"BM":
            return "image/bmp"
        return "image/jpeg"
    
    @classmethod
    async def local_to_base64_url(
        cls,
        file_path: Union[str, Path],
        max_size: Optional[int] = None
    ) -> str:
        """
        将本地图片文件转换为 base64 data URL
        
        Args:
            file_path: 本地图片文件路径
            max_size: 最大文件大小（字节），默认 20MB
            
        Returns:
            base64 data URL，格式：data:image/jpeg;base64,/9j/4AAQSkZJRg...
            
        Raises:
            FileNotFoundError: 文件不存在
            ValueError: 文件格式不支持或文件过大
        """
        file_path = Path(file_path)
        
        if not file_path.exists():
            raise FileNotFoundError(f"文件不存在：{file_path}")
        
        # 检查文件大小
        file_size = file_path.stat().st_size
        max_size = max_size or cls.MAX_IMAGE_SIZE
        if file_size > max_size:
            raise ValueError(f"文件过大：{file_size} 字节，最大支持 {max_size} 字节")
        
        # 读取文件
        with open(file_path, "rb") as f:
            image_data = f.read()
        
        # 获取 MIME 类型
        mime_type = cls._get_mime_type(str(file_path))
        
        # 转换为 base64
        base64_data = base64.b64encode(image_data).decode("utf-8")
        
        # 返回 data URL
        return f"data:{mime_type};base64,{base64_data}"
    
    @classmethod
    async def download_to_base64_url(
        cls,
        url: str,
        timeout: float = 30.0,
        max_size: Optional[int] = None
    ) -> str:
        """
        从 HTTP URL 下载图片并转换为 base64 data URL
        适用于内网图片，下载后转为 base64 嵌入请求
        
        Args:
            url: 图片 URL（可以是内网地址）
            timeout: 下载超时时间（秒）
            max_size: 最大文件大小（字节），默认 20MB
            
        Returns:
            base64 data URL
            
        Raises:
            ImportError: 未安装 httpx
            HTTPError: 下载失败
            ValueError: 文件格式不支持或文件过大
        """
        if not HAS_HTTPX:
            raise ImportError("请安装 httpx: pip install httpx")
        
        # 标准化 URL 中的路径分隔符（将 \ 转换为 /）
        url = url.replace("\\", "/")
        
        logger.info("开始下载图片：%s", url)
        
        # 使用更宽松的超时设置和重试机制
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=10.0),
            follow_redirects=True
        ) as client:
            try:
                response = await client.get(url)
                logger.debug("响应状态码：%s", response.status_code)
                response.raise_for_status()
                
                image_data = response.content
                logger.debug("图片大小：%d 字节", len(image_data))
                
                # 检查文件大小
                max_size = max_size or cls.MAX_IMAGE_SIZE
                if len(image_data) > max_size:
                    raise ValueError(f"文件过大：{len(image_data)} 字节，最大支持 {max_size} 字节")
                
                # 获取 MIME 类型
                mime_type = response.headers.get("content-type", "")
                if not mime_type or not mime_type.startswith("image/"):
                    # 从数据头部识别
                    mime_type = cls._get_mime_type_from_bytes(image_data)
                
                # 转换为 base64
                base64_data = base64.b64encode(image_data).decode("utf-8")
                
                logger.info("图片转换成功，MIME 类型：%s", mime_type)
                return f"data:{mime_type};base64,{base64_data}"
                
            except httpx.HTTPStatusError as e:
                logger.error("HTTP 错误：%s - %s", e.response.status_code, e.response.text[:200])
                raise
            except httpx.ConnectError as e:
                logger.error("连接错误：%s: %s", type(e).__name__, e, exc_info=True)
                raise
            except httpx.ReadTimeout as e:
                logger.error("读取超时：%s: %s", type(e).__name__, e, exc_info=True)
                raise
            except httpx.RequestError as e:
                logger.error("请求错误：%s: %s", type(e).__name__, e, exc_info=True)
                raise
            except Exception as e:
                logger.error("未知错误：%s: %s", type(e).__name__, e, exc_info=True)
                raise
    
    @classmethod
    async def convert_image_url(
        cls,
        url: str,
        timeout: float = 30.0,
        max_size: Optional[int] = None
    ) -> str:
        """
        转换图片 URL 为 base64 data URL
        如果是 http/https URL，则下载并转换；如果是本地文件路径，则直接转换
        
        Args:
            url: 图片 URL 或本地文件路径
            timeout: 下载超时时间（秒）
            max_size: 最大文件大小（字节）
            
        Returns:
            base64 data URL 或原始 URL（如果已经是 data URL）
        """
        # 如果已经是 data URL，直接返回
        if url.startswith("data:image/"):
            return url
        
        # 如果是本地文件路径
        if os.path.exists(url):
            return await cls.local_to_base64_url(url, max_size)
        
        # 如果是 http/https URL，下载并转换
        if url.startswith(("http://", "https://")):
            return await cls.download_to_base64_url(url, timeout, max_size)
        
        # 其他情况返回原始 URL
        return url
    
    @classmethod
    async def process_messages(
        cls,
        messages: list,
        timeout: float = 30.0,
        max_size: Optional[int] = None
    ) -> list:
        """
        处理消息列表中的图片 URL，将内网图片转换为 base64
        
        Args:
            messages: OpenAI 标准格式的消息列表
            timeout: 下载超时时间（秒）
            max_size: 最大文件大小（字节）
            
        Returns:
            处理后的消息列表
        """
        import copy
        processed_messages = copy.deepcopy(messages)
        
        for msg in processed_messages:
            if msg.get("role") != "user":
                continue
            
            content = msg.get("content", "")
            
            # 处理字符串内容
            if isinstance(content, str):
                continue
            
            # 处理列表内容（多模态）
            if isinstance(content, list):
                for item in content:
                    if item.get("type") == "image_url":
                        image_url_obj = item.get("image_url", {})
                        if isinstance(image_url_obj, dict):
                            url = image_url_obj.get("url", "")
                            if url:
                                # 转换为 base64
                                converted_url = await cls.convert_image_url(
                                    url, timeout, max_size
                                )
                                item["image_url"]["url"] = converted_url
        
        return processed_messages


# 便捷函数
async def convert_images_to_base64(messages: list, **kwargs) -> list:
    """
    便捷函数：将消息中的图片 URL 转换为 base64
    
    Args:
        messages: OpenAI 标准格式的消息列表
        **kwargs: 传递给 ImageUploader.process_messages 的参数
        
    Returns:
        处理后的消息列表
    """
    return await ImageUploader.process_messages(messages, **kwargs)