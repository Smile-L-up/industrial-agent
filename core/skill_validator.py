"""
Skill Validator - 技能校验器
负责校验上传的技能包：解压、结构检查、安全扫描
"""

import ast
import io
import json
import logging
import re
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger("industrial_agent.skill_validator")

# tool.py 中禁止 import 的模块
BLOCKED_MODULES = frozenset({
    "os", "subprocess", "shutil", "sys", "socket",
    "ctypes", "importlib", "code", "codeop",
    "multiprocessing", "signal", "pty", "fcntl",
    "resource", "zipimport", "runpy",
})

# tool.py 中禁止调用的函数
BLOCKED_CALLS = frozenset({
    "eval", "exec", "__import__", "compile", "breakpoint",
})

# 文件名黑名单（不允许出现在技能包中）
BLOCKED_FILES = frozenset({
    ".env", ".env.local", "credentials", "credentials.json",
    "id_rsa", "id_ed25519", ".htpasswd",
})

# 允许上传的文件扩展名
ALLOWED_EXTENSIONS = frozenset({
    ".md", ".py", ".txt", ".json", ".yaml", ".yml",
    ".csv", ".html", ".css", ".js", ".png", ".jpg", ".svg",
})

# ZIP 包大小上限（10MB）
MAX_ZIP_SIZE = 10 * 1024 * 1024

# 解压后总大小上限（20MB）
MAX_UNCOMPRESSED_SIZE = 20 * 1024 * 1024


@dataclass
class ValidationResult:
    """校验结果"""
    valid: bool
    skill_name: str = ""
    skill_description: str = ""
    files: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def validate_skill_zip(zip_bytes: bytes, existing_skills: Optional[set] = None) -> ValidationResult:
    """
    校验技能 ZIP 包

    Args:
        zip_bytes: ZIP 文件的字节内容
        existing_skills: 已有的技能名称集合（用于冲突检查）

    Returns:
        ValidationResult
    """
    result = ValidationResult(valid=False)

    # 1. 检查 ZIP 大小
    if len(zip_bytes) > MAX_ZIP_SIZE:
        result.errors.append(f"ZIP 包过大：{len(zip_bytes)} 字节，上限 {MAX_ZIP_SIZE} 字节")
        return result

    # 2. 解压到临时目录
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
            # 检查压缩炸弹
            total_size = sum(info.file_size for info in zf.infolist())
            if total_size > MAX_UNCOMPRESSED_SIZE:
                result.errors.append(f"解压后文件总大小 {total_size} 字节，超过上限 {MAX_UNCOMPRESSED_SIZE}")
                return result

            # 检查路径穿越
            for info in zf.infolist():
                if info.filename.startswith("/") or ".." in info.filename:
                    result.errors.append(f"非法文件路径: {info.filename}")
                    return result

            # 解压到临时目录
            with tempfile.TemporaryDirectory() as tmp_dir:
                tmp_path = Path(tmp_dir)
                zf.extractall(tmp_path)

                # 查找技能根目录（可能 ZIP 内有一层目录，也可能直接是文件）
                skill_root = _find_skill_root(tmp_path)
                if skill_root is None:
                    result.errors.append("ZIP 包中未找到 SKILL.md 文件")
                    return result

                _validate_skill_dir(skill_root, result, existing_skills)

    except zipfile.BadZipFile:
        result.errors.append("无效的 ZIP 文件格式")
    except Exception as e:
        result.errors.append(f"解压失败：{type(e).__name__}: {e}")

    return result


def extract_skill_zip(zip_bytes: bytes, target_dir: Path) -> ValidationResult:
    """
    解压技能 ZIP 到目标目录（校验通过后调用）

    Args:
        zip_bytes: ZIP 文件字节内容
        target_dir: 目标目录路径（如 skills/{name}/）

    Returns:
        ValidationResult
    """
    result = ValidationResult(valid=False)

    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
            with tempfile.TemporaryDirectory() as tmp_dir:
                tmp_path = Path(tmp_dir)
                zf.extractall(tmp_path)

                skill_root = _find_skill_root(tmp_path)
                if skill_root is None:
                    result.errors.append("ZIP 包中未找到 SKILL.md")
                    return result

                # 复制到目标目录
                if target_dir.exists():
                    import shutil
                    shutil.rmtree(target_dir)

                import shutil
                shutil.copytree(skill_root, target_dir)

                result.valid = True
                result.files = [f.name for f in target_dir.iterdir()]
                logger.info("技能已解压到：%s", target_dir)

    except Exception as e:
        result.errors.append(f"解压失败：{type(e).__name__}: {e}")

    return result


def _find_skill_root(tmp_path: Path) -> Optional[Path]:
    """
    在解压目录中查找技能根目录（包含 SKILL.md 的目录）

    支持两种结构：
    1. ZIP 根目录直接包含 SKILL.md
    2. ZIP 内有一层子目录，子目录内包含 SKILL.md
    """
    # 直接在根目录
    if (tmp_path / "SKILL.md").exists():
        return tmp_path

    # 检查子目录（只往下一层）
    for child in tmp_path.iterdir():
        if child.is_dir() and (child / "SKILL.md").exists():
            return child

    return None


