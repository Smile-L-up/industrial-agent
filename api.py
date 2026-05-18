"""
FastAPI Service - 智能体广场 API 服务
提供流式和非流式两种模式的 HTTP 接口

支持多轮对话：通过 session_id 区分不同用户的对话历史
支持多模态：使用 OpenAI 标准格式传入多张图片
"""

import asyncio
import json
import logging
import uuid
from typing import Optional, AsyncGenerator, Dict, List, Any
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from core.logger import setup_logging
setup_logging()

logger = logging.getLogger("industrial_agent.api")

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import uvicorn

# 导入项目模块
from config import LLM_CONFIG, DATABASE_CONFIG, SESSION_CONFIG
from llm.llm import get_llm
from agent.graph import AgentGraph
from core.skill_loader import SkillLoader
from core.streaming import StreamingResponse as StreamResponse
from core.image_uploader import ImageUploader
from core.image_store import ImageStore
from core.database import init_database, get_database


# 全局变量存储初始化组件
app_state = {
    "llm": None,
    "skills": None,
    "agent_graph": None,
    "db": None,
    "initialized": False
}


def cleanup_expired_sessions():
    """清理过期会话（数据库方式）"""
    db = get_database()
    if db:
        deleted = db.cleanup_expired_sessions(SESSION_CONFIG["ttl_minutes"])
        if deleted > 0:
            logger.info("已清理 %d 个过期会话", deleted)


def get_or_create_session(session_id: Optional[str] = None) -> tuple:
    """获取或创建会话（数据库方式）"""
    cleanup_expired_sessions()
    
    db = get_database()
    if not db:
        raise RuntimeError("数据库未初始化")
    
    # 检查会话是否存在
    session_info = db.get_session(session_id) if session_id else None
    
    if session_info is None:
        # 检查是否超出最大会话数
        if db.get_session_count() >= SESSION_CONFIG["max_sessions"]:
            # 清理最早的一个会话
            db.cleanup_expired_sessions(0)  # 清理所有过期的
        
        session_id = session_id or str(uuid.uuid4())
        db.create_session(session_id, {"created_by": "api"})
        logger.info("创建新会话：%s，当前会话数：%d", session_id, db.get_session_count())
    
    # 更新最后使用时间
    db.update_session_last_used(session_id)
    
    # 创建 AgentGraph 实例（不保存历史，历史存储在数据库中）
    agent_graph = AgentGraph(
        skill_loader=app_state["skill_loader"],
        metadata_list=app_state["metadata_list"],
        llm=app_state["llm"],
        max_history=SESSION_CONFIG["max_history"],
        session_id=session_id,
        db=db
    )
    
    return session_id, agent_graph


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("=" * 50)
    logger.info("智能体广场系统启动中...（支持多轮对话 + 数据库存储）")
    logger.info("=" * 50)
    
    # [1/4] 初始化数据库
    logger.info("[1/4] 初始化数据库：%s", DATABASE_CONFIG['type'])
    try:
        db = init_database(DATABASE_CONFIG)
        logger.info("      ✓ 数据库初始化成功")
        app_state["db"] = db
    except Exception as e:
        logger.error("      ✗ 数据库初始化失败：%s", e, exc_info=True)
        app_state["db"] = None
    
    # [2/4] 初始化 LLM
    logger.info("[2/4] 初始化语言模型：%s - %s", LLM_CONFIG['provider'], LLM_CONFIG['model'])
    try:
        llm = get_llm(
            provider=LLM_CONFIG["provider"],
            model=LLM_CONFIG["model"],
            api_key=LLM_CONFIG.get("api_key"),
            base_url=LLM_CONFIG.get("base_url"),
            system_prompt=LLM_CONFIG.get("system_prompt")  # 使用统一的 system prompt
        )
        logger.info("      ✓ 语言模型初始化成功")
        app_state["llm"] = llm
    except Exception as e:
        logger.error("      ✗ 语言模型初始化失败：%s", e, exc_info=True)
        app_state["llm"] = None
    
    # [3/4] 加载技能元数据（轻量，不加载 tool.py）
    logger.info("[3/4] 扫描技能目录")
    skill_loader = SkillLoader()
    metadata_list = skill_loader.load_all_metadata()
    app_state["skill_loader"] = skill_loader
    app_state["metadata_list"] = metadata_list
    
    # [4/4] 不再创建默认 AgentGraph（每次请求独立创建，避免并发竞态）
    logger.info("[4/4] 跳过默认代理图初始化（按请求创建）")
    app_state["agent_graph"] = None
    
    app_state["initialized"] = True
    
    logger.info("=" * 50)
    logger.info("系统启动完成！")
    logger.info("=" * 50)
    logger.info("多轮对话配置:")
    logger.info("  - 数据库类型：%s", DATABASE_CONFIG['type'])
    if DATABASE_CONFIG['type'] == 'sqlite':
        logger.info("  - 数据库路径：%s", DATABASE_CONFIG['sqlite_path'])
    else:
        logger.info("  - 数据库地址：%s:%s/%s", DATABASE_CONFIG['mysql_host'], DATABASE_CONFIG['mysql_port'], DATABASE_CONFIG['mysql_database'])
    logger.info("  - 最大历史条数：%d", SESSION_CONFIG['max_history'])
    logger.info("  - 会话超时：%d 分钟", SESSION_CONFIG['ttl_minutes'])
    logger.info("  - 最大会话数：%d", SESSION_CONFIG['max_sessions'])
    
    yield
    
    logger.info("正在关闭系统...")
    app_state.clear()


