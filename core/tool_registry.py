"""
Tool Registry - 工具注册表
负责注册和管理可用工具
"""

import logging
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger("industrial_agent.tool_registry")


@dataclass
class ToolDefinition:
    """工具定义"""
    name: str
    description: str
    func: Callable
    parameters: Dict[str, Any] = field(default_factory=dict)
    category: str = "general"
    created_at: datetime = field(default_factory=datetime.now)
    enabled: bool = True


class ToolRegistry:
    """工具注册表类"""
    
    _instance: Optional["ToolRegistry"] = None
    
    def __new__(cls) -> "ToolRegistry":
        """单例模式"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.tools: Dict[str, ToolDefinition] = {}
        self.categories: Dict[str, List[str]] = {}
    
    @classmethod
    def get_instance(cls) -> "ToolRegistry":
        """获取单例实例"""
        return cls()
    
    def register(
        self,
        name: str,
        description: str,
        func: Callable,
        parameters: Optional[Dict[str, Any]] = None,
        category: str = "general"
    ):
        """
        注册工具
        
        Args:
            name: 工具名称
            description: 工具描述
            func: 工具函数
            parameters: 参数定义
            category: 工具分类
        """
        if name in self.tools:
            logger.warning("工具 %s 已存在，将被覆盖", name)
        
        tool_def = ToolDefinition(
            name=name,
            description=description,
            func=func,
            parameters=parameters or {},
            category=category
        )
        
        self.tools[name] = tool_def
        
        # 添加到分类
        if category not in self.categories:
            self.categories[category] = []
        self.categories[category].append(name)
    
    def unregister(self, name: str):
        """注销工具"""
        if name in self.tools:
            tool = self.tools.pop(name)
            if tool.category in self.categories:
                self.categories[tool.category].remove(name)
    
    def get(self, name: str) -> Optional[ToolDefinition]:
        """获取工具定义"""
        return self.tools.get(name)
    
    def get_tool_func(self, name: str) -> Optional[Callable]:
        """获取工具函数"""
        tool = self.tools.get(name)
        return tool.func if tool else None
    
    def list_tools(self, category: Optional[str] = None) -> List[str]:
        """列出所有工具"""
        if category:
            return self.categories.get(category, [])
        return list(self.tools.keys())
    
    def list_categories(self) -> List[str]:
        """列出所有分类"""
        return list(self.categories.keys())
    
    def enable(self, name: str):
        """启用工具"""
        if name in self.tools:
            self.tools[name].enabled = True
    
    def disable(self, name: str):
        """禁用工具"""
        if name in self.tools:
            self.tools[name].enabled = False
    
    def is_enabled(self, name: str) -> bool:
        """检查工具是否启用"""
        tool = self.tools.get(name)
        return tool.enabled if tool else False
    
    def execute(self, name: str, **kwargs) -> Any:
        """执行工具"""
        tool = self.tools.get(name)
        if not tool:
            raise ValueError(f"工具不存在：{name}")
        if not tool.enabled:
            raise ValueError(f"工具已禁用：{name}")
        return tool.func(**kwargs)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            name: {
                "description": tool.description,
                "parameters": tool.parameters,
                "category": tool.category,
                "enabled": tool.enabled
            }
            for name, tool in self.tools.items()
        }
    
    def clear(self):
        """清空所有工具"""
        self.tools.clear()
        self.categories.clear()


# 装饰器用于快速注册工具
def tool(
    name: str,
    description: str,
    parameters: Optional[Dict[str, Any]] = None,
    category: str = "general"
):
    """工具注册装饰器"""
    def decorator(func: Callable):
        registry = ToolRegistry.get_instance()
        registry.register(
            name=name,
            description=description,
            func=func,
            parameters=parameters,
            category=category
        )
        return func
    return decorator