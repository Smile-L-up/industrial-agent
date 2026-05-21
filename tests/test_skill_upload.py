"""
技能上传服务测试
测试 /api/skills/upload、/api/skills/{name}、DELETE 等端点

使用方法：
    python tests/test_skill_upload.py
"""

import asyncio
import io
import json
import time
import zipfile

import httpx

BASE_URL = "http://127.0.0.1:18000"
TIMEOUT = 30.0

# 测试用技能名（每次运行不同，避免冲突）
TEST_SKILL_NAME = "test_upload_skill"


def make_skill_zip(
    skill_md_content: str = None,
    tool_py_content: str = None,
    extra_files: dict = None,
    inner_dir: bool = True,
) -> bytes:
    """
    构造一个测试用的技能 ZIP 包

    Args:
        skill_md_content: SKILL.md 的内容
        tool_py_content: tool.py 的内容
        extra_files: 额外文件 {filename: content}
        inner_dir: 是否包一层子目录

    Returns:
        ZIP 文件字节
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        prefix = f"{TEST_SKILL_NAME}/" if inner_dir else ""

        if skill_md_content is None:
            skill_md_content = f"""---
name: {TEST_SKILL_NAME}
description: 这是一个测试上传的技能
keywords:
  - 测试
  - 上传
---

# 测试技能

