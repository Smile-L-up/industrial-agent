"""
配置文件
存储 API 密钥和系统配置
"""

import os
import json
import logging
from dotenv import load_dotenv

logger = logging.getLogger("industrial_agent.config")

# 加载环境变量
load_dotenv()

# LLM 配置
# 使用 OpenAI 兼容方式调用 Qwen 模型
# Qwen 通过 DashScope 提供的 OpenAI 兼容接口：https://dashscope.aliyuncs.com/compatible-mode/v1
# 注意：现在不再区分文本模型和视觉模型，统一使用一个模型配置
# 当传入图片时，支持视觉的模型（如 qwen-vl 系列）会自动处理图片
# 不支持视觉的模型会返回无法读取图片的提示
LLM_CONFIG = {
    "provider": os.getenv("LLM_PROVIDER", "openai"),  # LLM 提供商
    "model": os.getenv("LLM_MODEL", "qwen3.5-plus"),  # 模型名称
    "api_key": os.getenv("DASHSCOPE_API_KEY"),  # API 密钥 - 从环境变量读取，不再提供默认值
    "base_url": os.getenv("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),  # API 基础 URL
    
    # 统一 System Prompt 配置
    # 用于控制模型的回答风格和语言
    # 可以通过环境变量 LLM_SYSTEM_PROMPT 覆盖，或者设置为空字符串禁用
    "system_prompt": os.getenv("LLM_SYSTEM_PROMPT", """你是一个简洁高效的智能助手。

【回答规范】
1. 请始终使用中文进行思考和回答
2. 思考过程请简洁明了，直接聚焦关键问题，不要过于冗长
3. 回答时条理清晰，使用简洁的语言
4. 避免中英文混杂，除非是专有名词或技术术语
5. 直接给出答案，不需要过多的解释和说明"""),
}

# 多模型注册表
# 从环境变量 LLM_MODELS 读取 JSON，key 为模型名，value 包含 api_key 和 base_url
# 示例：{"qwen3.5-plus":{"api_key":"sk-xxx","base_url":"https://..."},"qwen-max":{"api_key":"sk-yyy","base_url":"https://..."}}
_llm_models_raw = os.getenv("LLM_MODELS", "")
try:
    LLM_MODELS: dict = json.loads(_llm_models_raw) if _llm_models_raw else {}
except json.JSONDecodeError:
    logger.warning("LLM_MODELS 环境变量不是合法 JSON，已忽略：%s", _llm_models_raw[:100])
    LLM_MODELS = {}

# 记忆系统配置
MEMORY_CONFIG = {
    "short_term_capacity": 10,
    "long_term_storage": None,
}

# 代理配置
AGENT_CONFIG = {
    "max_iterations": 10,
}

# 数据库配置
# 支持 SQLite 和 MySQL，通过 DB_TYPE 切换
# SQLite: 适合单机部署，无需额外配置
# MySQL: 适合多实例、高可用场景
DATABASE_CONFIG = {
    # 数据库类型：sqlite 或 mysql
    "type": os.getenv("DB_TYPE", "sqlite"),  # 默认改为 sqlite，更安全
    
    # SQLite 配置（当 type=sqlite 时使用）
    "sqlite_path": os.getenv("SQLITE_PATH", "data/agent.db"),
    
    # MySQL 配置（当 type=mysql 时使用）
    "mysql_host": os.getenv("MYSQL_HOST", "localhost"),
    "mysql_port": int(os.getenv("MYSQL_PORT", "3306")),
    "mysql_user": os.getenv("MYSQL_USER", "root"),
    "mysql_password": os.getenv("MYSQL_PASSWORD"),  # 从环境变量读取，不再提供默认值
    "mysql_database": os.getenv("MYSQL_DATABASE", "agent_db"),
}

# 会话配置
SESSION_CONFIG = {
    "max_history": 10,        # 最大对话历史条数
    "ttl_minutes": 30,        # 会话超时时间（分钟）
    "max_sessions": 100,      # 最大并发会话数
}


# ==================== 启动验证 ====================
def validate_config():
    """验证关键配置是否存在，缺失时打印警告"""
    warnings = []
    if not LLM_CONFIG.get("api_key"):
        warnings.append("DASHSCOPE_API_KEY 未设置！LLM 调用将失败。请在 .env 文件中配置。")
    if DATABASE_CONFIG["type"] == "mysql" and not DATABASE_CONFIG.get("mysql_password"):
        warnings.append("MYSQL_PASSWORD 未设置！MySQL 连接将失败。请在 .env 文件中配置。")
    for w in warnings:
        logger.warning(w)
    return warnings


validate_config()