app = FastAPI(
    title="智能体广场 API",
    description="智能体系统 HTTP 接口，支持流式和非流式输出",
    version="1.0.0",
    lifespan=lifespan
)


# ==================== 请求/响应模型 ====================

class ChatRequest(BaseModel):
    """聊天请求模型 - OpenAI 标准格式
    
    示例：
    ```json
    {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "请描述这些图片"},
                    {"type": "image_url", "image_url": {"url": "https://example.com/image1.jpg"}},
                    {"type": "image_url", "image_url": {"url": "https://example.com/image2.jpg"}}
                ]
            }
        ],
        "session_id": "your-session-id",
        "model": "qwen3.5-plus",
        "temperature": 0.7,
        "max_tokens": 2000,
        "enable_thinking": false
    }
    ```
    
    多轮对话说明：
    - 首次请求可不传 session_id，服务端会返回新的 session_id
    - 后续请求携带返回的 session_id，服务端会保留对话历史
    """
    messages: List[Dict[str, Any]] = Field(..., description="OpenAI 标准格式的消息列表，支持多模态内容")
    session_id: Optional[str] = Field(default=None, description="会话 ID，用于多轮对话。首次可不传，后续请求携带返回的 session_id")
    model: Optional[str] = Field(default=None, description="指定使用的模型（可选，用于覆盖默认配置）")
    temperature: Optional[float] = Field(default=None, description="温度参数（0-2，越高越随机）")
    max_tokens: Optional[int] = Field(default=None, description="最大生成 token 数")
    top_p: Optional[float] = Field(default=None, description="核采样参数")
    frequency_penalty: Optional[float] = Field(default=None, description="频率惩罚")
    presence_penalty: Optional[float] = Field(default=None, description="存在惩罚")
    enable_thinking: Optional[bool] = Field(default=None, description="是否启用思考模式")
    selected_skills: Optional[List[str]] = Field(default=None, description="用户指定的技能名称列表，指定后跳过自动路由，直接使用指定技能")


class ChatResponse(BaseModel):
    """聊天响应模型"""
    query: str = Field(description="用户查询")
    session_id: str = Field(description="会话 ID")
    result: dict = Field(description="执行结果")
    final_result: str = Field(description="最终结果摘要")


class SessionResponse(BaseModel):
    """会话响应模型"""
    session_id: str = Field(description="会话 ID")
    history_count: int = Field(description="历史消息数")
    created_at: str = Field(description="创建时间")


