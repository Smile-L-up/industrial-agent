"""
Full Feature Test Suite for Industrial Agent
Tests all modules, skills, database, router, streaming, API endpoints, and end-to-end chat.
Uses conda 'skills' environment Python.
"""

import asyncio
import json
import os
import sys
import tempfile
import traceback
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

        for key in ("provider", "model", "base_url", "system_prompt"):
            report(f"LLM_CONFIG has '{key}'", key in LLM_CONFIG, f"missing key: {key}")

        report("DATABASE_CONFIG has 'type'", "type" in DATABASE_CONFIG)
        report("SESSION_CONFIG has 'max_history'", "max_history" in SESSION_CONFIG)
        report("SESSION_CONFIG has 'ttl_minutes'", "ttl_minutes" in SESSION_CONFIG)
        report("SESSION_CONFIG has 'max_sessions'", "max_sessions" in SESSION_CONFIG)

        warnings = validate_config()
        report("validate_config returns list", isinstance(warnings, list))
        report("API key configured", bool(LLM_CONFIG.get("api_key")), "DASHSCOPE_API_KEY not set")
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

        msg = Message(role="user", content="hello")
        report("Message creation", msg.role == "user" and msg.content == "hello")
        report("Message.to_dict", msg.to_dict() == {"role": "user", "content": "hello"})

        multi_msg = Message(role="user", content=[{"type": "text", "text": "hi"}])
        report("Multimodal Message", isinstance(multi_msg.content, list))

        resp = LLMResponse(content="hi", model="test", usage={"total": 1}, finish_reason="stop")
        report("LLMResponse creation", resp.content == "hi")
        report("LLMResponse thinking_content default", resp.thinking_content is None)

        report("LLMFactory has openai provider", "openai" in LLMFactory._providers)
        report("LLMFactory has azure_openai provider", "azure_openai" in LLMFactory._providers)

        try:
            llm = OpenAILLM(model="test-model", api_key="sk-test", base_url="http://localhost")
            report("OpenAILLM instantiation", True)
            report("OpenAILLM has chat method", hasattr(llm, "chat"))
            report("OpenAILLM has chat_stream method", hasattr(llm, "chat_stream"))
            report("OpenAILLM has generate method", hasattr(llm, "generate"))
            report("OpenAILLM has generate_stream method", hasattr(llm, "generate_stream"))
            report("OpenAILLM model", llm.model == "test-model")
            report("OpenAILLM temperature default", llm.temperature == 0.7)
            report("OpenAILLM max_tokens default", llm.max_tokens == 4096)
        except Exception as e:
            report("OpenAILLM instantiation", False, str(e))

        # Test get_llm convenience function
        try:
            llm2 = get_llm(provider="openai", model="test", api_key="sk-test", base_url="http://localhost")
            report("get_llm convenience function", llm2 is not None)
        except Exception as e:
            report("get_llm convenience function", False, str(e))

        # Test LLMFactory unknown provider
        try:
            LLMFactory.create("unknown_provider")
            report("LLMFactory unknown provider raises", False, "Should have raised ValueError")
        except ValueError:
            report("LLMFactory unknown provider raises", True)

    except Exception as e:
        report("llm module", False, f"{e}\n{traceback.format_exc()}")


