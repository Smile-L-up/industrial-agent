"""
测试 HttpSkill 配置模式是否走通
测试范围：SKILL.md 解析 → 技能加载 → 参数提取 → 请求体构建 → 响应解析 → 缺参追问
"""

import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


async def test_skill_loader_parsing():
    """测试1: SKILL.md 能被正确解析为 service 配置"""
    print("=" * 60)
    print("测试1: SKILL.md 解析")
    print("=" * 60)

    from core.skill_loader import SkillLoader

    loader = SkillLoader(skills_dir="skills")
    metadata_list = loader.load_all_metadata()

    # 检查 weather_map 被发现
    weather_meta = None
    for meta in metadata_list:
        if meta.name == "weather_map":
            weather_meta = meta
            break

    assert weather_meta is not None, "weather_map 技能未被发现"
    print(f"  [OK] 发现技能: {weather_meta.name} - {weather_meta.description}")
    print(f"       关键词: {weather_meta.keywords}")

    # 检查配置解析
    config = loader._load_config.__wrapped__(loader, loader.skills_dir / "weather_map") if hasattr(loader._load_config, '__wrapped__') else None
    # 直接调用
    from pathlib import Path
    config = loader._load_config(Path("skills/weather_map"))

    assert config is not None, "配置解析失败"
    assert "service" in config, "配置中缺少 service 字段"

    service = config["service"]
    assert service["type"] == "dify", f"service_type 应为 dify，实际为 {service['type']}"
    assert service["endpoint"] == "http://192.168.110.201:18080/v1/workflows/run"
    assert service["method"] == "POST"
    assert "areaName" in service["inputs"], "inputs 中缺少 areaName"
    assert "body_template" in service, "缺少 body_template"
    assert service["response_path"] == "data.outputs"

    print("  [OK] service 配置解析正确")
    print(f"       type: {service['type']}")
    print(f"       endpoint: {service['endpoint']}")
    print(f"       inputs: {list(service['inputs'].keys())}")
    print(f"       response_path: {service['response_path']}")
    return True


async def test_http_skill_instantiation():
    """测试2: HttpSkill 能从配置正确实例化"""
    print("\n" + "=" * 60)
    print("测试2: HttpSkill 实例化")
    print("=" * 60)

    from core.http_skill import HttpSkill

    config = {
        "name": "weather_map",
        "description": "气象色斑图生成服务",
        "keywords": ["气象", "色斑图"],
        "service": {
            "type": "dify",
            "endpoint": "http://192.168.110.201:18080/v1/workflows/run",
            "method": "POST",
            "headers": {"Authorization": "Bearer test-key"},
            "timeout": 120,
            "inputs": {
                "areaName": {"type": "string", "description": "地区名称", "required": True},
                "elementType": {"type": "string", "description": "气象要素", "required": True},
                "startTime": {"type": "date", "description": "开始日期", "required": True},
                "endTime": {"type": "date", "description": "结束日期", "required": True},
                "statistics": {"type": "string", "description": "统计方式", "default": "avg"},
            },
            "body_template": {
                "inputs": {
                    "areaName": "{areaName}",
                    "elementType": "{elementType}",
                    "startTime": "{startTime}",
                    "endTime": "{endTime}",
                    "statistics": "{statistics}",
                },
                "response_mode": "blocking",
                "user": "agent-user",
            },
            "response_path": "data.outputs",
        },
    }

    skill = HttpSkill(config)

    assert skill.name == "weather_map"
    assert skill.description == "气象色斑图生成服务"
    assert skill._endpoint == "http://192.168.110.201:18080/v1/workflows/run"
    assert skill._method == "POST"
    assert skill._response_path == "data.outputs"
    assert "areaName" in skill._inputs
    assert skill._inputs["statistics"]["default"] == "avg"

    print("  [OK] HttpSkill 实例化成功")
    print(f"       name: {skill.name}")
    print(f"       endpoint: {skill._endpoint}")
    print(f"       inputs: {list(skill._inputs.keys())}")

    # 测试 get_tools（HttpSkill 不声明子工具，路由由 Router 完成）
    tools = skill.get_tools()
    assert len(tools) == 0, f"HttpSkill.get_tools() 应返回空列表，实际: {tools}"
    print(f"  [OK] get_tools(): [] (子工具由 executor LLM 直接提取参数)")

    return skill


