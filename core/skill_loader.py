"""
Skill Loader - 技能加载器
负责加载和管理技能模块
"""

import os
import logging
import importlib.util
from typing import Dict, List, Any, Optional
from pathlib import Path

logger = logging.getLogger("industrial_agent.skill_loader")


class SkillLoader:
    """技能加载器类"""
    
    def __init__(self, skills_dir: str = "skills"):
        """
        初始化技能加载器
        
        Args:
            skills_dir: 技能目录路径
        """
        self.skills_dir = Path(skills_dir)
        self.skills: Dict[str, Any] = {}
        self.skill_configs: Dict[str, Dict] = {}
    
    def load_all(self) -> List[Any]:
        """
        加载所有技能
        
        Returns:
            技能列表
        """
        if not self.skills_dir.exists():
            logger.warning("技能目录不存在：%s", self.skills_dir)
            return []
        
        skills = []
        for skill_folder in self.skills_dir.iterdir():
            if skill_folder.is_dir():
                try:
                    skill = self.load_skill(skill_folder.name)
                    if skill:
                        skills.append(skill)
                except Exception as e:
                    logger.error("加载技能 %s 失败：%s", skill_folder.name, e, exc_info=True)
        
        return skills
    
    def load_skill(self, skill_name: str) -> Optional[Any]:
        """
        加载单个技能
        
        Args:
            skill_name: 技能名称
            
        Returns:
            技能实例
        """
        skill_path = self.skills_dir / skill_name
        
        if not skill_path.exists():
            logger.error("技能路径不存在：%s", skill_path)
            return None
        
        # 加载配置
        config = self._load_config(skill_path)
        if config:
            self.skill_configs[skill_name] = config
        
        # 加载工具模块
        tool_module = self._load_tool_module(skill_path, skill_name)
        
        if tool_module:
            # 创建技能实例
            skill = self._create_skill_instance(skill_name, config, tool_module)
            self.skills[skill_name] = skill
            return skill
        
        return None
    
    def _load_config(self, skill_path: Path) -> Optional[Dict]:
        """加载技能配置"""
        config_file = skill_path / "SKILL.md"
        if not config_file.exists():
            return None
        
        config = {
            "name": skill_path.name,
            "path": str(skill_path),
            "description": "",
            "tools": [],
            "raw_content": ""
        }
        
        with open(config_file, "r", encoding="utf-8") as f:
            content = f.read()
            config["raw_content"] = content
            
            # 简单解析 SKILL.md 文件
            lines = content.split("\n")
            for line in lines:
                if line.startswith("# "):
                    config["description"] = line[2:].strip()
                elif line.startswith("- "):
                    config["tools"].append(line[2:].strip())
        
        return config
    
    def _load_tool_module(self, skill_path: Path, skill_name: str) -> Optional[Any]:
        """加载工具模块"""
        tool_file = skill_path / "tool.py"
        if not tool_file.exists():
            return None
        
        # 动态导入模块
        spec = importlib.util.spec_from_file_location(
            f"skills.{skill_name}.tool",
            tool_file
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        return module
    
    def _create_skill_instance(self, skill_name: str, config: Dict, tool_module: Any) -> Any:
        """创建技能实例"""
        # 检查模块中是否有 Skill 类
        if hasattr(tool_module, "Skill"):
            return tool_module.Skill(config)
        
        # 否则创建一个包装类
        class SkillWrapper:
            def __init__(self, name, config, module):
                self.name = name
                self.config = config
                self.module = module
                self.description = config.get("description", "")
            
            async def execute(self, task: str, context: Dict, messages: List) -> str:
                if hasattr(self.module, "execute"):
                    return await self.module.execute(task, context, messages)
                return f"技能 {self.name} 未实现 execute 方法"
        
        return SkillWrapper(skill_name, config, tool_module)
    
    def get_skill(self, skill_name: str) -> Optional[Any]:
        """获取已加载的技能"""
        return self.skills.get(skill_name)
    
    def get_skill_config(self, skill_name: str) -> Optional[Dict]:
        """获取技能配置"""
        return self.skill_configs.get(skill_name)
    
    def reload_skill(self, skill_name: str) -> Optional[Any]:
        """重新加载技能"""
        if skill_name in self.skills:
            del self.skills[skill_name]
        return self.load_skill(skill_name)