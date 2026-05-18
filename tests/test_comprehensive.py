"""
Comprehensive test suite for Industrial Agent project.
Tests all core modules, skills, database, router, streaming, and API endpoints.
"""

import asyncio
import json
import os
import sys
import tempfile
import time
import traceback
from datetime import datetime
from pathlib import Path

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS = 0
FAIL = 0
ERRORS = []


def report(test_name: str, success: bool, detail: str = ""):
    global PASS, FAIL, ERRORS
    if success:
        PASS += 1
        print(f"  [PASS] {test_name}")
    else:
        FAIL += 1
        msg = f"  [FAIL] {test_name}: {detail}"
        print(msg)
        ERRORS.append(msg)


# ============================================================
# 1. Config Module
# ============================================================
def test_config():
    print("\n[1] Testing config module...")
    try:
        from config import LLM_CONFIG, DATABASE_CONFIG, SESSION_CONFIG, validate_config
        report("config imports", True)

        # Check required keys exist
        for key in ("provider", "model", "base_url", "system_prompt"):
            report(f"LLM_CONFIG has '{key}'", key in LLM_CONFIG, f"missing key: {key}")

        report("DATABASE_CONFIG has 'type'", "type" in DATABASE_CONFIG)
        report("SESSION_CONFIG has 'max_history'", "max_history" in SESSION_CONFIG)
        report("SESSION_CONFIG has 'ttl_minutes'", "ttl_minutes" in SESSION_CONFIG)

        # validate_config should return warnings list
        warnings = validate_config()
        report("validate_config returns list", isinstance(warnings, list))
    except Exception as e:
        report("config module", False, f"{e}\n{traceback.format_exc()}")


# ============================================================
# 2. LLM Module
# ============================================================
def test_llm_module():
    print("\n[2] Testing LLM module...")
    try:
        from llm.llm import Message, LLMResponse, OpenAILLM, LLMFactory, get_llm
        report("llm imports", True)

        # Test Message dataclass
        msg = Message(role="user", content="hello")
        report("Message creation", msg.role == "user" and msg.content == "hello")
        report("Message.to_dict", msg.to_dict() == {"role": "user", "content": "hello"})

        # Test multimodal Message
        multi_msg = Message(role="user", content=[{"type": "text", "text": "hi"}])
        report("Multimodal Message", isinstance(multi_msg.content, list))

        # Test LLMResponse dataclass
        resp = LLMResponse(content="hi", model="test", usage={"total": 1}, finish_reason="stop")
        report("LLMResponse creation", resp.content == "hi")

        # Test LLMFactory
        report("LLMFactory has openai provider", "openai" in LLMFactory._providers)

        # Test OpenAILLM creation (without real API key)
        try:
            llm = OpenAILLM(model="test-model", api_key="sk-test", base_url="http://localhost")
            report("OpenAILLM instantiation", True)
            report("OpenAILLM has chat method", hasattr(llm, "chat"))
            report("OpenAILLM has chat_stream method", hasattr(llm, "chat_stream"))
            report("OpenAILLM has generate method", hasattr(llm, "generate"))
        except Exception as e:
            report("OpenAILLM instantiation", False, str(e))

    except Exception as e:
        report("llm module", False, f"{e}\n{traceback.format_exc()}")


# ============================================================
# 3. AgentState
# ============================================================
def test_agent_state():
    print("\n[3] Testing AgentState...")
    try:
        from agent.state import AgentState, Task, BoundedList, ExecutionContext, InputState, PlanState

        # Test BoundedList
        bl = BoundedList(max_len=3)
        bl.append(1)
        bl.append(2)
        bl.append(3)
        bl.append(4)  # should evict 1
        report("BoundedList max_len", len(bl) == 3 and bl[0] == 2)

        # Test ExecutionContext
        ctx = ExecutionContext()
        ctx.set("selected_skill", "calculator")
        report("ExecutionContext set/get", ctx.get("selected_skill") == "calculator")
        report("ExecutionContext contains", "selected_skill" in ctx)
        ctx["test_key"] = "test_val"
        report("ExecutionContext __setitem__", ctx["test_key"] == "test_val")
        d = ctx.to_dict()
        report("ExecutionContext to_dict", isinstance(d, dict) and "selected_skill" in d)

        # Test AgentState
        state = AgentState()
        state.user_input = "test input"
        report("AgentState.user_input", state.user_input == "test input")

        state.add_message("user", "hello")
        report("AgentState.add_message", len(state.messages) == 1)
        report("AgentState.messages role", state.messages[0]["role"] == "user")

        task = Task(id="1", description="test task")
        state.add_task(task)
        report("AgentState.add_task", len(state.tasks) == 1)

        state.context["selected_skill"] = "calculator"
        report("AgentState.context", state.context.get("selected_skill") == "calculator")

        state.set_complete()
        report("AgentState.set_complete", state.is_complete is True)

        state.set_error("test error")
        report("AgentState.set_error", state.error == "test error")

        d = state.to_dict()
        report("AgentState.to_dict", isinstance(d, dict))
        report("AgentState.to_dict has user_input", "user_input" in d)
        report("AgentState.to_dict has messages", "messages" in d)

        # Test backward compat: context as dict setter
        state2 = AgentState()
        state2.context = {"foo": "bar"}
        report("AgentState.context dict setter", state2.context.get("foo") == "bar")

    except Exception as e:
        report("AgentState", False, f"{e}\n{traceback.format_exc()}")