async def test_body_template_filling(skill):
    """测试3: 请求体模板填充"""
    print("\n" + "=" * 60)
    print("测试3: 请求体模板填充")
    print("=" * 60)

    params = {
        "areaName": "福州市",
        "elementType": "temAvg",
        "startTime": "2026-04-15",
        "endTime": "2026-05-15",
        "statistics": "avg",
    }

    body = skill._build_body(params)

    assert body["inputs"]["areaName"] == "福州市"
    assert body["inputs"]["elementType"] == "temAvg"
    assert body["inputs"]["startTime"] == "2026-04-15"
    assert body["inputs"]["endTime"] == "2026-05-15"
    assert body["inputs"]["statistics"] == "avg"
    assert body["response_mode"] == "blocking"
    assert body["user"] == "agent-user"

    print("  [OK] 请求体构建正确:")
    print(json.dumps(body, ensure_ascii=False, indent=4))
    return True


async def test_response_parsing():
    """测试4: 响应路径解析"""
    print("\n" + "=" * 60)
    print("测试4: 响应路径解析")
    print("=" * 60)

    from core.http_skill import HttpSkill

    config = {
        "name": "test",
        "description": "test",
        "service": {
            "endpoint": "http://localhost",
            "response_path": "data.outputs",
            "inputs": {},
            "body_template": {},
        },
    }
    skill = HttpSkill(config)

    # 模拟 Dify 响应
    response = {
        "task_id": "d048f265-bd33-4c5e-bc48-4250466355b1",
        "data": {
            "status": "succeeded",
            "outputs": {
                "img_path": "http://192.168.110.200:46000/data-in-center/files/surdayimg/20260515/test.png"
            },
            "elapsed_time": 14.31,
        },
    }

    result = skill._extract_by_path(response, "data.outputs")
    assert result is not None
    assert "img_path" in result
    print(f"  [OK] response_path 'data.outputs' -> {json.dumps(result, ensure_ascii=False)}")

    # 测试更深路径
    result2 = skill._extract_by_path(response, "data.outputs.img_path")
    assert result2 == "http://192.168.110.200:46000/data-in-center/files/surdayimg/20260515/test.png"
    print(f"  [OK] response_path 'data.outputs.img_path' -> {result2}")

    # 测试不存在的路径
    result3 = skill._extract_by_path(response, "data.nonexistent")
    assert result3 is None
    print("  [OK] 不存在的路径返回 None")

    return True


async def test_missing_params_question():
    """测试5: 缺参追问消息生成"""
    print("\n" + "=" * 60)
    print("测试5: 缺参追问消息")
    print("=" * 60)

    from core.http_skill import HttpSkill

    config = {
        "name": "test",
        "description": "test",
        "service": {
            "endpoint": "http://localhost",
            "inputs": {
                "areaName": {"type": "string", "description": "地区名称，如'福州市'", "required": True},
                "elementType": {"type": "string", "description": "气象要素类型，如 temAvg", "required": True},
                "startTime": {"type": "date", "description": "开始日期，格式 YYYY-MM-DD", "required": True},
            },
            "body_template": {},
        },
    }
    skill = HttpSkill(config)

    question = skill._build_missing_params_question(["areaName", "startTime"])
    assert "地区名称" in question
    assert "开始日期" in question
    print(f"  [OK] 追问消息:\n{question}")

    return True