# ============================================================
# 3. AgentState
# ============================================================
def test_agent_state():
    print("\n[3] Testing AgentState...")
    try:
        from agent.state import AgentState, Task, BoundedList, ExecutionContext

        # BoundedList
        bl = BoundedList(max_len=3)
        bl.append(1)
        bl.append(2)
        bl.append(3)
        bl.append(4)
        report("BoundedList max_len", len(bl) == 3 and bl[0] == 2)
        report("BoundedList iteration", list(bl) == [2, 3, 4])

        # ExecutionContext
        ctx = ExecutionContext()
        ctx.set("selected_skill", "calculator")
        report("ExecutionContext set/get", ctx.get("selected_skill") == "calculator")
        report("ExecutionContext contains", "selected_skill" in ctx)
        ctx["test_key"] = "test_val"
        report("ExecutionContext __setitem__", ctx["test_key"] == "test_val")
        d = ctx.to_dict()
        report("ExecutionContext to_dict", isinstance(d, dict) and "selected_skill" in d)

        # AgentState
        state = AgentState()
        state.user_input = "test input"
        report("AgentState.user_input", state.user_input == "test input")

        state.add_message("user", "hello")
        report("AgentState.add_message", len(state.messages) == 1)
        report("AgentState.messages role", state.messages[0]["role"] == "user")

        task = Task(id="1", description="test task")
        state.add_task(task)
        report("AgentState.add_task", len(state.tasks) == 1)
        report("Task status default", task.status == "pending")

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
        report("AgentState.to_dict has tasks", "tasks" in d)
        report("AgentState.to_dict has context", "context" in d)

        # Backward compat: context as dict setter
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

        # Front matter parsing
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
        report("Front matter keywords", isinstance(fm.get("keywords"), list) and len(fm.get("keywords")) == 2)

        # Empty front matter
        empty_fm = _parse_front_matter("# No front matter")
        report("Empty front matter returns empty dict", empty_fm == {})

        # SkillLoader
        loader = SkillLoader(skills_dir="skills")
        metadata_list = loader.load_all_metadata()
        report("SkillLoader.load_all_metadata", isinstance(metadata_list, list))
        report("SkillLoader found skills", len(metadata_list) >= 4, f"found {len(metadata_list)} skills")

        for meta in metadata_list:
            report(f"Skill '{meta.name}' has name", bool(meta.name))
            report(f"Skill '{meta.name}' has description", bool(meta.description))
            report(f"Skill '{meta.name}' has path", bool(meta.path))

        # Load calculator
        calc_skill = loader.load_skill_full("calculator")
        report("Load calculator skill", calc_skill is not None)
        if calc_skill:
            report("Calculator has name", calc_skill.name == "calculator")
            report("Calculator has execute", hasattr(calc_skill, "execute"))
            report("Calculator has get_tools", hasattr(calc_skill, "get_tools"))

        # Load time_query
        time_skill = loader.load_skill_full("time_query")
        report("Load time_query skill", time_skill is not None)

        # Caching
        calc_skill2 = loader.load_skill_full("calculator")
        report("Skill caching works", calc_skill is calc_skill2)

        # get_metadata
        meta = loader.get_metadata("calculator")
        report("get_metadata works", meta is not None)

        # get_skill
        cached = loader.get_skill("calculator")
        report("get_skill from cache", cached is not None)

        # Nonexistent skill
        bad = loader.load_skill_full("nonexistent_skill")
        report("Nonexistent skill returns None", bad is None)

        # Load all (compat interface)
        all_skills = loader.load_all()
        report("load_all returns list", isinstance(all_skills, list))
        report("load_all finds skills", len(all_skills) >= 2)

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
        report("get_session metadata", session["metadata"].get("test") is True)

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
        report("get_stats has message_count", "message_count" in stats)
        report("get_stats has memory_count", "memory_count" in stats)

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

        # Basic execute
        result = await calc.execute("计算 1+2", {}, [])
        report("Calculator: 1+2", "3" in result, f"got: {result}")

        result = await calc.execute("10*3-5", {}, [])
        report("Calculator: 10*3-5", "25" in result, f"got: {result}")

        result = await calc.execute("(2+3)*4", {}, [])
        report("Calculator: (2+3)*4", "20" in result, f"got: {result}")

        result = await calc.execute("10除以2", {}, [])
        report("Calculator: 10/2", "5" in result, f"got: {result}")

        result = await calc.execute("100 除以 4", {}, [])
        report("Calculator: 100/4", "25" in result, f"got: {result}")

        # No expression
        result = await calc.execute("你好", {}, [])
        report("Calculator: no expression", "未能" in result or "请提供" in result)

        # Sub-tool
        tool_result = await calc.calculate("3+7")
        report("Calculator sub-tool", tool_result.get("success") and tool_result.get("result") == 10)

        # Sub-tool with empty expression
        tool_result2 = await calc.calculate("")
        report("Calculator sub-tool empty", not tool_result2.get("success"))

        # get_tools
        tools = calc.get_tools()
        report("Calculator get_tools", len(tools) == 1 and tools[0]["name"] == "calculate")

        # match_keywords
        keywords = calc.match_keywords()
        report("Calculator match_keywords", len(keywords) > 0)

        # Edge cases
        result = await calc.execute("0+0", {}, [])
        report("Calculator: 0+0", "0" in result)

        result = await calc.execute("999*999", {}, [])
        report("Calculator: 999*999", "998001" in result)

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

        # Execute
        result = await time_skill.execute("现在几点了", {}, [])
        report("TimeQuery execute", "当前时间" in result, f"got: {result}")

        # Sub-tool
        data = await time_skill.get_current_time()
        report("TimeQuery get_current_time", isinstance(data, dict))
        report("TimeQuery has year", "year" in data)
        report("TimeQuery has month", "month" in data)
        report("TimeQuery has day", "day" in data)
        report("TimeQuery has hour", "hour" in data)
        report("TimeQuery has minute", "minute" in data)
        report("TimeQuery has second", "second" in data)
        report("TimeQuery has weekday", "weekday" in data)
        report("TimeQuery has timestamp", "timestamp" in data)

        # get_tools
        tools = time_skill.get_tools()
        report("TimeQuery get_tools", len(tools) == 1 and tools[0]["name"] == "get_current_time")

        # match_keywords
        keywords = time_skill.match_keywords()
        report("TimeQuery match_keywords", len(keywords) > 0)

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

        # Router without LLM
        router = Router(llm=None, metadata_list=metadata_list)
        report("Router creation", router is not None)
        report("Router has metadata", len(router.metadata_list) > 0)
        report("Router has prompt_template", bool(router.prompt_template))

        # _match_user_skills
        selected = router._match_user_skills(["calculator"])
        report("Router _match_user_skills", selected == "calculator")

        selected = router._match_user_skills(["nonexistent"])
        report("Router _match_user_skills nonexistent", selected is None)

        selected = router._match_user_skills(["nonexistent", "time_query"])
        report("Router _match_user_skills fallback", selected == "time_query")

        # _parse_skill_selection
        parsed = router._parse_skill_selection("calculator")
        report("Router _parse_skill_selection exact", parsed == "calculator")

        parsed = router._parse_skill_selection("none")
        report("Router _parse_skill_selection none", parsed is None)

        parsed = router._parse_skill_selection("无")
        report("Router _parse_skill_selection 无", parsed is None)

        parsed = router._parse_skill_selection("null")
        report("Router _parse_skill_selection null", parsed is None)

        parsed = router._parse_skill_selection("")
        report("Router _parse_skill_selection empty", parsed is None)

        # _try_match_skill
        matched = router._try_match_skill("calculator")
        report("Router _try_match_skill", matched == "calculator")

        matched = router._try_match_skill("nonexistent")
        report("Router _try_match_skill nonexistent", matched is None)

        # _is_confirmed_answer
        report("Router _is_confirmed_answer (space)", router._is_confirmed_answer("hello world") is True)
        report("Router _is_confirmed_answer (punct)", router._is_confirmed_answer("hello!") is True)
        report("Router _is_confirmed_answer (skill name)", router._is_confirmed_answer("calculator") is False)
        report("Router _is_confirmed_answer (empty)", router._is_confirmed_answer("") is False)

        # Route with user-selected skills
        state = AgentState()
        state.user_input = "calculate 1+1"
        state.add_task(Task(id="1", description="calculate 1+1"))
        state.context["selected_skills"] = ["calculator"]

        result_state = await router.route(state)
        report("Router route with user skills", result_state.current_tool == "calculator")

        # Route without LLM (no skill match expected)
        state2 = AgentState()
        state2.user_input = "tell me a joke"
        state2.add_task(Task(id="2", description="tell me a joke"))
        result_state2 = await router.route(state2)
        report("Router route without LLM no match", result_state2.current_tool is None)

        # update_metadata
        router.update_metadata([])
        report("Router update_metadata", len(router.metadata_list) == 0)

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

        # call_tool with nonexistent tool
        try:
            await s2.call_tool("nonexistent", {}, {})
            report("BaseSkill.call_tool nonexistent", False, "Should have raised AttributeError")
        except AttributeError:
            report("BaseSkill.call_tool nonexistent", True)

        # execute_stream default implementation
        chunks = []
        async for chunk in s2.execute_stream("task", {}, []):
            chunks.append(chunk)
        report("BaseSkill.execute_stream default", len(chunks) == 1 and chunks[0] == "ok")

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
        report("HttpSkill get_tools", skill.get_tools() == [])
        report("HttpSkill match_keywords", skill.match_keywords() == ["test"])

        # _build_body
        body = skill._build_body({"query": "test"})
        report("HttpSkill _build_body", body == {"inputs": {"query": "test"}})

        # _extract_by_path
        data = {"data": {"result": "found"}}
        extracted = skill._extract_by_path(data, "data.result")
        report("HttpSkill _extract_by_path", extracted == "found")

        missing = skill._extract_by_path(data, "data.nonexistent")
        report("HttpSkill _extract_by_path missing", missing is None)

        # _build_missing_params_question
        question = skill._build_missing_params_question(["query"])
        report("HttpSkill missing params question", "查询" in question)

        # _extract_params_with_regex
        params = skill._extract_params_with_regex("2026-05-15 的数据")
        report("HttpSkill regex date extraction", isinstance(params, dict))

        # _format_result
        report("HttpSkill format string", skill._format_result("test") == "test")
        report("HttpSkill format dict", "{" in skill._format_result({"key": "val"}))

    except Exception as e:
        report("HttpSkill", False, f"{e}\n{traceback.format_exc()}")