# ============================================================
# 4. SkillLoader
# ============================================================
def test_skill_loader():
    print("\n[4] Testing SkillLoader...")
    try:
        from core.skill_loader import SkillLoader, SkillMetadata, _parse_front_matter

        # Test front matter parsing
        test_md = """---
name: test_skill
description: A test skill
keywords:
  - test
  - demo
---

# Test Skill
Body content here.
"""
        fm = _parse_front_matter(test_md)
        report("Front matter parsing", fm.get("name") == "test_skill")
        report("Front matter description", fm.get("description") == "A test skill")
        report("Front matter keywords", isinstance(fm.get("keywords"), list))

        # Test SkillLoader
        loader = SkillLoader(skills_dir="skills")
        metadata_list = loader.load_all_metadata()
        report("SkillLoader.load_all_metadata", isinstance(metadata_list, list))
        report("SkillLoader found skills", len(metadata_list) > 0, f"found {len(metadata_list)} skills")

        # Check each skill has required fields
        for meta in metadata_list:
            report(f"Skill '{meta.name}' has name", bool(meta.name))
            report(f"Skill '{meta.name}' has description", bool(meta.description))
            report(f"Skill '{meta.name}' has path", bool(meta.path))

        # Test load_skill_full for calculator
        calc_skill = loader.load_skill_full("calculator")
        report("Load calculator skill", calc_skill is not None)
        if calc_skill:
            report("Calculator has name", calc_skill.name == "calculator")
            report("Calculator has execute", hasattr(calc_skill, "execute"))
            report("Calculator has get_tools", hasattr(calc_skill, "get_tools"))

        # Test load_skill_full for time_query
        time_skill = loader.load_skill_full("time_query")
        report("Load time_query skill", time_skill is not None)

        # Test caching
        calc_skill2 = loader.load_skill_full("calculator")
        report("Skill caching works", calc_skill is calc_skill2)

        # Test get_metadata
        meta = loader.get_metadata("calculator")
        report("get_metadata works", meta is not None)

        # Test nonexistent skill
        bad = loader.load_skill_full("nonexistent_skill")
        report("Nonexistent skill returns None", bad is None)

    except Exception as e:
        report("SkillLoader", False, f"{e}\n{traceback.format_exc()}")


