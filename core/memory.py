"""
Memory - 统一记忆系统
负责管理短期记忆和长期记忆。

重构说明：
  - 统一使用 DatabaseManager 作为长期记忆的持久化后端
  - 移除独立的 JSON 文件存储逻辑，消除与 database.py 的重复
  - 使用 core.logger 替代 print
"""

from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
import uuid

from .logger import get_logger

logger = get_logger("core.memory")


@dataclass
class MemoryItem:
    """记忆项"""
    id: str
    content: str
    type: str  # short_term, long_term, episodic, semantic
    importance: float = 0.5
    created_at: datetime = field(default_factory=datetime.now)
    accessed_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


class Memory:
    """
    统一记忆系统。

    短期记忆：运行时内存列表（不持久化）
    长期记忆：通过 DatabaseManager 持久化到数据库

    使用方式：
        from core.database import DatabaseManager
        db = DatabaseManager()
        memory = Memory(short_term_capacity=10, db=db)
    """

    def __init__(
        self,
        short_term_capacity: int = 10,
        db=None,  # Optional[DatabaseManager]
    ):
        """
        初始化记忆系统

        Args:
            short_term_capacity: 短期记忆容量
            db: DatabaseManager 实例（用于长期记忆持久化）
        """
        self.short_term_capacity = short_term_capacity
        self.db = db

        # 短期记忆（运行时）
        self.short_term: List[MemoryItem] = []

        # 工作记忆（当前上下文）
        self.working: Dict[str, Any] = {}

    # ── 短期记忆 ──────────────────────────────────────

    def add_short_term(self, content: str, metadata: Optional[Dict] = None) -> str:
        """
        添加短期记忆

        Args:
            content: 记忆内容
            metadata: 元数据

        Returns:
            记忆 ID
        """
        item = MemoryItem(
            id=str(uuid.uuid4()),
            content=content,
            type="short_term",
            metadata=metadata or {},
        )

        self.short_term.append(item)

        # 如果超出容量，自动转移到长期记忆
        if len(self.short_term) > self.short_term_capacity:
            oldest = self.short_term.pop(0)
            self._promote_to_long_term(oldest)

        return item.id

    # ── 长期记忆 ──────────────────────────────────────

    def add_long_term(
        self,
        content: str,
        importance: float = 0.5,
        metadata: Optional[Dict] = None,
    ) -> str:
        """
        添加长期记忆（持久化到数据库）

        Args:
            content: 记忆内容
            importance: 重要程度 (0-1)
            metadata: 元数据

        Returns:
            记忆 ID
        """
        item = MemoryItem(
            id=str(uuid.uuid4()),
            content=content,
            type="long_term",
            importance=importance,
            metadata=metadata or {},
        )

        self._save_to_db(item)
        return item.id

    def _promote_to_long_term(self, item: MemoryItem):
        """将短期记忆提升为长期记忆并持久化"""
        item.type = "long_term"
        self._save_to_db(item)
        logger.debug(f"短期记忆 {item.id} 已提升为长期记忆")

    def _save_to_db(self, item: MemoryItem):
        """保存记忆项到数据库"""
        if self.db is None:
            logger.warning("未配置 DatabaseManager，长期记忆将不会持久化")
            return

        try:
            self.db.add_long_term_memory(
                memory_id=item.id,
                content=item.content,
                importance=item.importance,
                metadata=item.metadata,
            )
        except Exception as e:
            logger.error(f"保存长期记忆失败：{e}")

    def get_long_term_memories(self, limit: int = 100) -> List[Dict[str, Any]]:
        """从数据库获取长期记忆"""
        if self.db is None:
            return []
        try:
            return self.db.get_long_term_memories(limit=limit)
        except Exception as e:
            logger.error(f"获取长期记忆失败：{e}")
            return []

    # ── 工作记忆 ──────────────────────────────────────

    def add_working(self, key: str, value: Any):
        """添加工作记忆"""
        self.working[key] = value

    def get_working(self, key: str, default: Any = None) -> Any:
        """获取工作记忆"""
        return self.working.get(key, default)

    def clear_working(self):
        """清空工作记忆"""
        self.working.clear()

    # ── 搜索 ──────────────────────────────────────────

    def search(
        self,
        query: str,
        limit: int = 5,
        memory_type: Optional[str] = None,
    ) -> List[MemoryItem]:
        """
        搜索记忆（短期 + 长期）

        Args:
            query: 搜索关键词
            limit: 返回数量限制
            memory_type: 记忆类型过滤

        Returns:
            匹配的记忆列表
        """
        results: List[MemoryItem] = []

        # 搜索范围
        if memory_type == "short_term":
            pool = self.short_term
        elif memory_type == "long_term":
            # 从数据库获取长期记忆并转换
            db_items = self.get_long_term_memories(limit=1000)
            pool = [
                MemoryItem(
                    id=item.get("id", ""),
                    content=item.get("content", ""),
                    type="long_term",
                    importance=item.get("importance", 0.5),
                    metadata=item.get("metadata", {}),
                )
                for item in db_items
            ]
        else:
            # 全部
            db_items = self.get_long_term_memories(limit=1000)
            pool = list(self.short_term) + [
                MemoryItem(
                    id=item.get("id", ""),
                    content=item.get("content", ""),
                    type="long_term",
                    importance=item.get("importance", 0.5),
                    metadata=item.get("metadata", {}),
                )
                for item in db_items
            ]

        # 关键词匹配
        for item in pool:
            if query.lower() in item.content.lower():
                results.append(item)

        # 按重要性和访问时间排序
        results.sort(key=lambda x: (x.importance, x.accessed_at), reverse=True)

        return results[:limit]

    def get_recent(self, limit: int = 5) -> List[MemoryItem]:
        """获取最近的短期记忆"""
        return self.short_term[-limit:]

    def update_access_time(self, memory_id: str):
        """更新记忆访问时间"""
        for item in self.short_term:
            if item.id == memory_id:
                item.accessed_at = datetime.now()
                break

    # ── 记忆巩固 ──────────────────────────────────────

    def consolidate(self):
        """
        记忆巩固：将重要的短期记忆转移到长期记忆
        """
        promoted = []
        remaining = []
        for item in self.short_term:
            if item.importance > 0.7:
                promoted.append(item)
            else:
                remaining.append(item)

        self.short_term = remaining

        for item in promoted:
            self._promote_to_long_term(item)

        if promoted:
            logger.info(f"记忆巩固：{len(promoted)} 条短期记忆提升为长期记忆")

    # ── 删除 / 清空 ───────────────────────────────────

    def forget(self, memory_id: str) -> bool:
        """
        删除记忆

        Args:
            memory_id: 记忆 ID

        Returns:
            是否成功删除
        """
        # 从短期记忆中删除
        for i, item in enumerate(self.short_term):
            if item.id == memory_id:
                self.short_term.pop(i)
                return True

        # 从数据库中删除长期记忆
        if self.db:
            try:
                self.db.delete_long_term_memory(memory_id)
                return True
            except Exception as e:
                logger.error(f"删除长期记忆失败：{e}")

        return False

    def clear(self):
        """清空所有记忆"""
        self.short_term.clear()
        self.working.clear()
        # 注意：不清空数据库中的长期记忆，仅清空运行时状态

    # ── 序列化 ────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "short_term": [
                {
                    "content": i.content,
                    "type": i.type,
                    "metadata": i.metadata,
                }
                for i in self.short_term
            ],
            "working": self.working,
        }