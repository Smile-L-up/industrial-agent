# 数据库配置说明

本文档说明如何配置和使用智能体系统的数据库功能。

## 概述

系统支持两种数据库：

| 数据库 | 适用场景 | 配置难度 | 性能 |
|--------|----------|----------|------|
| **SQLite** | 单机部署、开发测试、小规模应用 | 简单（无需额外配置） | 适合低并发 |
| **MySQL** | 多实例部署、生产环境、高并发 | 需要 MySQL 服务器 | 适合高并发 |

## 快速开始

### 使用 SQLite（默认）

1. 无需额外配置，系统会自动创建 `data/agent.db` 文件

2. 确保 `.env` 文件中配置：
   ```bash
   DB_TYPE=sqlite
   SQLITE_PATH=data/agent.db
   ```

3. 启动应用即可自动使用

### 使用 MySQL

1. 安装 MySQL 服务器（版本 5.7+ 或 8.0+）

2. 创建数据库：
   ```sql
   CREATE DATABASE agent_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
   ```

3. 配置 `.env` 文件：
   ```bash
   DB_TYPE=mysql
   MYSQL_HOST=127.0.0.1
   MYSQL_PORT=3306
   MYSQL_USER=root
   MYSQL_PASSWORD=your_password
   MYSQL_DATABASE=agent_db
   ```

4. 安装 MySQL 驱动：
   ```bash
   pip install pymysql
   ```

5. 启动应用，系统会自动创建所需表结构

## 环境变量配置

| 变量名 | 说明 | 默认值 | 示例 |
|--------|------|--------|------|
| `DB_TYPE` | 数据库类型 | `sqlite` | `sqlite` 或 `mysql` |
| `SQLITE_PATH` | SQLite 数据库文件路径 | `data/agent.db` | `/var/data/agent.db` |
| `MYSQL_HOST` | MySQL 主机地址 | `localhost` | `192.168.1.100` |
| `MYSQL_PORT` | MySQL 端口 | `3306` | `3306` |
| `MYSQL_USER` | MySQL 用户名 | `root` | `agent_user` |
| `MYSQL_PASSWORD` | MySQL 密码 | 空 | `secure_password` |
| `MYSQL_DATABASE` | MySQL 数据库名 | `agent_db` | `agent_prod` |

## 数据库表结构

### sessions - 会话表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | TEXT/VARCHAR(64) | 会话 ID（主键） |
| created_at | DATETIME | 创建时间 |
| updated_at | DATETIME | 更新时间 |
| last_used_at | DATETIME | 最后使用时间 |
| metadata | TEXT | 元数据（JSON 格式） |

### conversation_history - 对话历史表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER/BIGINT | 自增 ID（主键） |
| session_id | TEXT/VARCHAR(64) | 会话 ID（外键） |
| role | TEXT/VARCHAR(16) | 角色（user/assistant） |
| content | TEXT/LONGTEXT | 消息内容 |
| created_at | DATETIME | 创建时间 |
| message_index | INTEGER | 消息索引 |

### long_term_memories - 长期记忆表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | TEXT/VARCHAR(64) | 记忆 ID（主键） |
| content | TEXT/LONGTEXT | 记忆内容 |
| type | TEXT/VARCHAR(32) | 记忆类型 |
| importance | REAL/FLOAT | 重要程度（0-1） |
| created_at | DATETIME | 创建时间 |
| accessed_at | DATETIME | 最后访问时间 |
| metadata | TEXT | 元数据（JSON 格式） |
| session_id | TEXT/VARCHAR(64) | 关联会话 ID |

### action_history - 动作历史表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER/BIGINT | 自增 ID（主键） |
| session_id | TEXT/VARCHAR(64) | 会话 ID（外键） |
| action_type | TEXT/VARCHAR(64) | 动作类型 |
| action_data | TEXT/LONGTEXT | 动作数据（JSON 格式） |
| created_at | DATETIME | 创建时间 |

## API 接口

### 获取数据库统计信息

```bash
GET /api/db/stats
```

响应示例：
```json
{
  "db_type": "sqlite",
  "db_path": "data/agent.db",
  "session_count": 5,
  "message_count": 42,
  "memory_count": 0
}
```

### 会话管理接口

```bash
# 创建新会话
POST /api/session/create

# 获取会话信息
GET /api/session/{session_id}

# 删除会话
DELETE /api/session/{session_id}

# 清空会话历史
POST /api/session/{session_id}/clear
```

## 数据备份

### SQLite 备份

```bash
# 复制数据库文件即可
cp data/agent.db data/agent_backup.db

# 或使用 Python 脚本
python -c "from core.database import get_database; db = get_database(); db.backup('backup.db')"
```

### MySQL 备份

```bash
# 使用 mysqldump
mysqldump -u root -p agent_db > agent_backup.sql

# 恢复
mysql -u root -p agent_db < agent_backup.sql
```

## 迁移指南

### 从 SQLite 迁移到 MySQL

1. 导出 SQLite 数据：
   ```python
   import sqlite3
   import json
   
   # 读取 SQLite
   conn = sqlite3.connect('data/agent.db')
   cursor = conn.cursor()
   
   # 导出会话
   cursor.execute("SELECT * FROM sessions")
   sessions = cursor.fetchall()
   
   # 导出对话历史
   cursor.execute("SELECT * FROM conversation_history")
   history = cursor.fetchall()
   
   conn.close()
   
   # 保存为 JSON
   with open('export.json', 'w') as f:
       json.dump({'sessions': sessions, 'history': history}, f)
   ```

2. 导入到 MySQL（需要编写相应导入脚本）

## 性能优化建议

### SQLite 优化

1. 使用 WAL 模式：
   ```sql
   PRAGMA journal_mode = WAL;
   ```

2. 定期执行 VACUUM：
   ```sql
   VACUUM;
   ```

### MySQL 优化

1. 调整 innodb_buffer_pool_size
2. 配置合适的连接数
3. 定期清理过期数据

## 故障排查

### 常见问题

1. **SQLite 锁定错误**
   - 确保没有其他进程占用数据库文件
   - 检查文件权限

2. **MySQL 连接失败**
   - 检查 MySQL 服务是否运行
   - 验证用户名密码是否正确
   - 确认防火墙允许连接

3. **表不存在错误**
   - 系统启动时会自动创建表
   - 检查数据库用户是否有创建表权限

## 配置示例

### 开发环境（SQLite）

```bash
DB_TYPE=sqlite
SQLITE_PATH=data/dev.db
```

### 生产环境（MySQL）

```bash
DB_TYPE=mysql
MYSQL_HOST=192.168.1.100
MYSQL_PORT=3306
MYSQL_USER=agent_prod
MYSQL_PASSWORD=secure_password_123
MYSQL_DATABASE=agent_production
```

### Docker 环境

```yaml
# docker-compose.yml
services:
  app:
    environment:
      - DB_TYPE=mysql
      - MYSQL_HOST=mysql
      - MYSQL_PORT=3306
      - MYSQL_USER=agent
      - MYSQL_PASSWORD=agent_password
      - MYSQL_DATABASE=agent_db
  
  mysql:
    image: mysql:8.0
    environment:
      - MYSQL_ROOT_PASSWORD=root_password
      - MYSQL_DATABASE=agent_db
      - MYSQL_USER=agent
      - MYSQL_PASSWORD=agent_password
    volumes:
      - mysql_data:/var/lib/mysql

volumes:
  mysql_data: