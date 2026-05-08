"""
Agent State - 代理状态定义
定义代理工作流中的状态数据结构

重构说明：
  - 将单一的 AgentState 拆分为多个子结构体（输入、计划、执行、上下文、元数据）
  - context 从万能字典改为强类型数据类
  - 提供类型安全的访问方法
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from datetime import datetime


# ── 任务定义 ────────────────────────────────────────

@dataclass
class Task:
    """任务定义"""
    id: str
    description: str
    status: str = "pending"  # pending, in_progress, completed, failed
    result: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None


# ── BoundedList（必须在引用它的 dataclass 之前定义） ──

class BoundedList(list):
    """
    带容量上限的列表。
    超出 max_len 时自动从头部裁剪（FIFO），防止无限增长导致内存泄漏。
    """

    def __init__(self, max_len: int = 200, *args):
        self._max_len = max_len
        super().__init__(*args)
        self._trim()

    def _trim(self):
        while len(self) > self._max_len:
            self.pop(0)

    def append(self, item):
        super().append(item)
        self._trim()

    def extend(self, iterable):
        super().extend(iterable)
        self._trim()


# ── 输入状态 ────────────────────────────────────────

@dataclass
class InputState:
    """用户输入相关状态"""
    user_input: str = ""
    messages: List[Dict[str, str]] = field(
        default_factory=lambda: BoundedList(max_len=100)
    )
    image: Optional[Dict[str, str]] = None  # 图片信息（多模态）


# ── 计划状态 ────────────────────────────────────────

@dataclass
class PlanState:
    """计划与任务分解相关状态"""
    plan: Optional[str] = None
    tasks: List[Task] = field(default_factory=list)
    steps: List[str] = field(default_factory=list)  # 任务步骤列表


# ── 执行上下文（强类型，替代万能 context 字典） ──────

@dataclass
class ExecutionContext:
    """
    执行上下文 — 用强类型字段替代原来的 Dict[str, Any]。
    每个字段都有明确的含义，避免随意写入导致不可追踪。
    """
    # 路由相关
    selected_skill: Optional[str] = None
    selected_subtool: Optional[str] = None

    # 思考模式
    thinking_content: Optional[str] = None

    # LLM 使用统计
    usage: Optional[Dict[str, int]] = None

    # 扩展字段（仅在确实无法预先定义时使用）
    extra: Dict[str, Any] = field(default_factory=dict)

    # ── 通用访问接口（向后兼容） ──

    def get(self, key: str, default: Any = None) -> Any:
        """向后兼容的字典式访问，优先查找已知字段，回退到 extra"""
        if hasattr(self, key):
            val = getattr(self, key)
            return val if val is not None else default
        return self.extra.get(key, default)

    def set(self, key: str, value: Any):
        """向后兼容的字典式写入。如果 key 是已知字段则直接设置，否则写入 extra"""
        if hasattr(self, key) and key != "extra":
            setattr(self, key, value)
        else:
            self.extra[key] = value

    def __contains__(self, key: str) -> bool:
        if hasattr(self, key) and key != "extra":
            return getattr(self, key) is not None
        return key in self.extra

    def __getitem__(self, key: str) -> Any:
        if hasattr(self, key) and key != "extra":
            val = getattr(self, key)
            if val is not None:
                return val
        return self.extra[key]

    def __setitem__(self, key: str, value: Any):
        self.set(key, value)

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for fld_name in ("selected_skill", "selected_subtool",
                         "thinking_content", "usage"):
            val = getattr(self, fld_name)
            if val is not None:
                result[fld_name] = val
        result.update(self.extra)
        return result


# ── 执行记录 ────────────────────────────────────────

@dataclass
class ExecutionRecord:
    """工具调用和结果的执行记录（带容量上限）"""
    tool_calls: List[Dict[str, Any]] = field(
        default_factory=lambda: BoundedList(max_len=200)
    )
    tool_results: List[Dict[str, Any]] = field(
        default_factory=lambda: BoundedList(max_len=200)
    )
    action_history: List[Dict[str, Any]] = field(
        default_factory=lambda: BoundedList(max_len=200)
    )

    def add_tool_call(self, tool: str, args: Dict[str, Any]):
        self.tool_calls.append({"tool": tool, "args": args})

    def add_tool_result(self, tool: str, result: Any, success: bool = True):
        self.tool_results.append({
            "tool": tool,
            "result": result,
            "success": success,
        })

    def add_action(self, action: Dict[str, Any]):
        self.action_history.append(action)


# ── 元数据 ──────────────────────────────────────────

@dataclass
class AgentMetadata:
    """代理元数据"""
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def touch(self):
        """更新 updated_at"""
        self.updated_at = datetime.now()


# ── 主状态类（组合以上子结构） ──────────────────────

class AgentState:
    """
    代理状态 — 组合各子结构体，提供统一的访问接口。

    使用方式示例：
        state = AgentState()
        state.input.user_input = "查询北京天气"
        state.plan.tasks.append(Task(id="1", description="查询天气"))
        state.execution_context.selected_skill = "weather_report"
    """

    def __init__(self):
        # 子结构
        self.input: InputState = InputState()
        self.plan: PlanState = PlanState()
        self.execution_context: ExecutionContext = ExecutionContext()
        self.execution_record: ExecutionRecord = ExecutionRecord()
        self.metadata: AgentMetadata = AgentMetadata()

        # ── 兼容旧接口的直接属性映射 ──
        # 这些属性通过 property 代理到子结构，
        # 使得外部代码无需一次性全部迁移。

        # 当前执行状态
        self.current_task: Optional[Task] = None
        self.current_tool: Optional[str] = None

        # 上下文信息
        self.retrieved_docs: List[Dict[str, Any]] = []

        # 状态标记
        self.is_complete: bool = False
        self.error: Optional[str] = None
        self.final_result: Optional[str] = None

    # ── 向后兼容属性（代理到子结构） ─────────────────

    @property
    def user_input(self) -> str:
        return self.input.user_input

    @user_input.setter
    def user_input(self, value: str):
        self.input.user_input = value

    @property
    def messages(self) -> List[Dict[str, str]]:
        return self.input.messages

    @messages.setter
    def messages(self, value: List[Dict[str, str]]):
        self.input.messages = value

    @property
    def image(self) -> Optional[Dict[str, str]]:
        return self.input.image

    @image.setter
    def image(self, value: Optional[Dict[str, str]]):
        self.input.image = value

    @property
    def plan_text(self) -> Optional[str]:
        return self.plan.plan

    @plan_text.setter
    def plan_text(self, value: Optional[str]):
        self.plan.plan = value

    @property
    def tasks(self) -> List[Task]:
        return self.plan.tasks

    @property
    def steps(self) -> List[str]:
        return self.plan.steps

    @property
    def context(self) -> ExecutionContext:
        return self.execution_context

    @context.setter
    def context(self, value):
        """允许旧代码直接赋值字典 — 自动转换为 ExecutionContext"""
        if isinstance(value, ExecutionContext):
            self.execution_context = value
        elif isinstance(value, dict):
            for k, v in value.items():
                self.execution_context.set(k, v)

    @property
    def tool_calls(self) -> List[Dict[str, Any]]:
        return self.execution_record.tool_calls

    @property
    def tool_results(self) -> List[Dict[str, Any]]:
        return self.execution_record.tool_results

    @property
    def action_history(self) -> List[Dict[str, Any]]:
        return self.execution_record.action_history

    # ── 便捷方法 ─────────────────────────────────────

    def add_message(self, role: str, content: str):
        """添加消息"""
        self.input.messages.append({"role": role, "content": content})
        self.metadata.touch()

    def add_task(self, task: Task):
        """添加任务"""
        self.plan.tasks.append(task)
        self.metadata.touch()

    def update_current_task(self, task: Task):
        """更新当前任务"""
        self.current_task = task
        self.metadata.touch()

    def add_action(self, action: Dict[str, Any]):
        """添加动作历史"""
        self.execution_record.add_action(action)
        self.metadata.touch()

    def set_complete(self):
        """标记为完成"""
        self.is_complete = True
        self.metadata.touch()

    def set_error(self, error: str):
        """设置错误"""
        self.error = error
        self.metadata.touch()

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "user_input": self.input.user_input,
            "messages": self.input.messages,
            "image": self.input.image,
            "plan": self.plan.plan,
            "steps": self.plan.steps,
            "tasks": [
                {
                    "id": t.id,
                    "description": t.description,
                    "status": t.status,
                    "result": t.result,
                    "error": t.error
                }
                for t in self.plan.tasks
            ],
            "current_task": self.current_task.id if self.current_task else None,
            "current_tool": self.current_tool,
            "action_history": self.execution_record.action_history,
            "tool_calls": self.execution_record.tool_calls,
            "tool_results": self.execution_record.tool_results,
            "context": self.execution_context.to_dict(),
            "is_complete": self.is_complete,
            "error": self.error,
            "final_result": self.final_result,
            "created_at": self.metadata.created_at.isoformat(),
            "updated_at": self.metadata.updated_at.isoformat(),
        }