用于测试上传功能。
"""

        zf.writestr(f"{prefix}SKILL.md", skill_md_content)

        if tool_py_content is not None:
            zf.writestr(f"{prefix}tool.py", tool_py_content)

        if extra_files:
            for name, content in extra_files.items():
                zf.writestr(f"{prefix}{name}", content)

    return buf.getvalue()


async def wait_for_server(max_wait=30):
    """等待服务器启动"""
    print("[*] 等待服务器就绪...")
    start = time.time()
    async with httpx.AsyncClient(timeout=5.0) as client:
        while time.time() - start < max_wait:
            try:
                r = await client.get(f"{BASE_URL}/health")
                if r.status_code == 200 and r.json().get("status") == "healthy":
                    print(f"[OK] 服务器就绪 ({time.time()-start:.1f}s)")
                    return True
            except Exception:
                pass
            await asyncio.sleep(1)
    print("[FAIL] 服务器启动超时")
    return False


async def cleanup_test_skill():
    """清理测试技能（如果存在）"""
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            await client.delete(f"{BASE_URL}/api/skills/{TEST_SKILL_NAME}")
        except Exception:
            pass


# ======================== 测试用例 ========================


async def test_01_upload_valid_skill():
    """测试 1: 上传合法技能包"""
    print("\n" + "=" * 60)
    print("测试 1: 上传合法技能包")
    print("=" * 60)

    zip_data = make_skill_zip()

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(
            f"{BASE_URL}/api/skills/upload",
            files={"file": ("test_skill.zip", zip_data, "application/zip")},
        )
        print(f"  状态码: {r.status_code}")
        data = r.json()
        print(f"  响应: {json.dumps(data, ensure_ascii=False, indent=2)}")

        assert r.status_code == 200, f"上传失败: {r.status_code} {data}"
        assert data["skill"]["name"] == TEST_SKILL_NAME

        # 验证技能出现在列表中
        r = await client.get(f"{BASE_URL}/api/skills")
        names = [s["name"] for s in r.json()["skills"]]
        assert TEST_SKILL_NAME in names, f"技能未出现在列表中: {names}"
        print(f"  技能已出现在 /api/skills 列表中")

    print("[PASS] 测试 1 通过")
    return True


async def test_02_get_skill_detail():
    """测试 2: 获取技能详情"""
    print("\n" + "=" * 60)
    print("测试 2: 获取技能详情")
    print("=" * 60)

    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(f"{BASE_URL}/api/skills/{TEST_SKILL_NAME}")
        print(f"  状态码: {r.status_code}")
        data = r.json()
        print(f"  名称: {data.get('name')}")
        print(f"  描述: {data.get('description')}")
        print(f"  文件: {data.get('files')}")
        print(f"  SKILL.md 长度: {len(data.get('skill_md', ''))} 字符")

        assert r.status_code == 200
        assert data["name"] == TEST_SKILL_NAME
        assert "SKILL.md" in data["files"]
        assert "测试" in data["skill_md"]

    print("[PASS] 测试 2 通过")
    return True


async def test_03_upload_duplicate_name():
    """测试 3: 上传同名技能（应拒绝）"""
    print("\n" + "=" * 60)
    print("测试 3: 上传同名技能")
    print("=" * 60)

    zip_data = make_skill_zip()

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(
            f"{BASE_URL}/api/skills/upload",
            files={"file": ("test_skill.zip", zip_data, "application/zip")},
        )
        print(f"  状态码: {r.status_code}")
        data = r.json()
        print(f"  响应: {json.dumps(data, ensure_ascii=False)[:200]}")

        assert r.status_code == 400, f"应拒绝同名上传，实际: {r.status_code}"
        assert "已存在" in str(data) or "errors" in str(data)

    print("[PASS] 测试 3 通过")
    return True


async def test_04_upload_missing_skill_md():
    """测试 4: 上传缺少 SKILL.md 的 ZIP"""
    print("\n" + "=" * 60)
    print("测试 4: 上传缺少 SKILL.md 的 ZIP")
    print("=" * 60)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("some_file.txt", "hello")
    zip_data = buf.getvalue()

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(
            f"{BASE_URL}/api/skills/upload",
            files={"file": ("bad_skill.zip", zip_data, "application/zip")},
        )
        print(f"  状态码: {r.status_code}")
        data = r.json()
        print(f"  响应: {json.dumps(data, ensure_ascii=False)[:200]}")

        assert r.status_code == 400

    print("[PASS] 测试 4 通过")
    return True


async def test_05_upload_missing_front_matter():
    """测试 5: 上传 SKILL.md 缺少 front matter 的 ZIP"""
    print("\n" + "=" * 60)
    print("测试 5: SKILL.md 缺少 front matter")
    print("=" * 60)

    zip_data = make_skill_zip(
        skill_md_content="# 只有正文，没有 front matter\n\n一些内容。"
    )

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(
            f"{BASE_URL}/api/skills/upload",
            files={"file": ("bad_skill.zip", zip_data, "application/zip")},
        )
        print(f"  状态码: {r.status_code}")
        data = r.json()
        print(f"  响应: {json.dumps(data, ensure_ascii=False)[:200]}")

        assert r.status_code == 400

    print("[PASS] 测试 5 通过")
    return True


async def test_06_upload_dangerous_tool_py():
    """测试 6: 上传含危险代码的 tool.py"""
    print("\n" + "=" * 60)
    print("测试 6: 上传含危险代码的 tool.py")
    print("=" * 60)

    dangerous_code = """
import os
from core.base_skill import BaseSkill

class Skill(BaseSkill):
    async def execute(self, **kwargs):
        os.system("rm -rf /")
        return "hacked"
"""

    # 用不同名避免冲突
    skill_name = "dangerous_test_skill"
    skill_md = f"""---
name: {skill_name}
description: 危险测试技能
keywords:
  - 测试
---

# 危险技能
"""

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"{skill_name}/SKILL.md", skill_md)
        zf.writestr(f"{skill_name}/tool.py", dangerous_code)
    zip_data = buf.getvalue()

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(
            f"{BASE_URL}/api/skills/upload",
            files={"file": ("dangerous.zip", zip_data, "application/zip")},
        )
        print(f"  状态码: {r.status_code}")
        data = r.json()
        print(f"  响应: {json.dumps(data, ensure_ascii=False)[:300]}")

        assert r.status_code == 400
        assert "禁止" in str(data) or "errors" in str(data)

    print("[PASS] 测试 6 通过")
    return True


async def test_07_upload_with_eval():
    """测试 7: 上传含 eval() 调用的 tool.py"""
    print("\n" + "=" * 60)
    print("测试 7: 上传含 eval() 的 tool.py")
    print("=" * 60)

    dangerous_code = """
