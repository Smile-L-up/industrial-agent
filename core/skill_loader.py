"""
Skill Loader - 技能加载器
负责加载和管理技能模块

支持分层加载：
  - load_all_metadata()  → 只解析 SKILL.md 元数据（轻量）
  - load_skill_full()    → 按需加载 tool.py 并实例化（重量）
  - load_all()           → 兼容旧接口，一次性加载全部
"""

import os
import re
import sys
import logging
import importlib.util
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from pathlib import Path

logger = logging.getLogger("industrial_agent.skill_loader")

# YAML front matter 正则：匹配 --- 包裹的头部
_FRONT_MATTER_PATTERN = re.compile(
    r"^---\s*\n(.*?)\n---\s*\n",
    re.DOTALL,
)


@dataclass
class SkillMetadata:
    """技能元数据 — 轻量描述，不包含 tool.py 代码"""
    name: str
    description: str
    keywords: List[str] = field(default_factory=list)
    path: str = ""  # 技能目录路径，用于按需加载


def _parse_front_matter(content: str) -> Dict[str, Any]:
    """
    解析 YAML front matter。

    优先使用 PyYAML；如果未安装则回退到简易解析器，
    支持 name / description / keywords 等常见字段。

    Args:
        content: SKILL.md 的完整文本

    Returns:
        解析后的元数据字典，无 front matter 时返回空 dict
    """
    match = _FRONT_MATTER_PATTERN.match(content)
    if not match:
        return {}

    yaml_text = match.group(1)

    # 尝试使用 PyYAML
    try:
        import yaml
        parsed = yaml.safe_load(yaml_text)
        return parsed if isinstance(parsed, dict) else {}
    except ImportError:
        pass

    # 回退：简易解析器
    return _fallback_parse_yaml(yaml_text)


def _fallback_parse_yaml(yaml_text: str) -> Dict[str, Any]:
    """
    简易 YAML 解析回退，基于缩进递归解析，支持：
      - key: value
      - 嵌套字典（按缩进层级）
      - 列表（- item）
      - 列表项内嵌字典（- key:\n    subkey: value）
    """

    def _parse_block(lines: List[str], start: int, base_indent: int) -> tuple:
        """递归解析一个缩进块，返回 (result_dict, next_line_index)"""
        result: Dict[str, Any] = {}
        i = start
        current_key: Optional[str] = None
        current_list: Optional[list] = None

        def _save_pending_list():
            """将挂起的列表保存到 result"""
            nonlocal current_list, current_key
            if current_list is not None:
                if current_key is not None:
                    result[current_key] = current_list
                else:
                    result["_unnamed_list"] = current_list
                current_list = None

        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            # 空行和注释
            if stripped == "" or stripped.startswith("#"):
                i += 1
                continue

            indent = len(line) - len(line.lstrip())

            # 缩进小于基准 → 退回上层（保存挂起的列表后退出）
            if indent < base_indent:
                break

            # ── 缩进大于基准 → 子块，属于上一个 key ──
            if indent > base_indent:
                if current_key is not None:
                    sub_value, i = _parse_block(lines, i, indent)
                    # 子块返回的未命名列表 → 归属到当前 key
                    if "_unnamed_list" in sub_value:
                        result[current_key] = sub_value.pop("_unnamed_list")
                        if sub_value:
                            result[current_key] = sub_value
                    elif current_list is not None:
                        # 列表模式：追加到最后一项或新建
                        if current_list and isinstance(current_list[-1], dict):
                            current_list[-1].update(sub_value)
                        else:
                            current_list.append(sub_value)
                        result[current_key] = current_list
                    else:
                        result[current_key] = sub_value
                    current_key = None
                else:
                    i += 1
                continue

            # ── 列表项（- 开头）──
            if stripped.startswith("- "):
                item_text = stripped[2:].strip()
                if current_list is None:
                    current_list = []

                # 判断是否为 "key: value" 格式
                if ":" in item_text:
                    k, _, v = item_text.partition(":")
                    k = k.strip()
                    v = v.strip()
                    # 排除 URL（://）和引号内含冒号的情况
                    if "://" not in k and not item_text.startswith('"'):
                        item_dict: Dict[str, Any] = {k: _parse_value(v) if v else None}
                        # 检查后续是否有更深缩进的子块
                        if not v and i + 1 < len(lines):
                            next_line = lines[i + 1]
                            next_indent = len(next_line) - len(next_line.lstrip())
                            if next_line.strip() and next_indent > indent:
                                sub, i = _parse_block(lines, i + 1, next_indent)
                                item_dict[k] = sub
                                current_list.append(item_dict)
                                if current_key is not None:
                                    result[current_key] = current_list
                                continue
                        current_list.append(item_dict)
                        # 检查后续更深缩进的行（列表项带值后还有子属性）
                        if i + 1 < len(lines):
                            next_line = lines[i + 1]
                            next_indent = len(next_line) - len(next_line.lstrip())
                            if next_line.strip() and next_indent > indent:
                                sub, i = _parse_block(lines, i + 1, next_indent)
                                item_dict.update(sub)
                                if current_key is not None:
                                    result[current_key] = current_list
                                continue
                    else:
                        current_list.append(_parse_value(item_text))
                else:
                    current_list.append(_parse_value(item_text))

                if current_key is not None:
                    result[current_key] = current_list
                i += 1
                continue

            # ── key: value 行 ──
            if ":" in stripped:
                _save_pending_list()

                key, _, value = stripped.partition(":")
                key = key.strip()
                value = value.strip()
                current_key = key

                if value:
                    result[key] = _parse_value(value)
                else:
                    result.setdefault(key, None)
                i += 1
                continue

            i += 1

        # 循环结束，保存挂起的列表
        _save_pending_list()

        # 仅在顶层清理内部标记键（递归调用时需保留给外层处理）
        if base_indent == 0:
            result.pop("_unnamed_list", None)

        return result, i

    def _parse_value(value: str) -> Any:
        """解析标量值"""
        if not value:
            return value
        # 去除引号
        if (value.startswith('"') and value.endswith('"')) or \
           (value.startswith("'") and value.endswith("'")):
            return value[1:-1]
        # 布尔
        if value.lower() in ("true", "yes"):
            return True
        if value.lower() in ("false", "no"):
            return False
        # 数字
        try:
            return int(value)
        except ValueError:
            pass
        try:
            return float(value)
        except ValueError:
            pass
        return value

    lines = yaml_text.splitlines()
    parsed, _ = _parse_block(lines, 0, 0)
    return parsed