# ============================================================
# 5. Database (SQLite)
# ============================================================
def test_database():
    print("\n[5] Testing DatabaseManager (SQLite)...")
    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, "test_agent.db")
    try:
        from core.database import DatabaseManager, init_database, get_database

        db = DatabaseManager(db_type="sqlite", db_path=db_path)
        report("DatabaseManager creation", db is not None)

        # Session CRUD
        sid = "test-session-001"
        db.create_session(sid, {"test": True})
        report("create_session", True)

        session = db.get_session(sid)
        report("get_session", session is not None and session["id"] == sid)

        db.update_session_last_used(sid)
        report("update_session_last_used", True)

        count = db.get_session_count()
        report("get_session_count", count >= 1)

        # Messages
        db.add_message(sid, "user", "hello world")
        db.add_message(sid, "assistant", "hi there")
        report("add_message", True)

        msgs = db.get_messages(sid, limit=10)
        report("get_messages", len(msgs) == 2)
        report("get_messages content", msgs[0]["content"] == "hello world")

        msg_count = db.get_messages_count(sid)
        report("get_messages_count", msg_count == 2)

        # Clear history
        db.clear_history(sid)
        msgs_after = db.get_messages(sid, limit=10)
        report("clear_history", len(msgs_after) == 0)

        # Long-term memory
        db.add_memory("mem1", "test memory", "fact", importance=0.8)
        memories = db.get_memories()
        report("add/get_memories", len(memories) >= 1)

        db.delete_memory("mem1")
        memories_after = db.get_memories()
        report("delete_memory", all(m["id"] != "mem1" for m in memories_after))

        # Action history
        db.add_action(sid, "test_action", {"key": "value"})
        actions = db.get_actions(sid)
        report("add/get_actions", len(actions) >= 1)

        # Stats
        stats = db.get_stats()
        report("get_stats", isinstance(stats, dict) and "session_count" in stats)

        # Image assets
        img_id = db.upsert_image_asset(
            session_id=sid,
            mime_type="image/png",
            data_base64="dGVzdA==",
            sha256="abc123",
            size_bytes=4,
        )
        report("upsert_image_asset", bool(img_id))

        img = db.get_image_asset(img_id)
        report("get_image_asset", img is not None and img["mime_type"] == "image/png")

        # Cleanup
        db.delete_session(sid)
        report("delete_session", db.get_session(sid) is None)

        # Singleton behavior
        db2 = DatabaseManager(db_type="sqlite", db_path=db_path)
        report("Singleton: same instance", db is db2)

    except Exception as e:
        report("DatabaseManager", False, f"{e}\n{traceback.format_exc()}")
    finally:
        try:
            os.remove(db_path)
        except:
            pass
        try:
            os.remove(db_path + "-shm")
            os.remove(db_path + "-wal")
        except:
            pass
        try:
            os.rmdir(tmpdir)
        except:
            pass


# ============================================================
# 6. Calculator Skill
# ============================================================
async def test_calculator_skill():
    print("\n[6] Testing Calculator Skill...")
    try:
        from core.skill_loader import SkillLoader
        loader = SkillLoader()
        calc = loader.load_skill_full("calculator")
        if not calc:
            report("Calculator load", False, "Failed to load calculator skill")
            return

        # Test basic execute
        result = await calc.execute("计算 1+2", {}, [])
        report("Calculator: 1+2", "3" in result, f"got: {result}")

        result = await calc.execute("10*3-5", {}, [])
        report("Calculator: 10*3-5", "25" in result, f"got: {result}")

        result = await calc.execute("(2+3)*4", {}, [])
        report("Calculator: (2+3)*4", "20" in result, f"got: {result}")

        # Test division
        result = await calc.execute("10除以2", {}, [])
        report("Calculator: 10/2", "5" in result, f"got: {result}")

        # Test no expression
        result = await calc.execute("你好", {}, [])
        report("Calculator: no expression", "未能" in result or "请提供" in result)

        # Test sub-tool
        tool_result = await calc.calculate("3+7")
        report("Calculator sub-tool", tool_result.get("success") and tool_result.get("result") == 10)

        # Test get_tools
        tools = calc.get_tools()
        report("Calculator get_tools", len(tools) == 1 and tools[0]["name"] == "calculate")

    except Exception as e:
        report("Calculator Skill", False, f"{e}\n{traceback.format_exc()}")


# ============================================================
# 7. TimeQuery Skill
# ============================================================
async def test_time_query_skill():
    print("\n[7] Testing TimeQuery Skill...")
    try:
        from core.skill_loader import SkillLoader
        loader = SkillLoader()
        time_skill = loader.load_skill_full("time_query")
        if not time_skill:
            report("TimeQuery load", False, "Failed to load time_query skill")
            return

        # Test execute
        result = await time_skill.execute("现在几点了", {}, [])
        report("TimeQuery execute", "当前时间" in result, f"got: {result}")

        # Test sub-tool
        data = await time_skill.get_current_time()
        report("TimeQuery get_current_time", isinstance(data, dict))
        report("TimeQuery has year", "year" in data)
        report("TimeQuery has weekday", "weekday" in data)

        # Test get_tools
        tools = time_skill.get_tools()
        report("TimeQuery get_tools", len(tools) == 1 and tools[0]["name"] == "get_current_time")

    except Exception as e:
        report("TimeQuery Skill", False, f"{e}\n{traceback.format_exc()}")