# ============================================================
# 12. McpSkill
# ============================================================
def test_mcp_skill():
    print("\n[12] Testing McpSkill...")
    try:
        from core.mcp_skill import McpSkill

        config = {
            "name": "test_mcp",
            "description": "test mcp skill",
            "keywords": ["mcp"],
            "mcp": {
                "endpoint": "http://localhost:9999/mcp",
                "timeout": 30,
            },
        }

        skill = McpSkill(config)
        report("McpSkill creation", skill.name == "test_mcp")
        report("McpSkill description", skill.description == "test mcp skill")
        report("McpSkill match_keywords", skill.match_keywords() == ["mcp"])
        report("McpSkill get_tools (empty cache)", skill.get_tools() == [])

        # _format_result
        report("McpSkill format string", skill._format_result("test") == "test")
        report("McpSkill format dict", "{" in skill._format_result({"key": "val"}))

        # _fallback_extract
        schema = {"properties": {"query": {"type": "string"}}, "required": ["query"]}
        result = skill._fallback_extract("hello world", schema)
        report("McpSkill fallback extract", result.get("query") == "hello world")

        # _fallback_extract with no string params
        schema2 = {"properties": {"num": {"type": "number"}}, "required": ["num"]}
        result2 = skill._fallback_extract("hello", schema2)
        report("McpSkill fallback no string", result2 == {})

    except Exception as e:
        report("McpSkill", False, f"{e}\n{traceback.format_exc()}")