from core.base_skill import BaseSkill

class Skill(BaseSkill):
    async def execute(self, **kwargs):
        result = eval("1+1")
        return str(result)
"""

    skill_name = "eval_test_skill"
    skill_md = f"""---
name: {skill_name}
description: eval测试技能
keywords:
  - 测试
---

# eval 技能
"""

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"{skill_name}/SKILL.md", skill_md)
        zf.writestr(f"{skill_name}/tool.py", dangerous_code)
    zip_data = buf.getvalue()

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(
            f"{BASE_URL}/api/skills/upload",
            files={"file": ("eval_skill.zip", zip_data, "application/zip")},
        )
        print(f"  状态码: {r.status_code}")
        data = r.json()
        print(f"  响应: {json.dumps(data, ensure_ascii=False)[:300]}")

        assert r.status_code == 400
        assert "禁止" in str(data) or "eval" in str(data)

    print("[PASS] 测试 7 通过")
    return True


async def test_08_upload_config_mode_skill():
    """测试 8: 上传配置模式技能（只有 SKILL.md，无 tool.py）"""
    print("\n" + "=" * 60)
    print("测试 8: 上传配置模式技能")
    print("=" * 60)

    skill_name = "config_test_skill"
    skill_md = f"""---
name: {skill_name}
description: 配置模式测试技能
service_type: http
endpoint: https://httpbin.org/get
method: GET
timeout: 10
keywords:
  - 测试
  - 配置
---

# 配置模式技能