def _validate_skill_dir(
    skill_dir: Path,
    result: ValidationResult,
    existing_skills: Optional[set] = None,
):
    """校验技能目录内容"""

    # ── 1. 检查 SKILL.md ──
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        result.errors.append("缺少 SKILL.md 文件")
        return

    try:
        content = skill_md.read_text(encoding="utf-8")
    except Exception as e:
        result.errors.append(f"读取 SKILL.md 失败：{e}")
        return

    # 解析 front matter
    front_matter = _parse_front_matter(content)
    if not front_matter:
        result.errors.append("SKILL.md 缺少 YAML front matter（需要 --- 包裹的头部）")
        return

    skill_name = front_matter.get("name", "").strip()
    skill_desc = front_matter.get("description", "").strip()

    if not skill_name:
        result.errors.append("SKILL.md 的 front matter 中缺少 name 字段")
        return

    if not skill_desc:
        result.errors.append("SKILL.md 的 front matter 中缺少 description 字段")
        return

    # 检查技能名格式（只允许字母、数字、下划线、中文）
    if not re.match(r'^[\w一-鿿]+$', skill_name):
        result.errors.append(f"技能名 '{skill_name}' 格式不合法（只允许字母、数字、下划线、中文）")
        return

    # 检查名称冲突
    if existing_skills and skill_name in existing_skills:
        result.errors.append(f"技能名 '{skill_name}' 已存在，请使用其他名称或先删除已有技能")
        return

    result.skill_name = skill_name
    result.skill_description = skill_desc

    # ── 2. 检查文件列表 ──
    files = []
    for f in skill_dir.rglob("*"):
        if f.is_file():
            rel = f.relative_to(skill_dir)
            files.append(str(rel))

            # 检查文件名黑名单
            if f.name.lower() in BLOCKED_FILES:
                result.errors.append(f"不允许的文件：{f.name}")
                return

            # 检查扩展名
            if f.suffix and f.suffix.lower() not in ALLOWED_EXTENSIONS:
                result.warnings.append(f"非常见文件类型：{f.name}（{f.suffix}）")

    result.files = files

    # ── 3. 安全扫描 tool.py ──
    tool_py = skill_dir / "tool.py"
    if tool_py.exists():
        scan_errors = scan_tool_py(tool_py)
        if scan_errors:
            result.errors.extend(scan_errors)
            return

    result.valid = True


def scan_tool_py(tool_py_path: Path) -> List[str]:
    """
    静态安全扫描 tool.py

    使用 AST 解析，检查：
    1. import 语句中的黑名单模块
    2. 函数调用中的危险函数

    Returns:
        错误列表，空列表表示安全
    """
    errors = []

    try:
        source = tool_py_path.read_text(encoding="utf-8")
    except Exception as e:
        return [f"读取 tool.py 失败：{e}"]

    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return [f"tool.py 语法错误：{e}"]

    for node in ast.walk(tree):
        # import xxx
        if isinstance(node, ast.Import):
            for alias in node.names:
                root_module = alias.name.split(".")[0]
                if root_module in BLOCKED_MODULES:
                    errors.append(
                        f"tool.py 第 {node.lineno} 行：禁止 import '{alias.name}'"
                    )

        # from xxx import yyy
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                root_module = node.module.split(".")[0]
                if root_module in BLOCKED_MODULES:
                    errors.append(
                        f"tool.py 第 {node.lineno} 行：禁止 from '{node.module}' import"
                    )

        # eval(...), exec(...), etc.
        elif isinstance(node, ast.Call):
            func_name = _get_call_name(node)
            if func_name in BLOCKED_CALLS:
                errors.append(
                    f"tool.py 第 {node.lineno} 行：禁止调用 '{func_name}'"
                )

    return errors


def _get_call_name(node: ast.Call) -> Optional[str]:
    """提取函数调用的名称"""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _parse_front_matter(content: str) -> Optional[dict]:
    """解析 SKILL.md 的 YAML front matter"""
    pattern = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
    match = pattern.match(content)
    if not match:
        return None

    yaml_text = match.group(1)

    # 尝试 PyYAML
    try:
        import yaml
        parsed = yaml.safe_load(yaml_text)
        return parsed if isinstance(parsed, dict) else None
    except ImportError:
        pass

    # 回退：简易解析
    return _simple_yaml_parse(yaml_text)


def _simple_yaml_parse(yaml_text: str) -> dict:
    """简易 YAML 解析（只处理 key: value 和 key: 列表）"""
    result = {}
    current_key = None
    current_list = None

    for line in yaml_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if stripped.startswith("- "):
            if current_key and current_list is not None:
                current_list.append(stripped[2:].strip())
            continue

        if ":" in stripped:
            # 保存上一个列表
            if current_key and current_list is not None:
                result[current_key] = current_list
                current_list = None

            key, _, value = stripped.partition(":")
            key = key.strip()
            value = value.strip()
            current_key = key

            if value:
                # 去引号
                if (value.startswith('"') and value.endswith('"')) or \
                   (value.startswith("'") and value.endswith("'")):
                    value = value[1:-1]
                result[key] = value
            else:
                current_list = []
        else:
            # 续行（列表项的子行）
            if current_key and current_list is not None:
                current_list.append(stripped)

    # 保存最后一个列表
    if current_key and current_list is not None:
        result[current_key] = current_list

    return result
