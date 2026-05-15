"""
Database Manager - 数据库管理层
支持 SQLite 和 MySQL，通过配置切换
"""

import json
import os
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from contextlib import contextmanager
import sqlite3
import threading
import queue

logger = logging.getLogger("industrial_agent.database")

# 单例锁：确保并发场景下只初始化一次
_db_init_lock = threading.Lock()


class DatabaseManager:
    """
    数据库管理器（单例模式）

    同一组配置参数只会创建一次表。多次实例化时直接复用已有的表结构，
    避免重复执行 CREATE TABLE / CREATE INDEX 的开销。
    """

    # 类级别缓存：记录已初始化过的配置指纹
    _initialized_fingerprints: set = set()

    def __new__(cls, db_type="sqlite", db_path=None, host=None, port=None,
                user=None, password=None, database=None, **kwargs):
        """单例：相同配置只创建一个实例"""
        # 统一为 kwargs 形式构造指纹
        fp = cls._make_fingerprint({
            "db_type": db_type, "db_path": db_path, "host": host,
            "port": port, "database": database,
        })
        if not hasattr(cls, "_instances"):
            cls._instances: Dict[str, "DatabaseManager"] = {}
        if fp not in cls._instances:
            instance = super().__new__(cls)
            cls._instances[fp] = instance
        return cls._instances[fp]

    @staticmethod
    def _make_fingerprint(kwargs: dict) -> str:
        """根据关键配置参数生成唯一指纹"""
        db_type = kwargs.get("db_type", "sqlite")
        if db_type == "sqlite":
            return f"sqlite:{kwargs.get('db_path', 'data/agent.db')}"
        else:
            return (
                f"mysql:{kwargs.get('host', 'localhost')}:"
                f"{kwargs.get('port', 3306)}/"
                f"{kwargs.get('database', 'agent_db')}"
            )

    def __init__(
        self,
        db_type: str = "sqlite",
        db_path: Optional[str] = None,
        host: Optional[str] = None,
        port: Optional[int] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        database: Optional[str] = None
    ):
        """
        初始化数据库管理器
        
        Args:
            db_type: 数据库类型 (sqlite, mysql)
            db_path: SQLite 数据库文件路径
            host: MySQL 主机地址
            port: MySQL 端口
            user: MySQL 用户名
            password: MySQL 密码
            database: 数据库名称
        """
        # 防止重复初始化（__init__ 会在每次 __new__ 返回已有实例时再次调用）
        fp = self._make_fingerprint({
            "db_type": db_type, "db_path": db_path, "host": host,
            "port": port, "database": database,
        })
        if fp in self._initialized_fingerprints:
            return  # 已初始化过，跳过

        self.db_type = db_type
        self.db_path = db_path or "data/agent.db"
        self.host = host or "localhost"
        self.port = port or 3306
        self.user = user or "root"
        self.password = password or ""
        self.database = database or "agent_db"
        
        # 确保 SQLite 目录存在
        if self.db_type == "sqlite":
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        # SQL 占位符：MySQL 用 %s，SQLite 用 ?
        self._placeholder = "%s" if self.db_type == "mysql" else "?"
        
        # 连接池配置
        self._pool_lock = threading.Lock()
        
        if self.db_type == "sqlite":
            # SQLite: 使用线程本地存储，每个线程一个连接
            # 启用 WAL 模式以支持并发读
            self._thread_local = threading.local()
            self._sqlite_connections_lock = threading.Lock()
        elif self.db_type == "mysql":
            # MySQL: 使用队列连接池
            self._pool_size = min(10, os.cpu_count() or 4)
            self._pool: queue.Queue = queue.Queue(maxsize=self._pool_size)
            self._pool_created = 0
        
        # 创建表（带锁，确保并发安全）
        with _db_init_lock:
            if fp not in self._initialized_fingerprints:
                self._create_tables()
                self._initialized_fingerprints.add(fp)
    
    def _create_sqlite_connection(self) -> sqlite3.Connection:
        """创建一个新的 SQLite 连接，启用 WAL 模式"""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")  # WAL 模式支持并发读
        conn.execute("PRAGMA busy_timeout=5000")  # 5 秒锁等待超时
        conn.execute("PRAGMA foreign_keys=ON")     # 启用外键约束
        return conn
    
    def _get_sqlite_connection(self) -> sqlite3.Connection:
        """获取线程本地的 SQLite 连接（每线程复用）"""
        conn = getattr(self._thread_local, "connection", None)
        if conn is None:
            conn = self._create_sqlite_connection()
            self._thread_local.connection = conn
        # 检查连接是否仍然可用
        try:
            conn.execute("SELECT 1")
        except (sqlite3.ProgrammingError, sqlite3.OperationalError):
            conn = self._create_sqlite_connection()
            self._thread_local.connection = conn
        return conn
    
    def _get_mysql_connection(self):
        """从连接池获取 MySQL 连接"""
        try:
            import pymysql
        except ImportError:
            raise ImportError("请安装 pymysql: pip install pymysql")
        
        # 尝试从池中获取已有连接
        try:
            conn = self._pool.get_nowait()
            # 验证连接是否仍然有效
            try:
                conn.ping(reconnect=True)
                return conn
            except Exception:
                # 连接已断开，创建新的
                pass
        except queue.Empty:
            pass
        
        # 如果池未满，创建新连接
        with self._pool_lock:
            if self._pool_created < self._pool_size:
                self._pool_created += 1
                try:
                    return pymysql.connect(
                        host=self.host,
                        port=self.port,
                        user=self.user,
                        password=self.password,
                        database=self.database,
                        charset="utf8mb4",
                        cursorclass=pymysql.cursors.DictCursor,
                        autocommit=False
                    )
                except Exception:
                    self._pool_created -= 1
                    raise
        
        # 池已满且无可用连接，阻塞等待
        return self._pool.get(timeout=10.0)
    
    def _return_mysql_connection(self, conn):
        """归还 MySQL 连接到连接池"""
        try:
            self._pool.put_nowait(conn)
        except queue.Full:
            # 池满，关闭多余连接
            try:
                conn.close()
            except Exception:
                pass
    
    def _get_connection(self):
        """获取数据库连接（兼容旧接口，供 _create_tables 使用）"""
        if self.db_type == "sqlite":
            return self._create_sqlite_connection()
        elif self.db_type == "mysql":
            return self._get_mysql_connection()
        else:
            raise ValueError(f"不支持的数据库类型：{self.db_type}")
    
    @contextmanager
    def get_cursor(self):
        """获取数据库游标（上下文管理器，支持连接复用）"""
        if self.db_type == "sqlite":
            # SQLite 使用线程本地连接，不关闭（复用）
            conn = self._get_sqlite_connection()
            try:
                cursor = conn.cursor()
                yield cursor
                conn.commit()
            except Exception as e:
                try:
                    conn.rollback()
                except Exception:
                    pass
                # 如果是致命错误（如数据库损坏），丢弃连接
                if isinstance(e, (sqlite3.DatabaseError, sqlite3.IntegrityError)):
                    logger.error(f"SQLite 错误: {e}")
                raise e
            # SQLite 连接不关闭，保留在 thread_local 中复用
        elif self.db_type == "mysql":
            # MySQL 从池中获取，用完归还
            conn = self._get_mysql_connection()
            try:
                cursor = conn.cursor()
                yield cursor
                conn.commit()
            except Exception as e:
                try:
                    conn.rollback()
                except Exception:
                    logger.warning(f"MySQL rollback 失败: {e}")
                logger.error(f"MySQL 错误: {e}")
                raise e
            finally:
                self._return_mysql_connection(conn)
    
    def _create_tables(self):
        """创建数据库表"""
        if self.db_type == "sqlite":
            self._create_sqlite_tables()
        elif self.db_type == "mysql":
            self._create_mysql_tables()
    
    def _create_sqlite_tables(self):
        """创建 SQLite 数据表"""
        with self.get_cursor() as cursor:
            # 会话表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_used_at TEXT NOT NULL,
                    metadata TEXT
                )
            """)
            
            # 对话历史表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS conversation_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    message_index INTEGER NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                )
            """)
            
            # 创建索引
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_history_session_id 
                ON conversation_history(session_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_history_created_at 
                ON conversation_history(created_at)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_sessions_last_used 
                ON sessions(last_used_at)
            """)
            
            # 长期记忆表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS long_term_memories (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    type TEXT NOT NULL,
                    importance REAL DEFAULT 0.5,
                    created_at TEXT NOT NULL,
                    accessed_at TEXT NOT NULL,
                    metadata TEXT,
                    session_id TEXT
                )
            """)
            
            # 动作历史表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS action_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    action_data TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS image_assets (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    data_base64 TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    source_url TEXT,
                    summary TEXT,
                    metadata TEXT,
                    created_at TEXT NOT NULL,
                    last_used_at TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_image_assets_session_id
                ON image_assets(session_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_image_assets_sha256
                ON image_assets(sha256)
            """)
    
    def _create_mysql_tables(self):
        """创建 MySQL 数据表"""
        with self.get_cursor() as cursor:
            # 会话表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id VARCHAR(64) PRIMARY KEY,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    last_used_at DATETIME NOT NULL,
                    metadata TEXT
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            
            # 对话历史表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS conversation_history (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    session_id VARCHAR(64) NOT NULL,
                    role VARCHAR(16) NOT NULL,
                    content LONGTEXT NOT NULL,
                    created_at DATETIME NOT NULL,
                    message_index INT NOT NULL,
                    INDEX idx_session_id (session_id),
                    INDEX idx_created_at (created_at),
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            
            # 长期记忆表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS long_term_memories (
                    id VARCHAR(64) PRIMARY KEY,
                    content LONGTEXT NOT NULL,
                    type VARCHAR(32) NOT NULL,
                    importance FLOAT DEFAULT 0.5,
                    created_at DATETIME NOT NULL,
                    accessed_at DATETIME NOT NULL,
                    metadata TEXT,
                    session_id VARCHAR(64),
                    INDEX idx_session_id (session_id),
                    INDEX idx_type (type)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            
            # 动作历史表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS action_history (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    session_id VARCHAR(64) NOT NULL,
                    action_type VARCHAR(64) NOT NULL,
                    action_data LONGTEXT NOT NULL,
                    created_at DATETIME NOT NULL,
                    INDEX idx_session_id (session_id),
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS image_assets (
                    id VARCHAR(80) PRIMARY KEY,
                    session_id VARCHAR(64) NOT NULL,
                    sha256 VARCHAR(64) NOT NULL,
                    mime_type VARCHAR(64) NOT NULL,
                    data_base64 LONGTEXT NOT NULL,
                    size_bytes BIGINT NOT NULL,
                    source_url TEXT,
                    summary TEXT,
                    metadata TEXT,
                    created_at DATETIME NOT NULL,
                    last_used_at DATETIME NOT NULL,
                    INDEX idx_session_id (session_id),
                    INDEX idx_sha256 (sha256),
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
    
    # ==================== 会话管理 ====================
    
    def create_session(self, session_id: str, metadata: Optional[Dict] = None) -> bool:
        """创建新会话"""
        now = datetime.now().isoformat()
        placeholder = self._placeholder
        with self.get_cursor() as cursor:
            cursor.execute(f"""
                INSERT INTO sessions (id, created_at, updated_at, last_used_at, metadata)
                VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})
            """, (session_id, now, now, now, json.dumps(metadata or {})))
        return True
    
    def get_session(self, session_id: str) -> Optional[Dict]:
        """获取会话信息"""
        placeholder = self._placeholder
        with self.get_cursor() as cursor:
            cursor.execute(f"SELECT * FROM sessions WHERE id = {placeholder}", (session_id,))
            row = cursor.fetchone()
            if row:
                if self.db_type == "sqlite":
                    return {
                        "id": row[0],
                        "created_at": row[1],
                        "updated_at": row[2],
                        "last_used_at": row[3],
                        "metadata": json.loads(row[4]) if row[4] else {}
                    }
                else:
                    return {
                        "id": row["id"],
                        "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else str(row["created_at"]),
                        "updated_at": row["updated_at"].isoformat() if hasattr(row["updated_at"], "isoformat") else str(row["updated_at"]),
                        "last_used_at": row["last_used_at"].isoformat() if hasattr(row["last_used_at"], "isoformat") else str(row["last_used_at"]),
                        "metadata": json.loads(row["metadata"]) if row["metadata"] else {}
                    }
        return None
    
    def update_session_last_used(self, session_id: str) -> bool:
        """更新会话最后使用时间"""
        now = datetime.now().isoformat()
        placeholder = self._placeholder
        with self.get_cursor() as cursor:
            cursor.execute(f"""
                UPDATE sessions SET last_used_at = {placeholder}, updated_at = {placeholder} WHERE id = {placeholder}
            """, (now, now, session_id))
        return True
    
    def delete_session(self, session_id: str) -> bool:
        """删除会话"""
        placeholder = self._placeholder
        with self.get_cursor() as cursor:
            cursor.execute(f"DELETE FROM image_assets WHERE session_id = {placeholder}", (session_id,))
            cursor.execute(f"DELETE FROM conversation_history WHERE session_id = {placeholder}", (session_id,))
            cursor.execute(f"DELETE FROM sessions WHERE id = {placeholder}", (session_id,))
        return True
    
    def cleanup_expired_sessions(self, ttl_minutes: int = 30) -> int:
        """清理过期会话"""
        cutoff = (datetime.now() - timedelta(minutes=ttl_minutes)).isoformat()
        # MySQL 使用 %s 占位符，SQLite 使用 ? 占位符
        placeholder = self._placeholder
        with self.get_cursor() as cursor:
            cursor.execute(f"SELECT id FROM sessions WHERE last_used_at < {placeholder}", (cutoff,))
            expired_ids = []
            for row in cursor.fetchall():
                if self.db_type == "mysql" and isinstance(row, dict):
                    expired_ids.append(row["id"])
                else:
                    expired_ids.append(row[0])
            
            cursor.execute(f"DELETE FROM conversation_history WHERE session_id IN (SELECT id FROM sessions WHERE last_used_at < {placeholder})", (cutoff,))
            cursor.execute(f"DELETE FROM image_assets WHERE session_id IN (SELECT id FROM sessions WHERE last_used_at < {placeholder})", (cutoff,))
            cursor.execute(f"DELETE FROM sessions WHERE last_used_at < {placeholder}", (cutoff,))
        
        return len(expired_ids)
    
    def get_session_count(self) -> int:
        """获取当前会话数"""
        with self.get_cursor() as cursor:
            cursor.execute("SELECT COUNT(*) as count FROM sessions")
            row = cursor.fetchone()
            if self.db_type == "mysql" and isinstance(row, dict):
                return row.get("count", 0)
            elif isinstance(row, (list, tuple)):
                return row[0]
            elif isinstance(row, dict):
                # SQLite 也可能返回 dict，尝试多种键名
                return row.get("count", row.get("COUNT(*)", 0))
            else:
                return 0
    
    # ==================== 对话历史管理 ====================
    
    def add_message(
        self,
        session_id: str,
        role: str,
        content: Any,
        message_index: Optional[int] = None
    ) -> int:
        """添加对话消息"""
        now = datetime.now().isoformat()
        placeholder = self._placeholder
        
        # 将 content 转换为 JSON 字符串（支持多模态消息，content 可能是列表）
        if isinstance(content, (list, dict)):
            content_str = json.dumps(content, ensure_ascii=False)
        else:
            content_str = str(content) if content is not None else ""
        
        with self.get_cursor() as cursor:
            if message_index is None:
                cursor.execute(f"""
                    SELECT COALESCE(MAX(message_index), -1) + 1 AS next_index FROM conversation_history WHERE session_id = {placeholder}
                """, (session_id,))
                row = cursor.fetchone()
                # 处理 MySQL (dict) 和 SQLite (tuple) 的不同返回格式
                if isinstance(row, dict):
                    message_index = row.get("next_index", 0)
                else:
                    message_index = row[0] if row else 0
            
            cursor.execute(f"""
                INSERT INTO conversation_history (session_id, role, content, created_at, message_index)
                VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})
            """, (session_id, role, content_str, now, message_index))
        
        return message_index
    
    def get_messages(self, session_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """获取对话历史"""
        placeholder = self._placeholder
        with self.get_cursor() as cursor:
            cursor.execute(f"""
                SELECT role, content, created_at, message_index 
                FROM conversation_history 
                WHERE session_id = {placeholder} 
                ORDER BY message_index ASC 
                LIMIT {placeholder}
            """, (session_id, limit))
            
            messages = []
            for row in cursor.fetchall():
                if self.db_type == "mysql" and isinstance(row, dict):
                    messages.append({
                        "role": row["role"],
                        "content": row["content"],
                        "created_at": row["created_at"],
                        "message_index": row["message_index"]
                    })
                else:
                    messages.append({
                        "role": row[0],
                        "content": row[1],
                        "created_at": row[2],
                        "message_index": row[3]
                    })
            return messages
    
    def get_messages_count(self, session_id: str) -> int:
        """获取消息数量"""
        placeholder = self._placeholder
        with self.get_cursor() as cursor:
            cursor.execute(f"SELECT COUNT(*) as count FROM conversation_history WHERE session_id = {placeholder}", (session_id,))
            row = cursor.fetchone()
            if isinstance(row, dict):
                return row.get("count", 0)
            return row[0]
    
    def clear_history(self, session_id: str) -> bool:
        """清空对话历史"""
        placeholder = self._placeholder
        with self.get_cursor() as cursor:
            cursor.execute(f"DELETE FROM conversation_history WHERE session_id = {placeholder}", (session_id,))
        return True
    
    def trim_history(self, session_id: str, max_history: int) -> bool:
        """裁剪历史，只保留最新的 max_history 条"""
        placeholder = self._placeholder
        with self.get_cursor() as cursor:
            cursor.execute(f"""
                SELECT message_index FROM conversation_history 
                WHERE session_id = {placeholder} 
                ORDER BY message_index DESC 
                LIMIT 1 OFFSET {placeholder}
            """, (session_id, max_history - 1))
            
            rows = cursor.fetchall()
            if rows:
                if self.db_type == "mysql" and isinstance(rows[0], dict):
                    max_keep_index = rows[0]["message_index"]
                else:
                    max_keep_index = rows[0][0]
                cursor.execute(f"""
                    DELETE FROM conversation_history 
                    WHERE session_id = {placeholder} AND message_index < {placeholder}
                """, (session_id, max_keep_index))
        return True

    # ==================== 图片资产管理 ====================

    def upsert_image_asset(
        self,
        session_id: str,
        mime_type: str,
        data_base64: str,
        sha256: str,
        size_bytes: int,
        source_url: Optional[str] = None,
        summary: Optional[str] = None,
        metadata: Optional[Dict] = None
    ) -> str:
        """保存图片资产并返回轻量引用 ID。"""
        now = datetime.now().isoformat()
        image_id = f"img_{sha256[:16]}_{session_id[:8]}"
        placeholder = self._placeholder

        with self.get_cursor() as cursor:
            cursor.execute(f"SELECT id FROM image_assets WHERE id = {placeholder}", (image_id,))
            exists = cursor.fetchone()
            if exists:
                cursor.execute(f"""
                    UPDATE image_assets
                    SET last_used_at = {placeholder}, summary = {placeholder}, source_url = {placeholder}
                    WHERE id = {placeholder}
                """, (now, summary, source_url, image_id))
            else:
                cursor.execute(f"""
                    INSERT INTO image_assets (
                        id, session_id, sha256, mime_type, data_base64, size_bytes,
                        source_url, summary, metadata, created_at, last_used_at
                    )
                    VALUES (
                        {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder},
                        {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}
                    )
                """, (
                    image_id,
                    session_id,
                    sha256,
                    mime_type,
                    data_base64,
                    size_bytes,
                    source_url,
                    summary,
                    json.dumps(metadata or {}, ensure_ascii=False),
                    now,
                    now
                ))

        return image_id

    def get_image_asset(self, image_id: str) -> Optional[Dict[str, Any]]:
        """获取图片资产。"""
        placeholder = self._placeholder
        with self.get_cursor() as cursor:
            cursor.execute(f"""
                SELECT id, session_id, sha256, mime_type, data_base64, size_bytes,
                       source_url, summary, metadata, created_at, last_used_at
                FROM image_assets
                WHERE id = {placeholder}
            """, (image_id,))
            row = cursor.fetchone()
            if not row:
                return None

            if self.db_type == "mysql" and isinstance(row, dict):
                return {
                    "id": row["id"],
                    "session_id": row["session_id"],
                    "sha256": row["sha256"],
                    "mime_type": row["mime_type"],
                    "data_base64": row["data_base64"],
                    "size_bytes": row["size_bytes"],
                    "source_url": row["source_url"],
                    "summary": row["summary"],
                    "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
                    "created_at": row["created_at"],
                    "last_used_at": row["last_used_at"],
                }

            return {
                "id": row[0],
                "session_id": row[1],
                "sha256": row[2],
                "mime_type": row[3],
                "data_base64": row[4],
                "size_bytes": row[5],
                "source_url": row[6],
                "summary": row[7],
                "metadata": json.loads(row[8]) if row[8] else {},
                "created_at": row[9],
                "last_used_at": row[10],
            }
    
    # ==================== 长期记忆管理 ====================
    
    def add_memory(
        self,
        memory_id: str,
        content: str,
        memory_type: str,
        importance: float = 0.5,
        metadata: Optional[Dict] = None,
        session_id: Optional[str] = None
    ) -> bool:
        """添加长期记忆"""
        now = datetime.now().isoformat()
        placeholder = self._placeholder
        with self.get_cursor() as cursor:
            cursor.execute(f"""
                INSERT INTO long_term_memories (id, content, type, importance, created_at, accessed_at, metadata, session_id)
                VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})
            """, (memory_id, content, memory_type, importance, now, now, json.dumps(metadata or {}), session_id))
        return True
    
    def get_memories(
        self,
        session_id: Optional[str] = None,
        memory_type: Optional[str] = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """获取记忆列表"""
        placeholder = self._placeholder
        conditions = []
        params = []
        
        if session_id:
            conditions.append(f"session_id = {placeholder}")
            params.append(session_id)
        if memory_type:
            conditions.append(f"type = {placeholder}")
            params.append(memory_type)
        
        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
        
        with self.get_cursor() as cursor:
            cursor.execute(f"""
                SELECT id, content, type, importance, created_at, accessed_at, metadata, session_id
                FROM long_term_memories
                {where_clause}
                ORDER BY importance DESC, accessed_at DESC
                LIMIT {placeholder}
            """, params + [limit])
            
            memories = []
            for row in cursor.fetchall():
                if self.db_type == "mysql" and isinstance(row, dict):
                    memories.append({
                        "id": row["id"],
                        "content": row["content"],
                        "type": row["type"],
                        "importance": row["importance"],
                        "created_at": row["created_at"],
                        "accessed_at": row["accessed_at"],
                        "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
                        "session_id": row["session_id"]
                    })
                else:
                    memories.append({
                        "id": row[0],
                        "content": row[1],
                        "type": row[2],
                        "importance": row[3],
                        "created_at": row[4],
                        "accessed_at": row[5],
                        "metadata": json.loads(row[6]) if row[6] else {},
                        "session_id": row[7]
                    })
            return memories
    
    def delete_memory(self, memory_id: str) -> bool:
        """删除记忆"""
        placeholder = self._placeholder
        with self.get_cursor() as cursor:
            cursor.execute(f"DELETE FROM long_term_memories WHERE id = {placeholder}", (memory_id,))
        return True
    
    def clear_memories(self, session_id: Optional[str] = None) -> bool:
        """清空记忆"""
        placeholder = self._placeholder
        with self.get_cursor() as cursor:
            if session_id:
                cursor.execute(f"DELETE FROM long_term_memories WHERE session_id = {placeholder}", (session_id,))
            else:
                cursor.execute("DELETE FROM long_term_memories")
        return True
    
    # ==================== 动作历史管理 ====================
    
    def add_action(
        self,
        session_id: str,
        action_type: str,
        action_data: Dict[str, Any]
    ) -> bool:
        """添加动作记录"""
        now = datetime.now().isoformat()
        placeholder = self._placeholder
        with self.get_cursor() as cursor:
            cursor.execute(f"""
                INSERT INTO action_history (session_id, action_type, action_data, created_at)
                VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder})
            """, (session_id, action_type, json.dumps(action_data), now))
        return True
    
    def get_actions(self, session_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        """获取动作历史"""
        placeholder = self._placeholder
        with self.get_cursor() as cursor:
            cursor.execute(f"""
                SELECT action_type, action_data, created_at
                FROM action_history
                WHERE session_id = {placeholder}
                ORDER BY created_at DESC
                LIMIT {placeholder}
            """, (session_id, limit))
            
            actions = []
            for row in cursor.fetchall():
                if self.db_type == "mysql" and isinstance(row, dict):
                    actions.append({
                        "action_type": row["action_type"],
                        "action_data": json.loads(row["action_data"]) if row["action_data"] else {},
                        "created_at": row["created_at"]
                    })
                else:
                    actions.append({
                        "action_type": row[0],
                        "action_data": json.loads(row[1]) if row[1] else {},
                        "created_at": row[2]
                    })
            return actions
    
    def clear_actions(self, session_id: str) -> bool:
        """清空动作历史"""
        placeholder = self._placeholder
        with self.get_cursor() as cursor:
            cursor.execute(f"DELETE FROM action_history WHERE session_id = {placeholder}", (session_id,))
        return True
    
    # ==================== 工具方法 ====================
    
    def backup(self, backup_path: str) -> bool:
        """备份数据库（仅 SQLite 支持）"""
        if self.db_type != "sqlite":
            return False
        
        import shutil
        shutil.copy2(self.db_path, backup_path)
        return True
    
    def get_stats(self) -> Dict[str, Any]:
        """获取数据库统计信息"""
        with self.get_cursor() as cursor:
            cursor.execute("SELECT COUNT(*) as count FROM sessions")
            row = cursor.fetchone()
            session_count = row.get("count", 0) if isinstance(row, dict) else row[0]
            
            cursor.execute("SELECT COUNT(*) as count FROM conversation_history")
            row = cursor.fetchone()
            message_count = row.get("count", 0) if isinstance(row, dict) else row[0]
            
            cursor.execute("SELECT COUNT(*) as count FROM long_term_memories")
            row = cursor.fetchone()
            memory_count = row.get("count", 0) if isinstance(row, dict) else row[0]

            cursor.execute("SELECT COUNT(*) as count FROM image_assets")
            row = cursor.fetchone()
            image_count = row.get("count", 0) if isinstance(row, dict) else row[0]
            
            return {
                "db_type": self.db_type,
                "db_path": self.db_path if self.db_type == "sqlite" else f"{self.host}:{self.port}/{self.database}",
                "session_count": session_count,
                "message_count": message_count,
                "memory_count": memory_count,
                "image_count": image_count
            }


# 全局数据库实例（延迟初始化）
_db_manager: Optional[DatabaseManager] = None


def init_database(config: Dict[str, Any]) -> DatabaseManager:
    """初始化数据库管理器"""
    global _db_manager
    _db_manager = DatabaseManager(
        db_type=config.get("type", "sqlite"),
        db_path=config.get("sqlite_path", "data/agent.db"),
        host=config.get("mysql_host", "localhost"),
        port=config.get("mysql_port", 3306),
        user=config.get("mysql_user", "root"),
        password=config.get("mysql_password", ""),
        database=config.get("mysql_database", "agent_db")
    )
    return _db_manager


def get_database() -> Optional[DatabaseManager]:
    """获取数据库管理器实例"""
    return _db_manager
