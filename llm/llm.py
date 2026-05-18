"""
LLM - 语言模型接口
提供统一的语言模型调用接口
支持 OpenAI 及兼容 OpenAI 接口的服务（如 Qwen/DashScope）
"""

import asyncio
import logging
from typing import Dict, List, Any, Optional, AsyncGenerator, Callable
from dataclasses import dataclass
from abc import ABC, abstractmethod

logger = logging.getLogger("industrial_agent.llm")


@dataclass
class Message:
    """消息类"""
    role: str  # system, user, assistant
    content: str | list  # 支持文本或包含图片的多模态内容
    
    def to_dict(self) -> dict:
        """转换为字典格式"""
        return {"role": self.role, "content": self.content}


@dataclass
class LLMResponse:
    """LLM 响应类"""
    content: str
    model: str
    usage: Dict[str, int]
    finish_reason: str
    raw_response: Any = None
    thinking_content: Optional[str] = None  # 思考内容（如果启用思考模式）


class BaseLLM(ABC):
    """语言模型基类"""
    
    def __init__(
        self,
        model: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = 4096,
        **kwargs
    ):
        """
        初始化语言模型
        
        Args:
            model: 模型名称
            temperature: 温度参数
            max_tokens: 最大生成 token 数
        """
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._config = kwargs
    
    @abstractmethod
    async def generate(self, prompt: str, **kwargs) -> str:
        """生成响应"""
        pass
    
    @abstractmethod
    async def generate_stream(
        self,
        prompt: str,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """流式生成响应"""
        pass
    
    @abstractmethod
    async def chat(
        self,
        messages: List[Message],
        **kwargs
    ) -> LLMResponse:
        """对话"""
        pass


class OpenAILLM(BaseLLM):
    """OpenAI 语言模型 / 兼容 OpenAI 接口的服务"""
    
    def __init__(
        self,
        model: str = "gpt-3.5-turbo",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        temperature: Optional[float] = 0.7,
        max_tokens: Optional[int] = 4096,
        enable_thinking: Optional[bool] = None,
        top_p: Optional[float] = 1.0,
        frequency_penalty: Optional[float] = 0.0,
        presence_penalty: Optional[float] = 0.0,
        system_prompt: Optional[str] = None,
        **kwargs
    ):
        """
        初始化 OpenAI 模型
        
        Args:
            model: 模型名称
            api_key: API 密钥
            base_url: API 基础 URL（可用于兼容接口，如 DashScope）
            temperature: 温度参数（0-2，越高越随机），默认 0.7
            max_tokens: 最大 token 数，默认 4096
            enable_thinking: 是否启用思考模式（可选，用于 Qwen 等支持思考的模型）
            top_p: 核采样参数，默认 1.0
            frequency_penalty: 频率惩罚，默认 0.0
            presence_penalty: 存在惩罚，默认 0.0
            system_prompt: 系统提示词（可选，用于控制模型回答风格和语言）
            
        示例 - 使用 Qwen 通过 DashScope:
            model="qwen-plus"
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
            api_key="sk-xxx"
            enable_thinking=True  # 启用思考模式
        """
        # 处理 None 值：如果传入 None，使用默认值
        if temperature is None:
            temperature = 0.7
        if max_tokens is None:
            max_tokens = 4096
        if top_p is None:
            top_p = 1.0
        if frequency_penalty is None:
            frequency_penalty = 0.0
        if presence_penalty is None:
            presence_penalty = 0.0
        
        super().__init__(model, temperature, max_tokens, **kwargs)
        
        # 保存其他 OpenAI 兼容参数
        self.top_p = top_p
        self.frequency_penalty = frequency_penalty
        self.presence_penalty = presence_penalty
        
        # 系统提示词配置
        self.system_prompt = system_prompt
        
        try:
            from openai import AsyncOpenAI
            self.client = AsyncOpenAI(
                api_key=api_key,
                base_url=base_url
            )
        except ImportError:
            raise ImportError("请安装 openai: pip install openai")
        
        # 思考模式配置
        self.enable_thinking = enable_thinking
    
    async def generate(self, prompt: str, **kwargs) -> str:
        """生成响应"""
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=kwargs.get("temperature", self.temperature),
            max_tokens=kwargs.get("max_tokens", self.max_tokens)
        )
        return response.choices[0].message.content
    
    async def generate_stream(
        self,
        prompt: str,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """流式生成"""
        stream = await self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=kwargs.get("temperature", self.temperature),
            max_tokens=kwargs.get("max_tokens", self.max_tokens),
            stream=True
        )
        
        async for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
    
    async def chat(
        self,
        messages: List[Message],
        **kwargs
    ) -> LLMResponse:
        """对话"""
        msg_dicts = [{"role": m.role, "content": m.content} for m in messages]
        
        # 自动添加 system prompt（如果配置了且第一条消息不是 system）
        if self.system_prompt and (not msg_dicts or msg_dicts[0]["role"] != "system"):
            msg_dicts.insert(0, {"role": "system", "content": self.system_prompt})
        
        # 获取 enable_thinking 参数（支持实例配置和调用时覆盖）
        enable_thinking = kwargs.get("enable_thinking", self.enable_thinking)
        
        # 构建请求参数 - 使用 or 确保 None 值不会覆盖默认值
        # 注意：kwargs.get("temperature", self.temperature) 在 kwargs["temperature"]=None 时会返回 None
        # 所以需要使用 (kwargs.get("temperature") or self.temperature) 来确保 None 被忽略
        request_params = {
            "model": self.model,
            "messages": msg_dicts,
            "temperature": kwargs.get("temperature") or self.temperature,
            "max_tokens": kwargs.get("max_tokens") or self.max_tokens
        }
        
        # 添加其他 OpenAI 兼容参数（只在非 None 时添加）
        if self.top_p is not None:
            request_params["top_p"] = self.top_p
        if self.frequency_penalty is not None:
            request_params["frequency_penalty"] = self.frequency_penalty
        if self.presence_penalty is not None:
            request_params["presence_penalty"] = self.presence_penalty
        
        # 如果启用了 thinking 模式，添加 extra_body 参数（DashScope 使用 enable_thinking）
        if enable_thinking is True:
            # request_params["extra_body"] = {
            #     "enable_thinking": True
            # }
            request_params["extra_body"] = {
                "chat_template_kwargs": {
                    "enable_thinking": True
                },
                "thinking_budget": 200
            }

            logger.debug("发送请求，enable_thinking=True")
        
        response = await self.client.chat.completions.create(**request_params)
        logger.debug("收到响应，response.choices[0].message.__dict__ = %s", response.choices[0].message.__dict__)
        
        choice = response.choices[0]
        
        # 提取思考内容（Qwen/DashScope 在 reasoning_content 字段中）
        thinking_content = None
        message = choice.message
        
        # 尝试多种方式获取思考内容
        # 1. 直接检查 message 的 reasoning_content 属性（DashScope 通过 openai 库返回时可能不在 __dict__ 中）
        if hasattr(message, 'reasoning_content'):
            rc = getattr(message, 'reasoning_content', None)
            if rc:
                thinking_content = rc
        # 2. 检查 reasoning 属性
        if not thinking_content and hasattr(message, 'reasoning'):
            reasoning = getattr(message, 'reasoning', None)
            if reasoning:
                thinking_content = reasoning
        # 3. 检查 response.model_extra
        if not thinking_content and hasattr(response, 'model_extra'):
            model_extra = response.model_extra
            if model_extra and 'reasoning_content' in model_extra:
                thinking_content = model_extra['reasoning_content']
        # 4. 检查 response 的 reasoning_content 属性
        if not thinking_content and hasattr(response, 'reasoning_content'):
            thinking_content = getattr(response, 'reasoning_content', None)
        
        return LLMResponse(
            content=choice.message.content,
            model=self.model,
            usage={
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens
            },
            finish_reason=choice.finish_reason,
            raw_response=response,
            thinking_content=thinking_content
        )
    
    async def chat_stream(
        self,
        messages: List[Message],
        cancel_event: Optional[asyncio.Event] = None,
        **kwargs
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        流式对话 - 支持思考模式（实时输出）

        Args:
            messages: 消息列表
            cancel_event: 取消信号事件（设置后终止流式输出）
            **kwargs: 其他参数

        Yields:
            字典格式的数据块，包含：
            - {"type": "reasoning_content", "content": "..."}  # 思考内容（实时输出）
            - {"type": "content", "content": "..."}  # 回答内容（实时输出）
            - {"type": "usage", "usage": {...}}  # usage 信息

        示例:
            async for chunk in llm.chat_stream(messages, enable_thinking=True):
                if chunk["type"] == "reasoning_content":
                    print(f"思考：{chunk['content']}")
                elif chunk["type"] == "content":
                    print(f"回答：{chunk['content']}")
        """
        msg_dicts = [{"role": m.role, "content": m.content} for m in messages]
        
        # 自动添加 system prompt（如果配置了且第一条消息不是 system）
        if self.system_prompt and (not msg_dicts or msg_dicts[0]["role"] != "system"):
            msg_dicts.insert(0, {"role": "system", "content": self.system_prompt})
        
        # 获取 enable_thinking 参数（支持实例配置和调用时覆盖）
        enable_thinking = kwargs.get("enable_thinking", self.enable_thinking)
        
        # 构建请求参数 - 使用 or 确保 None 值不会覆盖默认值
        request_params = {
            "model": self.model,
            "messages": msg_dicts,
            "temperature": kwargs.get("temperature") or self.temperature,
            "max_tokens": kwargs.get("max_tokens") or self.max_tokens,
            "stream": True,
            "stream_options": {
                "include_usage": True
            }
        }
        
        # 添加其他 OpenAI 兼容参数（只在非 None 时添加）
        if self.top_p is not None:
            request_params["top_p"] = self.top_p
        if self.frequency_penalty is not None:
            request_params["frequency_penalty"] = self.frequency_penalty
        if self.presence_penalty is not None:
            request_params["presence_penalty"] = self.presence_penalty
        
        # 添加 extra_body 参数控制思考模式（DashScope 使用 enable_thinking）
        # enable_thinking=True 时启用思考，enable_thinking=False 时明确禁用思考，enable_thinking=None 时使用默认行为
        if enable_thinking is not None:
                

            # request_params["extra_body"] = {
            #     "enable_thinking": enable_thinking
            # }
            request_params["extra_body"] = {
                "chat_template_kwargs": {
                    "enable_thinking": enable_thinking
                },
                "thinking_budget": 200
            }
            logger.debug("chat_stream model=%s, enable_thinking=%s", self.model, enable_thinking)
        
        stream = await self.client.chat.completions.create(**request_params)

        # 实时输出：收到 chunk 后立即 yield，不再缓存
        try:
            async for chunk in stream:
                # 检查取消信号
                if cancel_event and cancel_event.is_set():
                    logger.info("检测到取消信号，终止 LLM 流式输出")
                    await stream.close()
                    return

                if not chunk.choices:
                    # 返回 usage 信息
                    if hasattr(chunk, 'usage') and chunk.usage:
                        yield {
                            "type": "usage",
                            "usage": {
                                "prompt_tokens": chunk.usage.prompt_tokens,
                                "completion_tokens": chunk.usage.completion_tokens,
                                "total_tokens": chunk.usage.total_tokens
                            }
                        }
                    continue

                delta = chunk.choices[0].delta

                # 实时输出思考内容
                if hasattr(delta, "reasoning_content") and delta.reasoning_content is not None:
                    logger.debug("chat_stream 收到 reasoning_content, enable_thinking=%s, content=%s...", enable_thinking, delta.reasoning_content[:30])
                    # 如果 enable_thinking=False，跳过输出思考内容
                    if enable_thinking is not False:
                        yield {
                            "type": "reasoning_content",
                            "content": delta.reasoning_content
                        }
                    else:
                        logger.debug("chat_stream enable_thinking=False, 跳过输出思考内容")

                # 实时输出回答内容
                if hasattr(delta, "content") and delta.content is not None:
                    yield {
                        "type": "content",
                        "content": delta.content
                    }
        except asyncio.CancelledError:
            logger.info("LLM 流式输出被取消")
            await stream.close()
            raise


class AzureOpenAILLM(BaseLLM):
    """Azure OpenAI 语言模型"""
    
    def __init__(
        self,
        azure_endpoint: str,
        api_key: str,
        api_version: str = "2023-05-15",
        deployment: str = "gpt-35-turbo",
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ):
        """
        初始化 Azure OpenAI 模型
        
        Args:
            azure_endpoint: Azure 端点
            api_key: API 密钥
            api_version: API 版本
            deployment: 部署名称
            temperature: 温度参数
            max_tokens: 最大 token 数
        """
        super().__init__(deployment, temperature, max_tokens, **kwargs)
        
        try:
            from openai import AsyncAzureOpenAI
            self.client = AsyncAzureOpenAI(
                azure_endpoint=azure_endpoint,
                api_key=api_key,
                api_version=api_version
            )
            self._deployment = deployment
        except ImportError:
            raise ImportError("请安装 openai: pip install openai")
    
    async def generate(self, prompt: str, **kwargs) -> str:
        """生成响应"""
        response = await self.client.chat.completions.create(
            model=self._deployment,
            messages=[{"role": "user", "content": prompt}],
            temperature=kwargs.get("temperature", self.temperature),
            max_tokens=kwargs.get("max_tokens", self.max_tokens)
        )
        return response.choices[0].message.content
    
    async def generate_stream(
        self,
        prompt: str,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """流式生成"""
        stream = await self.client.chat.completions.create(
            model=self._deployment,
            messages=[{"role": "user", "content": prompt}],
            temperature=kwargs.get("temperature", self.temperature),
            max_tokens=kwargs.get("max_tokens", self.max_tokens),
            stream=True
        )
        
        async for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
    
    async def chat(
        self,
        messages: List[Message],
        **kwargs
    ) -> LLMResponse:
        """对话"""
        msg_dicts = [{"role": m.role, "content": m.content} for m in messages]
        
        response = await self.client.chat.completions.create(
            model=self._deployment,
            messages=msg_dicts,
            temperature=kwargs.get("temperature", self.temperature),
            max_tokens=kwargs.get("max_tokens", self.max_tokens)
        )
        
        choice = response.choices[0]
        return LLMResponse(
            content=choice.message.content,
            model=self._deployment,
            usage={
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens
            },
            finish_reason=choice.finish_reason,
            raw_response=response
        )
    
    async def chat_stream(
        self,
        messages: List[Message],
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """流式对话 - 逐 chunk 返回"""
        msg_dicts = [{"role": m.role, "content": m.content} for m in messages]
        
        stream = await self.client.chat.completions.create(
            model=self._deployment,
            messages=msg_dicts,
            temperature=kwargs.get("temperature", self.temperature),
            max_tokens=kwargs.get("max_tokens", self.max_tokens),
            stream=True
        )
        
        async for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content


class LLMFactory:
    """LLM 工厂类"""
    
    _providers = {
        "openai": OpenAILLM,
        "azure_openai": AzureOpenAILLM,
    }
    
    @classmethod
    def register_provider(cls, name: str, provider_class: type):
        """注册提供商"""
        cls._providers[name] = provider_class
    
    @classmethod
    def create(
        cls,
        provider: str,
        **kwargs
    ) -> BaseLLM:
        """
        创建 LLM 实例
        
        Args:
            provider: 提供商名称
            **kwargs: 提供商参数
            
        Returns:
            LLM 实例
        """
        if provider not in cls._providers:
            raise ValueError(f"未知的提供商：{provider}")
        
        return cls._providers[provider](**kwargs)


# 便捷函数
def get_llm(provider: str, **kwargs) -> BaseLLM:
    """获取 LLM 实例"""
    return LLMFactory.create(provider, **kwargs)


async def generate_with_retry(
    llm: BaseLLM,
    prompt: str,
    max_retries: int = 3,
    retry_delay: float = 1.0,
    **kwargs
) -> str:
    """带重试的生成"""
    last_error = None
    
    for i in range(max_retries):
        try:
            return await llm.generate(prompt, **kwargs)
        except Exception as e:
            last_error = e
            if i < max_retries - 1:
                await asyncio.sleep(retry_delay * (i + 1))
    
    raise RuntimeError(f"生成失败：{last_error}")