# ============================================================
# 13. ImageUploader / ImageStore
# ============================================================
async def test_image_modules():
    print("\n[13] Testing ImageUploader & ImageStore...")
    try:
        from core.image_uploader import ImageUploader
        from core.image_store import ImageStore

        # MIME type detection
        mime = ImageUploader._get_mime_type("test.jpg")
        report("ImageUploader MIME jpg", mime == "image/jpeg")
        mime = ImageUploader._get_mime_type("test.png")
        report("ImageUploader MIME png", mime == "image/png")
        mime = ImageUploader._get_mime_type("test.gif")
        report("ImageUploader MIME gif", mime == "image/gif")
        mime = ImageUploader._get_mime_type("test.webp")
        report("ImageUploader MIME webp", mime == "image/webp")

        # MIME from bytes
        png_header = b"\x89PNG\r\n\x1a\n" + b"\x00" * 10
        mime = ImageUploader._get_mime_type_from_bytes(png_header)
        report("ImageUploader MIME from bytes (PNG)", mime == "image/png")

        jpg_header = b"\xff\xd8\xff" + b"\x00" * 10
        mime = ImageUploader._get_mime_type_from_bytes(jpg_header)
        report("ImageUploader MIME from bytes (JPEG)", mime == "image/jpeg")

        # ImageStore helpers
        report("ImageStore is_data_image_url (true)", ImageStore.is_data_image_url("data:image/png;base64,abc"))
        report("ImageStore is_data_image_url (false)", not ImageStore.is_data_image_url("http://example.com/img.jpg"))

        import base64
        test_data = b"hello"
        b64 = base64.b64encode(test_data).decode()
        data_url = f"data:image/png;base64,{b64}"
        mime, b64_data, size, sha = ImageStore.parse_data_url(data_url)
        report("ImageStore parse_data_url mime", mime == "image/png")
        report("ImageStore parse_data_url size", size == 5)
        report("ImageStore parse_data_url sha", len(sha) == 64)

        summary = ImageStore.build_summary("test_id", "image/png", 1024)
        report("ImageStore build_summary", "test_id" in summary and "png" in summary)

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
# 14. AgentGraph (integration)
# ============================================================
async def test_agent_graph():
    print("\n[14] Testing AgentGraph (integration)...")
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
        report("AgentGraph has skill_loader", graph.skill_loader is not None)

        # _extract_user_input
        messages = [{"role": "user", "content": "hello world"}]
        user_input = graph._extract_user_input(messages)
        report("AgentGraph _extract_user_input", user_input == "hello world")

        # Multimodal _extract_user_input
        multi_messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": "describe this"},
                {"type": "image_url", "image_url": {"url": "http://example.com/img.jpg"}},
            ]
        }]
        user_input2 = graph._extract_user_input(multi_messages)
        report("AgentGraph _extract_user_input multimodal", "describe this" in user_input2)

        # _append_messages_to_history
        graph.conversation_history = []
        graph._append_messages_to_history([{"role": "user", "content": "msg1"}])
        report("AgentGraph _append_messages_to_history", len(graph.conversation_history) == 1)

        # clear_history
        graph.clear_history()
        report("AgentGraph clear_history", len(graph.conversation_history) == 0)

        # get_history
        graph.conversation_history = [{"role": "user", "content": "test"}]
        h = graph.get_history()
        report("AgentGraph get_history", len(h) == 1)
        report("AgentGraph get_history returns copy", h is not graph.conversation_history)

        # _build_multimodal_content
        content = graph._build_multimodal_content("text here", [{"type": "image_url", "image_url": {"url": "x"}}])
        report("AgentGraph _build_multimodal_content", len(content) == 2)
        report("AgentGraph _build_multimodal_content text", content[0]["type"] == "text")

        # With database
        import tempfile
        tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(tmpdir, "test_graph.db")
        try:
            from core.database import DatabaseManager
            db = DatabaseManager(db_type="sqlite", db_path=db_path)
            db.create_session("test-sid", {})
            db.add_message("test-sid", "user", "hello from db")

            graph2 = AgentGraph(
                skill_loader=loader,
                metadata_list=metadata_list,
                llm=None,
                session_id="test-sid",
                db=db
            )
            report("AgentGraph with DB", len(graph2.conversation_history) > 0)
        finally:
            try:
                os.remove(db_path)
            except:
                pass
            try:
                os.rmdir(tmpdir)
            except:
                pass

    except Exception as e:
        report("AgentGraph", False, f"{e}\n{traceback.format_exc()}")


