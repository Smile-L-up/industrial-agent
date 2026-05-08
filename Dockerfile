# Industrial Agent Dockerfile
# 智能体项目 Docker 镜像（极简版）

# 使用稳定的 Python 基础镜像
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 设置环境变量
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

# 安装系统依赖（最小化）
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# 复制依赖文件
COPY requirements.txt .

# 安装 Python 依赖（使用精简安装）
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 复制项目文件（排除不必要的文件）
COPY agent/ ./agent/
COPY core/ ./core/
COPY llm/ ./llm/
COPY skills/ ./skills/
COPY prompts/ ./prompts/
COPY static/ ./static/
COPY api.py .
COPY config.py .
COPY main.py .

# 创建数据目录
RUN mkdir -p /app/data /app/logs

# 暴露端口
EXPOSE 18000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:18000/health || exit 1

# 启动命令
CMD ["python", "-m", "uvicorn", "api:app", "--host", "0.0.0.0", "--port", "18000"]