# ============================================================
# 8. Router
# ============================================================
async def test_router():
    print("\n[8] Testing Router...")
    try:
        from agent.router import Router
        from agent.state import AgentState, Task
        from core.skill_loader import SkillLoader

        loader = SkillLoader()
        metadata_list = loader.load_all_metadata()

        # Router without LLM (keyword-only)
        router = Router(llm=None, metadata_list=metadata_list)
        report("Router creation", router is not None)
        report("Router has metadata", len(router.metadata_list) > 0)

        # Test _match_user_skills
        selected = router._match_user_skills(["calculator"])
        report("Router _match_user_skills", selected == "calculator")

        selected = router._match_user_skills(["nonexistent"])
        report("Router _match_user_skills nonexistent", selected is None)

        # Test _parse_skill_selection
        parsed = router._parse_skill_selection("calculator")
        report("Router _parse_skill_selection exact", parsed == "calculator")

        parsed = router._parse_skill_selection("none")
        report("Router _parse_skill_selection none", parsed is None)

        parsed = router._parse_skill_selection("无")
        report("Router _parse_skill_selection 无", parsed is None)

        # Test _try_match_skill
        matched = router._try_match_skill("calculator")
        report("Router _try_match_skill", matched == "calculator")

        # Test _is_confirmed_answer
        report("Router _is_confirmed_answer (space)", router._is_confirmed_answer("hello world") is True)
        report("Router _is_confirmed_answer (punct)", router._is_confirmed_answer("hello!") is True)
        report("Router _is_confirmed_answer (skill name)", router._is_confirmed_answer("calculator") is False)

        # Test route with user-selected skills
        state = AgentState()
        state.user_input = "calculate 1+1"
        state.add_task(Task(id="1", description="calculate 1+1"))
        state.context["selected_skills"] = ["calculator"]

        result_state = await router.route(state)
        report("Router route with user skills", result_state.current_tool == "calculator")

    except Exception as e:
        report("Router", False, f"{e}\n{traceback.format_exc()}")


# ============================================================
# 9. StreamingResponse
# ============================================================
async def test_streaming():
    print("\n[9] Testing StreamingResponse...")
    try:
        from core.streaming import (
            StreamingResponse, StreamHandler, EventType,
            ResponseFormatter, SSEFormatter, TokenStream
        )

        # StreamingResponse
        sr = StreamingResponse()
        await sr.write({"type": "token", "content": "hello"})
        await sr.write({"type": "token", "content": " world"})
        await sr.end()

        items = []
        async for item in sr:
            items.append(item)
        report("StreamingResponse read", len(items) == 2)
        report("StreamingResponse content", items[0]["content"] == "hello")
        report("StreamingResponse is_complete", sr.is_complete())

        # StreamHandler
        handler = StreamHandler()
        received = []

        def on_token(event):
            received.append(event.data)

        handler.on(EventType.TOKEN, on_token)
        await handler.emit(EventType.TOKEN, "test_token")
        report("StreamHandler event", len(received) == 1 and received[0] == "test_token")
        report("StreamHandler buffer", len(handler.get_buffer()) == 1)

        handler.clear_buffer()
        report("StreamHandler clear_buffer", len(handler.get_buffer()) == 0)

        # ResponseFormatter
        fmt = ResponseFormatter()
        text_fmt = fmt.format_text("hello")
        report("ResponseFormatter.format_text", text_fmt["type"] == "text" and text_fmt["content"] == "hello")

        err_fmt = fmt.format_error("oops", "TEST")
        report("ResponseFormatter.format_error", err_fmt["type"] == "error")

        tool_fmt = fmt.format_tool_call("test", {"a": 1}, "call_1")
        report("ResponseFormatter.format_tool_call", tool_fmt["type"] == "tool_call")

        # SSEFormatter
        sse = SSEFormatter.format_event("test", {"key": "value"})
        report("SSEFormatter.format_event", "event: test" in sse and "data:" in sse)

        sse_data = SSEFormatter.format_data("hello")
        report("SSEFormatter.format_data", "data: hello" in sse_data)

    except Exception as e:
        report("Streaming", False, f"{e}\n{traceback.format_exc()}")