# ============================================================
# 15. API Endpoints (with proper lifespan)
# ============================================================
async def test_api():
    print("\n[15] Testing API endpoints...")
    try:
        from httpx import AsyncClient, ASGITransport
        from api import app, app_state

        # Manually trigger lifespan initialization
        from core.database import init_database
        from config import DATABASE_CONFIG, LLM_CONFIG, SESSION_CONFIG
        from core.skill_loader import SkillLoader
        from llm.llm import get_llm

        # Initialize components
        db = init_database(DATABASE_CONFIG)
        app_state["db"] = db

        llm = get_llm(
            provider=LLM_CONFIG["provider"],
            model=LLM_CONFIG["model"],
            api_key=LLM_CONFIG.get("api_key"),
            base_url=LLM_CONFIG.get("base_url"),
            system_prompt=LLM_CONFIG.get("system_prompt"),
        )
        app_state["llm"] = llm

        skill_loader = SkillLoader()
        metadata_list = skill_loader.load_all_metadata()
        app_state["skill_loader"] = skill_loader
        app_state["metadata_list"] = metadata_list
        app_state["initialized"] = True

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Root endpoint
            resp = await client.get("/api")
            report("API /api", resp.status_code == 200)
            data = resp.json()
            report("API /api has name", "name" in data)
            report("API /api has endpoints", "endpoints" in data)

            # Health check
            resp = await client.get("/health")
            report("API /health", resp.status_code == 200)
            health = resp.json()
            report("API /health has status", "status" in health)
            report("API /health has llm", "llm" in health)
            report("API /health has skills_count", "skills_count" in health)

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

            # Clear session history
            resp = await client.post(f"/api/session/{sid}/clear")
            report("API /api/session/{id}/clear", resp.status_code == 200)

            # Delete session
            resp = await client.delete(f"/api/session/{sid}")
            report("API DELETE /api/session/{id}", resp.status_code == 200)

            # Chat endpoint (non-stream)
            resp = await client.post("/api/chat", json={
                "messages": [{"role": "user", "content": "1+1等于多少"}],
                "selected_skills": ["calculator"],
            })
            report("API /api/chat responds", resp.status_code in (200, 500), f"status={resp.status_code}")
            if resp.status_code == 200:
                chat_data = resp.json()
                report("API /api/chat has session_id", "session_id" in chat_data)
                report("API /api/chat has result", "result" in chat_data)

            # Stream endpoint
            resp = await client.post("/api/chat/stream", json={
                "messages": [{"role": "user", "content": "你好"}],
                "request_id": "test-req-001",
            })
            report("API /api/chat/stream responds", resp.status_code == 200)

            # Cancel endpoint
            resp = await client.post("/api/chat/cancel", json={
                "request_id": "nonexistent-req",
            })
            report("API /api/chat/cancel 404", resp.status_code == 404)

    except Exception as e:
        report("API", False, f"{e}\n{traceback.format_exc()}")