# ==================== 辅助函数 ====================

def _collect_llm_kwargs(request: ChatRequest) -> dict:
    """从 ChatRequest 中收集非 None 的 OpenAI 兼容参数"""
    kwargs = {}
    for field in ("temperature", "max_tokens", "top_p", "frequency_penalty", "presence_penalty"):
        value = getattr(request, field, None)
        if value is not None:
            kwargs[field] = value
    return kwargs


async def generate_stream_chunks_with_messages(
    messages: List[Dict[str, Any]],
    session_id: Optional[str] = None,
    custom_llm=None,
    enable_thinking: Optional[bool] = None,
    selected_skills: Optional[List[str]] = None
) -> AsyncGenerator[str, None]:
    """
    生成流式数据块 - 支持 OpenAI 标准 messages 格式
    
    Args:
        messages: OpenAI 标准格式的消息列表
        session_id: 会话 ID
        custom_llm: 自定义 LLM 实例
        enable_thinking: 是否启用思考模式
        selected_skills: 用户指定的技能名称列表（可选）
        
    Yields:
        JSON 字符串格式的流式数据块
    """
    logger.info("[generate_stream_chunks_with_messages] enable_thinking=%s", enable_thinking)
    
    # 处理消息中的图片 URL，将内网图片转换为 base64
    processed_messages = messages
    storage_messages = messages
    has_images = False
    for msg in messages:
        if msg.get("role") == "user":
            content = msg.get("content", [])
            if isinstance(content, list):
                for item in content:
                    if item.get("type") == "image_url":
                        has_images = True
                        break
    
    if has_images:
        try:
            logger.info("[generate_stream_chunks_with_messages] 开始处理消息中的图片 URL...")
            processed_messages = await ImageUploader.process_messages(messages, timeout=30.0)
            logger.info("[generate_stream_chunks_with_messages] 图片 URL 处理完成")
        except Exception as e:
            logger.error("[generate_stream_chunks_with_messages] 图片处理失败：%s: %s", type(e).__name__, e, exc_info=True)
            # 图片处理失败，返回错误信息给用户（返回 JSON 字符串）
            error_msg = f"图片处理失败：{type(e).__name__}: {e}。请检查图片 URL 是否可访问。"
            yield f"data: {json.dumps({'type': 'error', 'message': error_msg}, ensure_ascii=False)}\n\n"
            return
    else:
        processed_messages = messages
    
    # 获取或创建会话
    actual_session_id, agent_graph = get_or_create_session(session_id)
    if has_images:
        db = get_database()
        if db:
            storage_messages = ImageStore.store_processed_messages(
                db,
                actual_session_id,
                messages,
                processed_messages
            )
    
    # 保存原始模型
    original_llm = agent_graph.llm
    
    # 如果有自定义 LLM，替换当前会话的模型
    if custom_llm:
        agent_graph.llm = custom_llm
        agent_graph.executor.llm = custom_llm
        agent_graph.router.llm = custom_llm
        logger.info("[generate_stream_chunks_with_messages] 已设置 custom_llm, custom_llm.model=%s", custom_llm.model)
    
    try:
        async for chunk in agent_graph.run_stream_with_messages(
            processed_messages,
            enable_thinking=enable_thinking,
            storage_messages=storage_messages,
            selected_skills=selected_skills
        ):
            # 确保所有 yield 的都是 JSON 字符串
            if isinstance(chunk, dict):
                chunk["session_id"] = actual_session_id
            yield f"data: {json.dumps(chunk, ensure_ascii=False, default=str)}\n\n"
    except Exception as e:
        # 记录详细错误信息
        import traceback
        error_traceback = traceback.format_exc()
        logger.error("[generate_stream_chunks_with_messages] 错误：%s", e, exc_info=True)
        
        # 特殊处理：如果错误消息是 "0"，添加更多上下文
        error_message = str(e)
        if error_message == "0":
            error_message = f"数据库操作错误：{e} (类型：{type(e).__name__})"
        
        error_data = json.dumps({"type": "error", "message": error_message, "session_id": actual_session_id}, ensure_ascii=False, default=str)
        yield f"data: {error_data}\n\n"
    finally:
        # 恢复原始模型
        agent_graph.llm = original_llm


