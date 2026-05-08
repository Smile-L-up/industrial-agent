"""
Streaming - 流式响应处理
负责处理流式输出和实时反馈
"""

import asyncio
import json
from typing import Dict, List, Any, Optional, AsyncGenerator, Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class EventType(Enum):
    """事件类型"""
    TOKEN = "token"
    MESSAGE = "message"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    ERROR = "error"
    COMPLETE = "complete"


@dataclass
class StreamEvent:
    """流事件"""
    type: EventType
    data: Any
    timestamp: datetime
    sequence: int


class StreamHandler:
    """流处理器类"""
    
    def __init__(self):
        """初始化流处理器"""
        self.handlers: Dict[EventType, List[Callable]] = {
            event: [] for event in EventType
        }
        self.buffer: List[StreamEvent] = []
        self.sequence = 0
    
    def on(self, event_type: EventType, callback: Callable):
        """
        注册事件处理器
        
        Args:
            event_type: 事件类型
            callback: 回调函数
        """
        self.handlers[event_type].append(callback)
    
    def off(self, event_type: EventType, callback: Callable):
        """移除事件处理器"""
        if callback in self.handlers[event_type]:
            self.handlers[event_type].remove(callback)
    
    async def emit(self, event_type: EventType, data: Any):
        """
        触发事件
        
        Args:
            event_type: 事件类型
            data: 事件数据
        """
        event = StreamEvent(
            type=event_type,
            data=data,
            timestamp=datetime.now(),
            sequence=self.sequence
        )
        self.sequence += 1
        self.buffer.append(event)
        
        # 调用所有注册的处理器
        for handler in self.handlers[event_type]:
            if asyncio.iscoroutinefunction(handler):
                await handler(event)
            else:
                handler(event)
    
    def get_buffer(self, limit: Optional[int] = None) -> List[StreamEvent]:
        """获取事件缓冲区"""
        if limit:
            return self.buffer[-limit:]
        return self.buffer
    
    def clear_buffer(self):
        """清空缓冲区"""
        self.buffer.clear()
        self.sequence = 0


class StreamingResponse:
    """流式响应类"""
    
    def __init__(self):
        """初始化流式响应"""
        self._queue: asyncio.Queue = asyncio.Queue()
        self._complete = False
        self._error: Optional[str] = None
    
    async def write(self, data: Any):
        """
        写入数据
        
        Args:
            data: 数据
        """
        await self._queue.put(data)
    
    async def end(self):
        """结束流"""
        self._complete = True
        await self._queue.put(None)
    
    async def error(self, message: str):
        """报告错误"""
        self._error = message
        await self._queue.put(None)
    
    async def read(self) -> Any:
        """读取数据"""
        return await self._queue.get()
    
    async def __aiter__(self) -> AsyncGenerator[Any, None]:
        """异步迭代器"""
        while True:
            item = await self._queue.get()
            if item is None:
                break
            yield item
    
    def is_complete(self) -> bool:
        """检查是否完成"""
        return self._complete
    
    def get_error(self) -> Optional[str]:
        """获取错误信息"""
        return self._error


class TokenStream:
    """令牌流处理器"""
    
    def __init__(self, handler: Optional[StreamHandler] = None):
        """
        初始化令牌流
        
        Args:
            handler: 流处理器
        """
        self.handler = handler or StreamHandler()
        self.tokens: List[str] = []
        self._complete = False
    
    async def process(
        self,
        async_generator: AsyncGenerator[str, None]
    ) -> AsyncGenerator[str, None]:
        """
        处理异步生成器
        
        Args:
            async_generator: 令牌异步生成器
            
        Yields:
            令牌
        """
        async for token in async_generator:
            self.tokens.append(token)
            await self.handler.emit(EventType.TOKEN, token)
            yield token
        
        self._complete = True
        await self.handler.emit(EventType.COMPLETE, "".join(self.tokens))
    
    def get_result(self) -> str:
        """获取结果"""
        return "".join(self.tokens)
    
    def is_complete(self) -> bool:
        """检查是否完成"""
        return self._complete


class ResponseFormatter:
    """响应格式化器"""
    
    @staticmethod
    def format_text(text: str) -> Dict[str, Any]:
        """格式化文本响应"""
        return {
            "type": "text",
            "content": text,
            "timestamp": datetime.now().isoformat()
        }
    
    @staticmethod
    def format_json(data: Any) -> Dict[str, Any]:
        """格式化 JSON 响应"""
        return {
            "type": "json",
            "content": data,
            "timestamp": datetime.now().isoformat()
        }
    
    @staticmethod
    def format_tool_call(
        name: str,
        arguments: Dict[str, Any],
        call_id: str
    ) -> Dict[str, Any]:
        """格式化工具调用"""
        return {
            "type": "tool_call",
            "name": name,
            "arguments": arguments,
            "id": call_id,
            "timestamp": datetime.now().isoformat()
        }
    
    @staticmethod
    def format_tool_result(
        call_id: str,
        result: Any,
        success: bool = True
    ) -> Dict[str, Any]:
        """格式化工具结果"""
        return {
            "type": "tool_result",
            "call_id": call_id,
            "result": result,
            "success": success,
            "timestamp": datetime.now().isoformat()
        }
    
    @staticmethod
    def format_error(message: str, code: str = "UNKNOWN") -> Dict[str, Any]:
        """格式化错误"""
        return {
            "type": "error",
            "code": code,
            "message": message,
            "timestamp": datetime.now().isoformat()
        }


class SSEFormatter:
    """SSE (Server-Sent Events) 格式化器"""
    
    @staticmethod
    def format_event(event: str, data: Any) -> str:
        """
        格式化 SSE 事件
        
        Args:
            event: 事件名称
            data: 事件数据
            
        Returns:
            SSE 格式字符串
        """
        if isinstance(data, (dict, list)):
            data = json.dumps(data, ensure_ascii=False)
        else:
            data = str(data)
        
        lines = data.split("\n")
        data_lines = "\n".join(f"data: {line}" for line in lines)
        
        return f"event: {event}\n{data_lines}\n\n"
    
    @staticmethod
    def format_data(data: Any) -> str:
        """格式化纯数据 SSE"""
        return SSEFormatter.format_event("message", data)
    
    @staticmethod
    def format_ping() -> str:
        """格式化心跳"""
        return ": ping\n\n"


async def create_streaming_response(
    async_generator: AsyncGenerator[str, None],
    format_type: str = "text"
) -> StreamingResponse:
    """
    创建流式响应
    
    Args:
        async_generator: 异步生成器
        format_type: 格式化类型
        
    Returns:
        流式响应对象
    """
    response = StreamingResponse()
    formatter = ResponseFormatter()
    
    async def process():
        async for token in async_generator:
            if format_type == "text":
                await response.write(formatter.format_text(token))
            elif format_type == "json":
                await response.write(formatter.format_json(token))
            else:
                await response.write(token)
        await response.end()
    
    asyncio.create_task(process())
    return response