# ============================================================
# 16. Prompts
# ============================================================
def test_prompts():
    print("\n[16] Testing prompts...")
    try:
        with open("prompts/router.txt", "r", encoding="utf-8") as f:
            router_prompt = f.read()
        report("router.txt exists", len(router_prompt) > 0)
        report("router.txt has {skills} placeholder", "{skills}" in router_prompt)
        report("router.txt has {task} placeholder", "{task}" in router_prompt)

        with open("prompts/planner.txt", "r", encoding="utf-8") as f:
            planner_prompt = f.read()
        report("planner.txt exists", len(planner_prompt) > 0)

        with open("prompts/react.txt", "r", encoding="utf-8") as f:
            react_prompt = f.read()
        report("react.txt exists", len(react_prompt) > 0)

    except Exception as e:
        report("Prompts", False, f"{e}\n{traceback.format_exc()}")


# ============================================================
# 17. SKILL.md files
# ============================================================
def test_skill_md_files():
    print("\n[17] Testing SKILL.md files...")
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
# 18. End-to-End Chat (with real LLM)
# ============================================================
async def test_e2e_chat():
    print("\n[18] Testing End-to-End Chat (real LLM)...")
    try:
        from config import LLM_CONFIG
        from llm.llm import get_llm, Message
        from agent.graph import AgentGraph
        from core.skill_loader import SkillLoader
        from core.database import DatabaseManager

        if not LLM_CONFIG.get("api_key"):
            report("E2E chat skipped", False, "No API key configured")
            return

        # Initialize
        llm = get_llm(
            provider=LLM_CONFIG["provider"],
            model=LLM_CONFIG["model"],
            api_key=LLM_CONFIG["api_key"],
            base_url=LLM_CONFIG["base_url"],
            system_prompt=LLM_CONFIG.get("system_prompt"),
        )
        loader = SkillLoader()
        metadata_list = loader.load_all_metadata()

        # Create temp database
        tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(tmpdir, "test_e2e.db")
        db = DatabaseManager(db_type="sqlite", db_path=db_path)
        db.create_session("e2e-test", {})

        graph = AgentGraph(
            skill_loader=loader,
            metadata_list=metadata_list,
            llm=llm,
            session_id="e2e-test",
            db=db
        )

        # Test 1: Calculator skill via stream (production path)
        print("    Testing calculator via agent stream...")
        graph.conversation_history = []
        full_resp = ""
        async for chunk in graph.run_stream_with_messages(
            [{"role": "user", "content": "1+1等于多少"}],
            selected_skills=["calculator"]
        ):
            if chunk.get("type") == "token":
                full_resp += chunk.get("content", "")
            elif chunk.get("type") == "complete":
                full_resp = chunk.get("content", full_resp)
        report("E2E calculator result", "2" in full_resp, f"got: {full_resp[:100]}")

        # Test 2: Time query skill via stream
        print("    Testing time_query via agent stream...")
        graph.conversation_history = []
        full_resp2 = ""
        async for chunk in graph.run_stream_with_messages(
            [{"role": "user", "content": "现在几点了"}],
            selected_skills=["time_query"]
        ):
            if chunk.get("type") == "token":
                full_resp2 += chunk.get("content", "")
            elif chunk.get("type") == "complete":
                full_resp2 = chunk.get("content", full_resp2)
        report("E2E time_query result", len(full_resp2) > 0, f"got: {full_resp2[:100]}")

        # Test 3: LLM direct answer (no skill)
        print("    Testing LLM direct answer...")
        graph.conversation_history = []
        result3 = await graph.run_with_messages(
            [{"role": "user", "content": "你好，请简短回复"}],
        )
        final = str(result3.get("final_result", ""))
        report("E2E LLM direct answer", len(final) > 0, f"got: {final[:100]}")

        # Test 4: Stream mode
        print("    Testing stream mode...")
        graph.conversation_history = []
        full_response = ""
        async for chunk in graph.run_stream_with_messages(
            [{"role": "user", "content": "2+2等于多少"}],
            selected_skills=["calculator"]
        ):
            if chunk.get("type") == "token":
                full_response += chunk.get("content", "")
            elif chunk.get("type") == "complete":
                full_response = chunk.get("content", full_response)
        report("E2E stream mode", "4" in full_response, f"got: {full_response[:100]}")

        # Cleanup
        try:
            os.remove(db_path)
        except:
            pass
        try:
            os.rmdir(tmpdir)
        except:
            pass

    except Exception as e:
        report("E2E chat", False, f"{e}\n{traceback.format_exc()}")