def format_response(state_dict: dict) -> dict:
    """格式化响应数据"""
    return {
        "query": state_dict.get("user_input", ""),
        "result": state_dict,
        "final_result": state_dict.get("final_result", ""),
        "plan": state_dict.get("plan", ""),
        "steps": state_dict.get("steps", []),
        "tool_calls": state_dict.get("tool_calls", []),
        "tool_results": state_dict.get("tool_results", []),
        "thinking_content": state_dict.get("context", {}).get("thinking_content", None)
    }


# ==================== API 路由 ====================

@app.get("/api")
async def root():
    """根路径"""
    return {
        "name": "智能体广场 API",
        "version": "1.0.0",
        "status": "running" if app_state["initialized"] else "initializing",
        "endpoints": {
            "chat": "/api/chat",
            "chat_stream": "/api/chat/stream",
            "health": "/health",
            "skills": "/api/skills",
            "static": "/static/index.html"
        }
    }


@app.get("/health")
async def health_check():
    """健康检查"""
    return {
        "status": "healthy" if app_state["initialized"] else "initializing",
        "llm": "ready" if app_state["llm"] else "not ready",
        "skills_count": len(app_state.get("metadata_list") or [])
    }


def _create_llm_for_request(
    model_name: Optional[str] = None,
    enable_thinking: Optional[bool] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    top_p: Optional[float] = None,
    frequency_penalty: Optional[float] = None,
    presence_penalty: Optional[float] = None,
    **kwargs
):
    """
    为请求创建 LLM 实例
    
    Args:
        model_name: 用户指定的模型名称（可选）
        enable_thinking: 是否启用思考模式（可选）
        temperature: 温度参数（可选）
        max_tokens: 最大 token 数（可选）
        top_p: 核采样参数（可选）
        frequency_penalty: 频率惩罚（可选）
        presence_penalty: 存在惩罚（可选）
        **kwargs: 其他 OpenAI 兼容参数
        
    Returns:
        LLM 实例
    """
    config = LLM_CONFIG.copy()
    if model_name:
        config["model"] = model_name
        logger.info("[_create_llm_for_request] 使用用户指定的模型：%s", model_name)
    else:
        logger.info("[_create_llm_for_request] 使用默认模型：%s", config['model'])
    
    # 构建 LLM 参数，只传递非 None 的值
    llm_params = {
        "provider": config["provider"],
        "model": config["model"],
        "api_key": config.get("api_key"),
        "base_url": config.get("base_url"),
        "system_prompt": config.get("system_prompt"),  # 使用统一的 system prompt
    }
    
    # 只在用户明确传入时才传递参数，避免 None 覆盖默认值
    if enable_thinking is not None:
        llm_params["enable_thinking"] = enable_thinking
    if temperature is not None:
        llm_params["temperature"] = temperature
    if max_tokens is not None:
        llm_params["max_tokens"] = max_tokens
    if top_p is not None:
        llm_params["top_p"] = top_p
    if frequency_penalty is not None:
        llm_params["frequency_penalty"] = frequency_penalty
    if presence_penalty is not None:
        llm_params["presence_penalty"] = presence_penalty
    
    # 添加其他 kwargs（只传递非 None 的值）
    for key, value in kwargs.items():
        if value is not None:
            llm_params[key] = value
    
    logger.info("[_create_llm_for_request] 创建 LLM: %s", llm_params)
    
    return get_llm(**llm_params)


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    聊天接口（非流式）- OpenAI 标准格式
    
    多轮对话支持：
    - 首次请求不提供 session_id，返回新 session_id
    - 后续请求携带返回的 session_id，可继续对话
    
    多模态支持：
    - 使用 OpenAI 标准 messages 格式，content 支持多模态列表
    - 支持传入多张图片
    
    示例：
    ```json
    {
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": "请描述这些图片"},
                {"type": "image_url", "image_url": {"url": "https://example.com/image1.jpg"}},
                {"type": "image_url", "image_url": {"url": "https://example.com/image2.jpg"}}
            ]
        }]
    }
    ```
    """
    if not app_state["initialized"]:
        raise HTTPException(status_code=503, detail="系统正在初始化中")
    
    try:
        # 使用 request.session_id 获取会话 ID（现在 session_id 是 ChatRequest 的字段）
        actual_session_id, agent_graph = get_or_create_session(request.session_id)
        
        # 从 messages 中提取用户查询（用于响应）
        query_text = ""
        for msg in request.messages:
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, list):
                    for item in content:
                        if item.get("type") == "text":
                            query_text += item.get("text", "") + " "
                elif isinstance(content, str):
                    query_text = content
                break
        
        # 收集 OpenAI 兼容参数
        llm_kwargs = _collect_llm_kwargs(request)
        
        # 处理消息中的图片 URL，将内网图片转换为 base64
        processed_messages = request.messages
        storage_messages = request.messages
        try:
            logger.info("[chat] 开始处理消息中的图片 URL")
            processed_messages = await ImageUploader.process_messages(request.messages, timeout=30.0)
            logger.info("[chat] 图片 URL 处理完成")
        except Exception as e:
            logger.error("[chat] 图片处理警告：%s: %s", type(e).__name__, e, exc_info=True)
            # 图片处理失败不影响继续执行，使用原始消息
        
        # 如果指定了模型或其他参数，创建临时 LLM 实例
        if processed_messages is not request.messages:
            db = get_database()
            if db:
                storage_messages = ImageStore.store_processed_messages(
                    db,
                    actual_session_id,
                    request.messages,
                    processed_messages
                )

        if request.model or llm_kwargs:
            llm = _create_llm_for_request(
                request.model,
                enable_thinking=request.enable_thinking,
                **llm_kwargs
            )
            original_llm = agent_graph.llm
            original_executor_llm = agent_graph.executor.llm
            original_router_llm = agent_graph.router.llm
            agent_graph.llm = llm
            agent_graph.executor.llm = llm
            agent_graph.router.llm = llm
            
            try:
                result = await agent_graph.run_with_messages(
                    processed_messages,
                    enable_thinking=request.enable_thinking,
                    storage_messages=storage_messages,
                    selected_skills=request.selected_skills
                )
            finally:
                agent_graph.llm = original_llm
                agent_graph.executor.llm = original_executor_llm
                agent_graph.router.llm = original_router_llm
        else:
            result = await agent_graph.run_with_messages(
                processed_messages,
                enable_thinking=request.enable_thinking,
                storage_messages=storage_messages,
                selected_skills=request.selected_skills
            )
        
        formatted_result = format_response(result)
        return ChatResponse(
            query=query_text.strip(),
            session_id=actual_session_id,
            result=formatted_result,
            final_result=formatted_result.get("final_result", "")
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"处理失败：{str(e)}")


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest):
    """
    聊天接口（流式）- OpenAI 标准格式
    
    使用 Server-Sent Events (SSE) 实时返回处理进度和结果
    
    多轮对话支持：
    - 首次请求不提供 session_id，返回新 session_id
    - 后续请求携带返回的 session_id，可继续对话
    
    多模态支持：
    - 使用 OpenAI 标准 messages 格式，content 支持多模态列表
    - 支持传入多张图片
    
    示例：
    ```json
    {
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": "请描述这些图片"},
                {"type": "image_url", "image_url": {"url": "https://example.com/image1.jpg"}},
                {"type": "image_url", "image_url": {"url": "https://example.com/image2.jpg"}}
            ]
        }],
        "stream": true
    }
    ```
    """
    if not app_state["initialized"]:
        raise HTTPException(status_code=503, detail="系统正在初始化中")
    
    # 收集 OpenAI 兼容参数
    llm_kwargs = _collect_llm_kwargs(request)
    
    # 如果指定了模型或其他参数，创建独立的 LLM 实例
    custom_llm = None
    if request.model or llm_kwargs:
        custom_llm = _create_llm_for_request(
            request.model,
            enable_thinking=request.enable_thinking,
            **llm_kwargs
        )
    
    return StreamingResponse(
        generate_stream_chunks_with_messages(
            request.messages,
            session_id=request.session_id,
            custom_llm=custom_llm,
            enable_thinking=request.enable_thinking,
            selected_skills=request.selected_skills
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@app.get("/api/skills")
async def list_skills():
    """获取可用技能列表（元数据）"""
    if not app_state["initialized"]:
        raise HTTPException(status_code=503, detail="系统正在初始化中")

    metadata_list = app_state["metadata_list"]
    return {
        "skills": [
            {
                "name": meta.name,
                "description": meta.description,
                "keywords": meta.keywords,
            }
            for meta in metadata_list
        ]
    }


@app.post("/api/session/create")
async def create_session():
    """创建新会话"""
    if not app_state["initialized"]:
        raise HTTPException(status_code=503, detail="系统正在初始化中")
    
    session_id, agent_graph = get_or_create_session(None)
    db = get_database()
    history_count = db.get_messages_count(session_id) if db else 0
    session_info = db.get_session(session_id) if db else {}
    
    return SessionResponse(
        session_id=session_id,
        history_count=history_count,
        created_at=session_info.get("created_at", datetime.now().isoformat())
    )


@app.get("/api/session/{session_id}")
async def get_session(session_id: str):
    """获取会话信息"""
    if not app_state["initialized"]:
        raise HTTPException(status_code=503, detail="系统正在初始化中")
    
    db = get_database()
    if not db:
        raise HTTPException(status_code=500, detail="数据库未初始化")
    
    session_info = db.get_session(session_id)
    if not session_info:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    history = db.get_messages(session_id, limit=SESSION_CONFIG["max_history"])
    return {
        "session_id": session_id,
        "history_count": len(history),
        "history": history,
        "created_at": session_info.get("created_at", "")
    }


@app.delete("/api/session/{session_id}")
async def delete_session(session_id: str):
    """删除会话"""
    if not app_state["initialized"]:
        raise HTTPException(status_code=503, detail="系统正在初始化中")
    
    db = get_database()
    if not db:
        raise HTTPException(status_code=500, detail="数据库未初始化")
    
    session_info = db.get_session(session_id)
    if not session_info:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    db.delete_session(session_id)
    return {"message": "会话已删除", "session_id": session_id}


@app.post("/api/session/{session_id}/clear")
async def clear_session_history(session_id: str):
    """清空会话历史"""
    if not app_state["initialized"]:
        raise HTTPException(status_code=503, detail="系统正在初始化中")
    
    db = get_database()
    if not db:
        raise HTTPException(status_code=500, detail="数据库未初始化")
    
    session_info = db.get_session(session_id)
    if not session_info:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    db.clear_history(session_id)
    return {"message": "会话历史已清空", "session_id": session_id}


@app.get("/api/db/stats")
async def get_db_stats():
    """获取数据库统计信息"""
    if not app_state["initialized"]:
        raise HTTPException(status_code=503, detail="系统正在初始化中")
    
    db = get_database()
    if not db:
        raise HTTPException(status_code=500, detail="数据库未初始化")
    
    return db.get_stats()


# 挂载静态文件目录
try:
    app.mount("/static", StaticFiles(directory="static"), name="static")
    
    @app.get("/")
    async def serve_index():
        """提供前端页面"""
        return FileResponse("static/index.html")
except Exception as e:
    logger.warning("无法挂载静态文件目录：%s", e)


if __name__ == "__main__":
    uvicorn.run(
        "api:app",
        host="0.0.0.0",
        port=18000,
        reload=False,
        log_level="info"
    )