def _strip_front_matter(content: str) -> str:
    """移除 YAML front matter，返回纯 Markdown 正文。"""
    return _FRONT_MATTER_PATTERN.sub("", content, count=1)


class SkillLoader:
    """技能加载器类 — 支持分层加载"""

    def __init__(self, skills_dir: str = "skills"):
        """
        初始化技能加载器

        Args:
            skills_dir: 技能目录路径
        """
        self.skills_dir = Path(skills_dir)
        self.metadata_cache: Dict[str, SkillMetadata] = {}
        self.skill_cache: Dict[str, Any] = {}

    # ==================== 分层加载接口 ====================

    def load_all_metadata(self) -> List[SkillMetadata]:
        """
        扫描所有技能目录，只解析 SKILL.md 元数据（轻量）。

        Returns:
            技能元数据列表
        """
        if not self.skills_dir.exists():
            logger.warning("技能目录不存在：%s", self.skills_dir)
            return []

        metadata_list = []
        for skill_folder in sorted(self.skills_dir.iterdir()):
            if not skill_folder.is_dir():
                continue
            md_file = skill_folder / "SKILL.md"
            if not md_file.exists():
                continue

            try:
                with open(md_file, "r", encoding="utf-8") as f:
                    content = f.read()

                front_matter = _parse_front_matter(content)
                meta = SkillMetadata(
                    name=front_matter.get("name", skill_folder.name),
                    description=front_matter.get("description", ""),
                    keywords=front_matter.get("keywords", []),
                    path=str(skill_folder),
                )
                self.metadata_cache[meta.name] = meta
                metadata_list.append(meta)
                logger.info("发现技能：%s — %s", meta.name, meta.description)
            except Exception as e:
                logger.error("解析技能元数据 %s 失败：%s", skill_folder.name, e, exc_info=True)

        logger.info("共发现 %d 个技能（仅加载元数据）", len(metadata_list))
        return metadata_list

    def load_skill_full(self, skill_name: str) -> Optional[Any]:
        """
        按需加载技能的完整实现（动态导入 tool.py 并实例化）。
        每次调用都会重新加载，确保 SKILL.md / tool.py 的改动立即生效。

        Args:
            skill_name: 技能名称

        Returns:
            BaseSkill 实例，加载失败返回 None
        """
        # 清理旧的实例缓存和模块缓存，确保每次都重新加载
        self.skill_cache.pop(skill_name, None)
        self._clear_module_cache(skill_name)

        # 从 metadata 获取路径
        meta = self.metadata_cache.get(skill_name)
        if meta:
            skill_path = Path(meta.path)
        else:
            skill_path = self.skills_dir / skill_name

        if not skill_path.exists():
            logger.error("技能路径不存在：%s", skill_path)
            return None

        # 解析配置（每次重新读取 SKILL.md）
        config = self._load_config(skill_path)
        if not config and meta:
            config = {
                "name": meta.name,
                "path": meta.path,
                "description": meta.description,
                "keywords": meta.keywords,
            }

        # 加载工具模块（每次重新加载）
        tool_module = self._load_tool_module(skill_path, skill_name)

        # 注入 skill_loader 引用，供复合技能加载子技能
        if config:
            config["_skill_loader"] = self

        skill = None
        if tool_module:
            # ── 代码模式：tool.py 存在 ──
            skill = self._create_skill_instance(skill_name, config or {}, tool_module)
        elif config and config.get("type") == "composite":
            # ── 复合模式：无 tool.py，SKILL.md 中声明了 type: composite ──
            skill = self._create_composite_skill(skill_name, config)
        elif config and config.get("services"):
            # ── 服务模式：无 tool.py，SKILL.md 中声明了 services 列表 ──
            # 统一走 MultiServiceSkill（支持 LLM 规划 + 参数校验 + 缺参追问）
            skill = self._create_multi_service_skill(skill_name, config)
        elif config:
            # ── Prompt 模式：无 tool.py，无 services，只有 SKILL.md ──
            skill = self._create_prompt_skill(skill_name, config)
        else:
            logger.error("技能 %s 配置为空", skill_name)
            return None

        if skill is not None:
            self.skill_cache[skill_name] = skill
            logger.info("已加载技能：%s", skill_name)

        return skill

    # ==================== 兼容旧接口 ====================

    def load_all(self) -> List[Any]:
        """
        一次性加载所有技能（兼容旧接口）。

        Returns:
            技能实例列表
        """
        metadata_list = self.load_all_metadata()
        skills = []
        for meta in metadata_list:
            skill = self.load_skill_full(meta.name)
            if skill:
                skills.append(skill)
        return skills

    def get_skill(self, skill_name: str) -> Optional[Any]:
        """获取已加载的技能（从缓存）"""
        return self.skill_cache.get(skill_name)

    def get_metadata(self, skill_name: str) -> Optional[SkillMetadata]:
        """获取技能元数据"""
        return self.metadata_cache.get(skill_name)

    # ==================== 热加载接口 ====================

    def reload_metadata(self) -> List[SkillMetadata]:
        """
        清空缓存并重新扫描技能目录。
        用于技能上传/删除后热加载。

        Returns:
            更新后的技能元数据列表
        """
        # 清理所有已知技能的 Python 模块缓存
        for name in list(self.metadata_cache.keys()):
            self._clear_module_cache(name)

        self.metadata_cache.clear()
        self.skill_cache.clear()
        logger.info("已清空技能缓存，重新扫描...")
        return self.load_all_metadata()

    def remove_skill(self, skill_name: str) -> bool:
        """
        从缓存中移除指定技能（不删除文件）。

        Args:
            skill_name: 技能名称

        Returns:
            是否成功移除
        """
        removed = False
        if skill_name in self.metadata_cache:
            del self.metadata_cache[skill_name]
            removed = True
        if skill_name in self.skill_cache:
            del self.skill_cache[skill_name]
            removed = True
        if removed:
            logger.info("已从缓存中移除技能：%s", skill_name)
        return removed

    def get_skill_dir(self, skill_name: str) -> Path:
        """
        获取技能目录路径。

        Args:
            skill_name: 技能名称

        Returns:
            技能目录的 Path 对象
        """
        meta = self.metadata_cache.get(skill_name)
        if meta and meta.path:
            return Path(meta.path)
        return self.skills_dir / skill_name

    def get_existing_skill_names(self) -> set:
        """获取所有已知技能名称集合"""
        return set(self.metadata_cache.keys())

    # ==================== 内部方法 ====================

    def _clear_module_cache(self, skill_name: str) -> None:
        """
        清理指定技能的 Python 模块缓存（sys.modules），
        确保重新加载 tool.py 时拿到最新代码。
        """
        module_key = f"skills.{skill_name}.tool"
        if module_key in sys.modules:
            del sys.modules[module_key]
            logger.debug("已清理模块缓存：%s", module_key)

    def _load_config(self, skill_path: Path) -> Optional[Dict]:
        """
        加载技能配置 — 从 SKILL.md 的 YAML front matter 解析元数据。

        Returns:
            包含 name / description / keywords 等字段的字典。
            如果 front matter 中声明了 service 配置，也会一并返回。
        """
        config_file = skill_path / "SKILL.md"
        if not config_file.exists():
            return None

        with open(config_file, "r", encoding="utf-8") as f:
            content = f.read()

        front_matter = _parse_front_matter(content)

        config = {
            "name": front_matter.get("name", skill_path.name),
            "path": str(skill_path),
            "description": front_matter.get("description", ""),
            "keywords": front_matter.get("keywords", []),
            "raw_content": _strip_front_matter(content),
        }

        # 复合技能配置
        skill_type = front_matter.get("type", "")
        if skill_type:
            config["type"] = skill_type
        if front_matter.get("sub_skills"):
            config["sub_skills"] = front_matter["sub_skills"]
        if front_matter.get("steps"):
            config["steps"] = front_matter["steps"]

        # 服务配置（统一使用 services 数组）
        if front_matter.get("services"):
            config["services"] = front_matter["services"]

        return config

    def _load_tool_module(self, skill_path: Path, skill_name: str) -> Optional[Any]:
        """加载工具模块"""
        tool_file = skill_path / "tool.py"
        if not tool_file.exists():
            return None

        spec = importlib.util.spec_from_file_location(
            f"skills.{skill_name}.tool",
            tool_file
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        return module

    def _create_skill_instance(self, skill_name: str, config: Dict, tool_module: Any) -> Optional[Any]:
        """
        创建技能实例。
        要求模块中的 Skill 类必须继承 BaseSkill。
        """
        from core.base_skill import BaseSkill

        if not hasattr(tool_module, "Skill"):
            logger.error(
                "技能 %s 的 tool.py 中缺少 Skill 类。"
                "请定义一个继承 BaseSkill 的 Skill 类。",
                skill_name,
            )
            return None

        skill_cls = tool_module.Skill

        if not (isinstance(skill_cls, type) and issubclass(skill_cls, BaseSkill)):
            logger.error(
                "技能 %s 的 Skill 类必须继承 BaseSkill，当前类型：%s",
                skill_name,
                skill_cls,
            )
            return None

        try:
            return skill_cls(config)
        except Exception as e:
            logger.error("实例化技能 %s 失败：%s", skill_name, e, exc_info=True)
            return None

    def _create_service_skill(self, skill_name: str, config: Dict) -> Optional[Any]:
        """
        根据 service 配置创建服务技能实例（配置模式，无需 tool.py）。
        支持 service_type: http, dify, mcp
        """
        service = config.get("service", {})
        # 兼容两种字段名：service_type 和 type
        service_type = service.get("service_type") or service.get("type", "http")

        if service_type in ("http", "dify"):
            from core.http_skill import HttpSkill
            try:
                return HttpSkill(config)
            except Exception as e:
                logger.error("实例化 HTTP 技能 %s 失败：%s", skill_name, e, exc_info=True)
                return None
        elif service_type == "mcp":
            from core.mcp_skill import McpSkill
            try:
                return McpSkill(config)
            except Exception as e:
                logger.error("实例化 MCP 技能 %s 失败：%s", skill_name, e, exc_info=True)
                return None
        else:
            logger.error("技能 %s 的 service_type '%s' 不受支持（支持：http, dify, mcp）", skill_name, service_type)
            return None

    def _create_composite_skill(self, skill_name: str, config: Dict) -> Optional[Any]:
        """
        创建复合技能实例（配置模式，无需 tool.py）。
        如果技能目录下有 tool.py 且其中定义了 Skill 类，则优先使用自定义实现。
        """
        from core.composite_skill import CompositeSkill

        # 检查是否有自定义 tool.py 实现
        skill_path = Path(config.get("path", self.skills_dir / skill_name))
        tool_module = self._load_tool_module(skill_path, skill_name)
        if tool_module and hasattr(tool_module, "Skill"):
            skill_cls = tool_module.Skill
            if isinstance(skill_cls, type) and issubclass(skill_cls, CompositeSkill):
                try:
                    return skill_cls(config)
                except Exception as e:
                    logger.error("实例化复合技能 %s 失败：%s", skill_name, e, exc_info=True)
                    return None

        # 使用默认 CompositeSkill
        try:
            return CompositeSkill(config)
        except Exception as e:
            logger.error("实例化复合技能 %s 失败：%s", skill_name, e, exc_info=True)
            return None

    def _create_multi_service_skill(self, skill_name: str, config: Dict) -> Optional[Any]:
        """
        创建多服务端点技能实例（配置模式，无需 tool.py）。
        """
        from core.multi_service_skill import MultiServiceSkill
        try:
            return MultiServiceSkill(config)
        except Exception as e:
            logger.error("实例化多服务技能 %s 失败：%s", skill_name, e, exc_info=True)
            return None

    def _create_prompt_skill(self, skill_name: str, config: Dict) -> Optional[Any]:
        """
        创建纯 Prompt 技能实例（无需 tool.py，无需 services）。
        SKILL.md 的内容将作为 system prompt 注入到 LLM。
        """
        from core.prompt_skill import PromptSkill
        try:
            return PromptSkill(config)
        except Exception as e:
            logger.error("实例化 Prompt 技能 %s 失败：%s", skill_name, e, exc_info=True)
            return None