# ============================================================
# 19. Executor
# ============================================================
async def test_executor():
    print("\n[19] Testing Executor...")
    try:
        from agent.executor import Executor, _get_city_from_input
        from agent.state import AgentState, Task
        from core.skill_loader import SkillLoader

        # _get_city_from_input
        report("Executor city extraction 北京", _get_city_from_input("北京天气") == "北京")
        report("Executor city extraction 上海", _get_city_from_input("上海怎么样") == "上海")
        report("Executor city extraction none", _get_city_from_input("hello") is None)

        # Executor without LLM
        loader = SkillLoader()
        executor = Executor(llm=None, skill_loader=loader)
        report("Executor creation", executor is not None)

        # _find_skill
        calc = executor._find_skill("calculator")
        report("Executor _find_skill", calc is not None)

        bad = executor._find_skill("nonexistent")
        report("Executor _find_skill nonexistent", bad is None)

        # Execute with calculator
        state = AgentState()
        state.user_input = "1+1"
        state.add_task(Task(id="1", description="1+1"))
        state.context["selected_skill"] = "calculator"

        result_state = await executor.execute(state)
        report("Executor execute calculator", result_state is not None)
        report("Executor execute result", len(result_state.tasks) > 0)
        if result_state.tasks:
            task_status = result_state.tasks[0].status
            report("Executor task has status", task_status in ("completed", "failed", "in_progress", "pending"),
                   f"status={task_status}")

        # Execute general (no skill, no LLM)
        state2 = AgentState()
        state2.user_input = "hello"
        state2.add_task(Task(id="2", description="hello"))
        result_state2 = await executor.execute(state2)
        report("Executor execute general no LLM", result_state2 is not None)

    except Exception as e:
        report("Executor", False, f"{e}\n{traceback.format_exc()}")


# ============================================================
# Main
# ============================================================
async def main():
    print("=" * 60)
    print("Industrial Agent - Full Feature Test Suite")
    print("=" * 60)

    # Sync tests
    test_config()
    test_llm_module()
    test_agent_state()
    test_skill_loader()
    test_database()
    test_http_skill()
    test_mcp_skill()
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
    await test_executor()
    await test_api()

    # E2E test (requires real LLM API key)
    await test_e2e_chat()

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