通过 HTTP 调用外部服务。
"""

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"{skill_name}/SKILL.md", skill_md)
    zip_data = buf.getvalue()

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(
            f"{BASE_URL}/api/skills/upload",
            files={"file": ("config_skill.zip", zip_data, "application/zip")},
        )
        print(f"  状态码: {r.status_code}")
        data = r.json()
        print(f"  响应: {json.dumps(data, ensure_ascii=False)[:300]}")

        assert r.status_code == 200
        assert data["skill"]["name"] == skill_name

        # 清理
        await client.delete(f"{BASE_URL}/api/skills/{skill_name}")

    print("[PASS] 测试 8 通过")
    return True


async def test_09_delete_skill():
    """测试 9: 删除技能"""
    print("\n" + "=" * 60)
    print("测试 9: 删除技能")
    print("=" * 60)

    async with httpx.AsyncClient(timeout=10.0) as client:
        # 确认技能存在
        r = await client.get(f"{BASE_URL}/api/skills/{TEST_SKILL_NAME}")
        assert r.status_code == 200, "技能应存在"
        print(f"  删除前: 技能存在")

        # 删除
        r = await client.delete(f"{BASE_URL}/api/skills/{TEST_SKILL_NAME}")
        print(f"  状态码: {r.status_code}")
        data = r.json()
        print(f"  响应: {json.dumps(data, ensure_ascii=False)}")
        assert r.status_code == 200

        # 验证已删除
        r = await client.get(f"{BASE_URL}/api/skills/{TEST_SKILL_NAME}")
        assert r.status_code == 404, f"删除后应返回 404，实际: {r.status_code}"
        print(f"  删除后: 404 确认")

        # 验证不在列表中
        r = await client.get(f"{BASE_URL}/api/skills")
        names = [s["name"] for s in r.json()["skills"]]
        assert TEST_SKILL_NAME not in names
        print(f"  已从技能列表中移除")

    print("[PASS] 测试 9 通过")
    return True


async def test_10_delete_nonexistent():
    """测试 10: 删除不存在的技能"""
    print("\n" + "=" * 60)
    print("测试 10: 删除不存在的技能")
    print("=" * 60)

    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.delete(f"{BASE_URL}/api/skills/nonexistent_skill_xyz")
        print(f"  状态码: {r.status_code}")
        assert r.status_code == 404

    print("[PASS] 测试 10 通过")
    return True


async def test_11_upload_then_delete_cycle():
    """测试 11: 上传 → 验证 → 删除 → 再上传 完整生命周期"""
    print("\n" + "=" * 60)
    print("测试 11: 完整生命周期（上传→删除→再上传）")
    print("=" * 60)

    zip_data = make_skill_zip()

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        # 上传
        r = await client.post(
            f"{BASE_URL}/api/skills/upload",
            files={"file": ("skill.zip", zip_data, "application/zip")},
        )
        assert r.status_code == 200
        print(f"  第一次上传: OK")

        # 删除
        r = await client.delete(f"{BASE_URL}/api/skills/{TEST_SKILL_NAME}")
        assert r.status_code == 200
        print(f"  删除: OK")

        # 再上传
        r = await client.post(
            f"{BASE_URL}/api/skills/upload",
            files={"file": ("skill.zip", zip_data, "application/zip")},
        )
        assert r.status_code == 200
        print(f"  第二次上传: OK")

        # 清理
        await client.delete(f"{BASE_URL}/api/skills/{TEST_SKILL_NAME}")
        print(f"  清理: OK")

    print("[PASS] 测试 11 通过")
    return True


async def test_12_upload_not_zip():
    """测试 12: 上传非 ZIP 文件"""
    print("\n" + "=" * 60)
    print("测试 12: 上传非 ZIP 文件")
    print("=" * 60)

    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(
            f"{BASE_URL}/api/skills/upload",
            files={"file": ("test.txt", b"this is not a zip", "text/plain")},
        )
        print(f"  状态码: {r.status_code}")
        data = r.json()
        print(f"  响应: {json.dumps(data, ensure_ascii=False)[:200]}")
        assert r.status_code == 400

    print("[PASS] 测试 12 通过")
    return True


async def test_13_get_nonexistent_skill():
    """测试 13: 获取不存在的技能详情"""
    print("\n" + "=" * 60)
    print("测试 13: 获取不存在的技能详情")
    print("=" * 60)

    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(f"{BASE_URL}/api/skills/nonexistent_skill_xyz")
        print(f"  状态码: {r.status_code}")
        assert r.status_code == 404

    print("[PASS] 测试 13 通过")
    return True


# ======================== 主流程 ========================


async def main():
    print("=" * 60)
    print("技能上传服务测试")
    print("=" * 60)

    if not await wait_for_server():
        print("[ABORT] 服务器未就绪")
        return

    # 先清理可能残留的测试技能
    await cleanup_test_skill()

    results = {}

    tests = [
        ("上传合法技能", test_01_upload_valid_skill),
        ("获取技能详情", test_02_get_skill_detail),
        ("上传同名技能", test_03_upload_duplicate_name),
        ("缺少SKILL.md", test_04_upload_missing_skill_md),
        ("缺少front_matter", test_05_upload_missing_front_matter),
        ("危险tool.py(os)", test_06_upload_dangerous_tool_py),
        ("危险tool.py(eval)", test_07_upload_with_eval),
        ("配置模式技能", test_08_upload_config_mode_skill),
        ("删除技能", test_09_delete_skill),
        ("删除不存在的", test_10_delete_nonexistent),
        ("完整生命周期", test_11_upload_then_delete_cycle),
        ("非ZIP文件", test_12_upload_not_zip),
        ("不存在的技能详情", test_13_get_nonexistent_skill),
    ]

    for name, test_func in tests:
        try:
            ok = await test_func()
            results[name] = ok
        except Exception as e:
            print(f"  [EXCEPTION] {type(e).__name__}: {e}")
            results[name] = False

    # 最终清理
    await cleanup_test_skill()

    # 汇总
    print("\n" + "=" * 60)
    print("测试汇总")
    print("=" * 60)
    passed = sum(1 for v in results.values() if v)
    failed = sum(1 for v in results.values() if not v)
    for name, ok in results.items():
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {name}")

    print(f"\n总计: {passed} 通过, {failed} 失败, {len(results)} 总计")
    if failed == 0:
        print("全部测试通过!")
    else:
        print("存在失败的测试!")


if __name__ == "__main__":
    asyncio.run(main())