async def test_full_flow_no_llm():
    """测试6: 完整流程（无 LLM，用正则提取 + 缺参追问）"""
    print("\n" + "=" * 60)
    print("测试6: 完整流程（无 LLM 模式）")
    print("=" * 60)

    from core.http_skill import HttpSkill

    config = {
        "name": "weather_map",
        "description": "气象色斑图生成服务",
        "keywords": ["气象", "色斑图"],
        "service": {
            "type": "dify",
            "endpoint": "http://192.168.110.201:18080/v1/workflows/run",
            "method": "POST",
            "headers": {},
            "timeout": 10,
            "inputs": {
                "areaName": {"type": "string", "description": "地区名称", "required": True},
                "elementType": {"type": "string", "description": "气象要素", "required": True},
                "startTime": {"type": "date", "description": "开始日期", "required": True},
                "endTime": {"type": "date", "description": "结束日期", "required": True},
                "statistics": {"type": "string", "description": "统计方式", "default": "avg"},
            },
            "body_template": {
                "inputs": {
                    "areaName": "{areaName}",
                    "elementType": "{elementType}",
                    "startTime": "{startTime}",
                    "endTime": "{endTime}",
                    "statistics": "{statistics}",
                },
                "response_mode": "blocking",
                "user": "agent-user",
            },
            "response_path": "data.outputs",
        },
    }

    skill = HttpSkill(config)
    # 不注入 LLM，走正则回退

    # 场景1: 用户只说了模糊的话，缺大部分参数
    print("\n  场景1: 用户说 '查一下天气'")
    result1 = await skill.execute(
        task="查一下天气",
        context=type("Ctx", (), {"extra": {}})(),
        messages=[{"role": "user", "content": "查一下天气"}],
    )
    print(f"  结果: {result1[:100]}...")
    assert "需要" in result1 or "请提供" in result1, "应该返回追问消息"
    print("  [OK] 正确返回追问消息")

    # 场景2: 用户提供了日期但没给地区
    print("\n  场景2: 用户说 '2026-04-15到2026-05-15的温度'")
    result2 = await skill.execute(
        task="2026-04-15到2026-05-15的温度",
        context=type("Ctx", (), {"extra": {}})(),
        messages=[{"role": "user", "content": "2026-04-15到2026-05-15的温度"}],
    )
    print(f"  结果: {result2[:100]}...")
    # 正则能提取日期，但缺 areaName 和 elementType
    assert "需要" in result2 or "请提供" in result2, "应该返回追问消息"
    print("  [OK] 正确返回追问消息（有日期但缺其他参数）")

    return True


async def test_skill_loader_integration():
    """测试7: SkillLoader 集成加载"""
    print("\n" + "=" * 60)
    print("测试7: SkillLoader 集成加载 weather_map")
    print("=" * 60)

    from core.skill_loader import SkillLoader

    loader = SkillLoader(skills_dir="skills")
    loader.load_all_metadata()

    # 通过 loader 加载 weather_map
    skill = loader.load_skill_full("weather_map")

    assert skill is not None, "weather_map 技能加载失败"
    from core.http_skill import HttpSkill
    assert isinstance(skill, HttpSkill), f"应为 HttpSkill 实例，实际为 {type(skill)}"
    assert skill.name == "weather_map"
    assert skill._endpoint == "http://192.168.110.201:18080/v1/workflows/run"

    print(f"  [OK] SkillLoader 成功加载 weather_map 为 HttpSkill")
    print(f"       name: {skill.name}")
    print(f"       endpoint: {skill._endpoint}")
    print(f"       inputs: {list(skill._inputs.keys())}")

    # 同时验证老技能仍然正常
    calc_skill = loader.load_skill_full("calculator")
    assert calc_skill is not None, "calculator 技能加载失败"
    print(f"  [OK] 老技能 calculator 仍然正常加载: {calc_skill.name}")

    time_skill = loader.load_skill_full("time_query")
    assert time_skill is not None, "time_query 技能加载失败"
    print(f"  [OK] 老技能 time_query 仍然正常加载: {time_skill.name}")

    return True


async def main():
    print("HttpSkill 配置模式测试")
    print("=" * 60)

    passed = 0
    failed = 0

    tests = [
        ("SKILL.md 解析", test_skill_loader_parsing),
        ("HttpSkill 实例化", test_http_skill_instantiation),
        ("响应路径解析", test_response_parsing),
        ("缺参追问消息", test_missing_params_question),
        ("完整流程（无LLM）", test_full_flow_no_llm),
        ("SkillLoader 集成", test_skill_loader_integration),
    ]

    skill_instance = None

    for name, test_fn in tests:
        try:
            if name == "HttpSkill 实例化":
                skill_instance = await test_fn()
            elif name == "请求体模板填充":
                await test_body_template_filling(skill_instance)
            else:
                await test_fn()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"  [FAIL] {name}: {e}")
            import traceback
            traceback.print_exc()

    # 单独测试 body template（需要 skill 实例）
    if skill_instance:
        try:
            await test_body_template_filling(skill_instance)
            passed += 1
        except Exception as e:
            failed += 1
            print(f"  [FAIL] 请求体模板填充: {e}")

    print("\n" + "=" * 60)
    print(f"测试结果: {passed} 通过, {failed} 失败")
    print("=" * 60)

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