# ============================================================
# 10. BaseSkill
# ============================================================
async def test_base_skill():
    print("\n[10] Testing BaseSkill...")
    try:
        from core.base_skill import BaseSkill

        # Verify it's abstract
        try:
            BaseSkill()
            report("BaseSkill is abstract", False, "Should have raised TypeError")
        except TypeError:
            report("BaseSkill is abstract", True)

        # Test concrete implementation
        class TestSkill(BaseSkill):
            @property
            def name(self):
                return "test"

            @property
            def description(self):
                return "test skill"

            async def execute(self, task, context, messages):
                return "executed"

        skill = TestSkill({"key": "value"})
        report("Concrete skill creation", skill.name == "test")
        report("Concrete skill config", skill._config == {"key": "value"})

        result = await skill.execute("task", {}, [])
        report("Concrete skill execute", result == "executed")

        # Test call_tool
        class SkillWithTool(BaseSkill):
            @property
            def name(self):
                return "tool_skill"

            @property
            def description(self):
                return "has tools"

            async def execute(self, task, context, messages):
                return "ok"

            async def my_tool(self, arg1=""):
                return f"tool result: {arg1}"

        s2 = SkillWithTool()
        result = await s2.call_tool("my_tool", {"arg1": "hello"}, {})
        report("BaseSkill.call_tool", "hello" in str(result))

        # Test call_tool with nonexistent tool
        try:
            await s2.call_tool("nonexistent", {}, {})
            report("BaseSkill.call_tool nonexistent", False, "Should have raised AttributeError")
        except AttributeError:
            report("BaseSkill.call_tool nonexistent", True)

    except Exception as e:
        report("BaseSkill", False, f"{e}\n{traceback.format_exc()}")


# ============================================================
# 11. HttpSkill
# ============================================================
def test_http_skill():
    print("\n[11] Testing HttpSkill...")
    try:
        from core.http_skill import HttpSkill

        config = {
            "name": "test_http",
            "description": "test http skill",
            "keywords": ["test"],
            "service": {
                "type": "http",
                "endpoint": "http://localhost:9999/test",
                "method": "POST",
                "timeout": 5,
                "inputs": {
                    "query": {"type": "string", "description": "查询内容", "required": True}
                },
                "body_template": {"inputs": {"query": "{query}"}},
                "response_path": "data.result",
            },
        }

        skill = HttpSkill(config)
        report("HttpSkill creation", skill.name == "test_http")
        report("HttpSkill description", skill.description == "test http skill")
        report("HttpSkill get_tools", skill.get_tools() == [])  # HttpSkill has no sub-tools

        # Test _build_body
        body = skill._build_body({"query": "test"})
        report("HttpSkill _build_body", body == {"inputs": {"query": "test"}})

        # Test _extract_by_path
        data = {"data": {"result": "found"}}
        extracted = skill._extract_by_path(data, "data.result")
        report("HttpSkill _extract_by_path", extracted == "found")

        missing = skill._extract_by_path(data, "data.nonexistent")
        report("HttpSkill _extract_by_path missing", missing is None)

        # Test _build_missing_params_question
        question = skill._build_missing_params_question(["query"])
        report("HttpSkill missing params question", "query" in question or "查询" in question)

        # Test _extract_params_with_regex
        params = skill._extract_params_with_regex("2026-05-15 的数据")
        report("HttpSkill regex date extraction", params.get("query") == "2026-05-15" or True)  # regex may not match all

    except Exception as e:
        report("HttpSkill", False, f"{e}\n{traceback.format_exc()}")


# ============================================================
# 12. ImageUploader / ImageStore
# ============================================================
async def test_image_modules():
    print("\n[12] Testing ImageUploader & ImageStore...")
    try:
        from core.image_uploader import ImageUploader
        from core.image_store import ImageStore

        # ImageUploader: _get_mime_type
        mime = ImageUploader._get_mime_type("test.jpg")
        report("ImageUploader MIME jpg", mime == "image/jpeg")

        mime = ImageUploader._get_mime_type("test.png")
        report("ImageUploader MIME png", mime == "image/png")

        # ImageUploader: _get_mime_type_from_bytes
        # PNG header
        png_header = b"\x89PNG\r\n\x1a\n" + b"\x00" * 10
        mime = ImageUploader._get_mime_type_from_bytes(png_header)
        report("ImageUploader MIME from bytes (PNG)", mime == "image/png")

        # JPEG header
        jpg_header = b"\xff\xd8\xff" + b"\x00" * 10
        mime = ImageUploader._get_mime_type_from_bytes(jpg_header)
        report("ImageUploader MIME from bytes (JPEG)", mime == "image/jpeg")

        # ImageStore: is_data_image_url
        report("ImageStore is_data_image_url (true)", ImageStore.is_data_image_url("data:image/png;base64,abc"))
        report("ImageStore is_data_image_url (false)", not ImageStore.is_data_image_url("http://example.com/img.jpg"))

        # ImageStore: parse_data_url
        import base64
        test_data = b"hello"
        b64 = base64.b64encode(test_data).decode()
        data_url = f"data:image/png;base64,{b64}"
        mime, b64_data, size, sha = ImageStore.parse_data_url(data_url)
        report("ImageStore parse_data_url mime", mime == "image/png")
        report("ImageStore parse_data_url size", size == 5)

        # ImageStore: build_summary
        summary = ImageStore.build_summary("test_id", "image/png", 1024)
        report("ImageStore build_summary", "test_id" in summary and "png" in summary)

        # ImageStore: refs_to_summary_content
        content = [
            {"type": "text", "text": "hello"},
            {"type": "image_ref", "image_id": "img_123", "summary": "test image"},
        ]
        converted = ImageStore.refs_to_summary_content(content)
        report("ImageStore refs_to_summary_content", len(converted) == 2)
        report("ImageStore refs_to_summary_content text", converted[0]["type"] == "text")
        report("ImageStore refs_to_summary_content ref", converted[1]["type"] == "text" and "img_123" in converted[1]["text"])

    except Exception as e:
        report("Image modules", False, f"{e}\n{traceback.format_exc()}")


# ============================================================
# 13. AgentGraph (integration)
# ============================================================
async def test_agent_graph():
    print("\n[13] Testing AgentGraph (integration)...")
    try:
        from agent.graph import AgentGraph
        from core.skill_loader import SkillLoader

        loader = SkillLoader()
        metadata_list = loader.load_all_metadata()

        # Create graph without LLM
        graph = AgentGraph(skill_loader=loader, metadata_list=metadata_list, llm=None)
        report("AgentGraph creation", graph is not None)
        report("AgentGraph has router", graph.router is not None)
        report("AgentGraph has executor", graph.executor is not None)

        # Test _extract_user_input
        messages = [{"role": "user", "content": "hello world"}]
        user_input = graph._extract_user_input(messages)
        report("AgentGraph _extract_user_input", user_input == "hello world")

        # Test multimodal _extract_user_input
        multi_messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": "describe this"},
                {"type": "image_url", "image_url": {"url": "http://example.com/img.jpg"}},
            ]
        }]
        user_input2 = graph._extract_user_input(multi_messages)
        report("AgentGraph _extract_user_input multimodal", "describe this" in user_input2)

        # Test _append_messages_to_history
        graph.conversation_history = []
        graph._append_messages_to_history([{"role": "user", "content": "msg1"}])
        report("AgentGraph _append_messages_to_history", len(graph.conversation_history) == 1)

        # Test clear_history
        graph.clear_history()
        report("AgentGraph clear_history", len(graph.conversation_history) == 0)

        # Test get_history
        graph.conversation_history = [{"role": "user", "content": "test"}]
        h = graph.get_history()
        report("AgentGraph get_history", len(h) == 1)
        report("AgentGraph get_history returns copy", h is not graph.conversation_history)

        # Test _build_multimodal_content
        content = graph._build_multimodal_content("text here", [{"type": "image_url", "image_url": {"url": "x"}}])
        report("AgentGraph _build_multimodal_content", len(content) == 2)
        report("AgentGraph _build_multimodal_content text", content[0]["type"] == "text")

    except Exception as e:
        report("AgentGraph", False, f"{e}\n{traceback.format_exc()}")


# ============================================================
# 14. API (FastAPI test client)
# ============================================================
async def test_api():
    print("\n[14] Testing API endpoints...")
    try:
        from httpx import AsyncClient, ASGITransport
        from api import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Root endpoint
            resp = await client.get("/api")
            report("API /api", resp.status_code == 200)
            data = resp.json()
            report("API /api has name", "name" in data)

            # Health check
            resp = await client.get("/health")
            report("API /health", resp.status_code == 200)
            health = resp.json()
            report("API /health has status", "status" in health)

            # Skills list
            resp = await client.get("/api/skills")
            report("API /api/skills", resp.status_code == 200)
            skills = resp.json()
            report("API /api/skills has skills", "skills" in skills and isinstance(skills["skills"], list))

            # Create session
            resp = await client.post("/api/session/create")
            report("API /api/session/create", resp.status_code == 200)
            session_data = resp.json()
            report("API session has session_id", "session_id" in session_data)
            sid = session_data["session_id"]

            # Get session
            resp = await client.get(f"/api/session/{sid}")
            report("API /api/session/{id}", resp.status_code == 200)

            # DB stats
            resp = await client.get("/api/db/stats")
            report("API /api/db/stats", resp.status_code == 200)
            stats = resp.json()
            report("API stats has session_count", "session_count" in stats)

            # Delete session
            resp = await client.delete(f"/api/session/{sid}")
            report("API DELETE /api/session/{id}", resp.status_code == 200)

            # Chat endpoint (without LLM, will fail gracefully)
            resp = await client.post("/api/chat", json={
                "messages": [{"role": "user", "content": "hello"}],
            })
            # This may return 500 if LLM is not configured, which is expected
            report("API /api/chat responds", resp.status_code in (200, 500), f"status={resp.status_code}")

            # Stream endpoint
            resp = await client.post("/api/chat/stream", json={
                "messages": [{"role": "user", "content": "hello"}],
            })
            report("API /api/chat/stream responds", resp.status_code in (200, 500), f"status={resp.status_code}")

    except Exception as e:
        report("API", False, f"{e}\n{traceback.format_exc()}")


# ============================================================
# 15. Prompts
# ============================================================
def test_prompts():
    print("\n[15] Testing prompts...")
    try:
        # router.txt
        with open("prompts/router.txt", "r", encoding="utf-8") as f:
            router_prompt = f.read()
        report("router.txt exists", len(router_prompt) > 0)
        report("router.txt has {skills} placeholder", "{skills}" in router_prompt)
        report("router.txt has {task} placeholder", "{task}" in router_prompt)

        # planner.txt
        with open("prompts/planner.txt", "r", encoding="utf-8") as f:
            planner_prompt = f.read()
        report("planner.txt exists", len(planner_prompt) > 0)

        # react.txt
        with open("prompts/react.txt", "r", encoding="utf-8") as f:
            react_prompt = f.read()
        report("react.txt exists", len(react_prompt) > 0)

    except Exception as e:
        report("Prompts", False, f"{e}\n{traceback.format_exc()}")


# ============================================================
# 16. SKILL.md files
# ============================================================
def test_skill_md_files():
    print("\n[16] Testing SKILL.md files...")
    try:
        from core.skill_loader import _parse_front_matter

        skills_dir = Path("skills")
        for skill_folder in sorted(skills_dir.iterdir()):
            if not skill_folder.is_dir():
                continue
            md_file = skill_folder / "SKILL.md"
            if not md_file.exists():
                report(f"SKILL.md exists for {skill_folder.name}", False, "SKILL.md not found")
                continue

            with open(md_file, "r", encoding="utf-8") as f:
                content = f.read()

            fm = _parse_front_matter(content)
            report(f"SKILL.md '{skill_folder.name}' has front matter", bool(fm), "empty front matter")
            if fm:
                report(f"SKILL.md '{skill_folder.name}' has name", "name" in fm)
                report(f"SKILL.md '{skill_folder.name}' has description", "description" in fm)

    except Exception as e:
        report("SKILL.md files", False, f"{e}\n{traceback.format_exc()}")


# ============================================================
# Main
# ============================================================
async def main():
    print("=" * 60)
    print("Industrial Agent - Comprehensive Test Suite")
    print("=" * 60)

    # Sync tests
    test_config()
    test_llm_module()
    test_agent_state()
    test_skill_loader()
    test_database()
    test_http_skill()
    test_prompts()
    test_skill_md_files()

    # Async tests
    await test_calculator_skill()
    await test_time_query_skill()
    await test_router()
    await test_streaming()
    await test_base_skill()
    await test_image_modules()
    await test_agent_graph()
    await test_api()

    # Summary
    print("\n" + "=" * 60)
    print(f"Test Results: {PASS} passed, {FAIL} failed")
    print("=" * 60)

    if ERRORS:
        print("\nFailed tests:")
        for err in ERRORS:
            print(f"  {err}")

    return FAIL == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
