# 智能体 Docker 部署指南（内网离线版）

本文档介绍如何使用 Docker 部署智能体系统，适用于**无网络内网环境**。

## 目录

- [部署架构](#部署架构)
- [前置要求](#前置要求)
- [部署流程概览](#部署流程概览)
- [步骤 1: 在外网机器准备](#步骤 1-在外网机器准备)
- [步骤 2: 传输到内网机器](#步骤 2-传输到内网机器)
- [步骤 3: 在内网机器部署](#步骤 3-在内网机器部署)
- [常见问题](#常见问题)

---

## 部署架构

```
┌─────────────────┐     ┌─────────────────┐
│   外网机器       │     │   内网机器       │
│  (有网络)       │     │  (无网络)        │
│                 │     │                  │
│ 1. 下载 Python 包  │ ──▶│ 2. 构建 Docker   │
│ 2. 拉取 Docker 镜像│     │    镜像          │
│ 3. 导出镜像      │     │ 3. 启动服务      │
└─────────────────┘     └─────────────────┘
```

---

## 前置要求

### 外网机器
- Python 3.11+
- Docker 20.10+
- Docker Compose 2.0+
- 网络连接

### 内网机器
- Docker 20.10+
- Docker Compose 2.0+
- 至少 10GB 可用磁盘空间

---

## 部署流程概览

| 步骤 | 操作 | 机器 |
|------|------|------|
| 1 | 下载 Python 依赖包 | 外网 |
| 2 | 拉取 Docker 基础镜像 | 外网 |
| 3 | 导出镜像和包 | 外网 |
| 4 | 传输到内网 | - |
| 5 | 导入并构建 | 内网 |
| 6 | 启动服务 | 内网 |

---

## 步骤 1: 在外网机器准备

### 1.1 下载 Python 依赖包

```bash
# 进入项目目录
cd industrial-agent

# 运行下载脚本
python download_packages.py
```

下载完成后会生成 `python-packages` 目录（约 2-3GB）。

### 1.2 拉取 Docker 基础镜像

```bash
# 拉取 Python 基础镜像
docker pull python:3.11-slim

# 导出镜像
docker save -o python-3.11-slim.tar python:3.11-slim
```

### 1.3 导出项目文件

```bash
# 打包项目文件（排除不必要的文件）
# 在 Linux/Mac 上:
tar -czf industrial-agent-src.tar.gz \
    --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='logs' \
    --exclude='data' \
    .

# 在 Windows 上，可以使用 7-Zip 或手动复制以下文件:
# - Dockerfile
# - docker-compose.intranet.yml
# - requirements.txt
# - .env.example
# - 所有源代码文件和目录
```

### 1.4 汇总传输文件

需要准备以下文件传输到内网：

```
python-3.11-slim.tar      # Docker 基础镜像 (~100MB)
python-packages/           # Python 依赖包 (约 2-3GB)
industrial-agent-src.tar.gz # 项目源代码
```

---

## 步骤 2: 传输到内网机器

使用 U 盘、移动硬盘或内网文件共享等方式，将上述文件复制到内网机器。

---

## 步骤 3: 在内网机器部署

### 3.1 导入 Docker 镜像

```bash
# 导入 Python 基础镜像
docker load -i python-3.11-slim.tar
```

### 3.2 准备项目文件

```bash
# 解压项目文件
tar -xzf industrial-agent-src.tar.gz -C /path/to/deploy/
cd /path/to/deploy/

# 复制 Python 包目录
cp -r /path/to/python-packages ./
```

### 3.3 配置环境变量

```bash
# 复制环境变量文件
cp .env.example .env

# 编辑 .env 文件，填入 API 密钥
# vi .env 或 notepad .env
```

### 3.4 构建并启动

```bash
# 构建 Docker 镜像
docker compose -f docker-compose.intranet.yml build

# 启动服务
docker compose -f docker-compose.intranet.yml up -d

# 查看状态
docker compose ps

# 查看日志
docker compose logs -f
```

### 3.5 验证部署

```bash
# 健康检查
curl http://localhost:18000/health

# 测试 API
curl http://localhost:18000/api
```

---

## 文件结构

部署时内网机器的文件结构应如下：

```
industrial-agent/
├── Dockerfile              # Docker 构建文件
├── docker-compose.intranet.yml  # Docker Compose 配置
├── requirements.txt        # Python 依赖
├── .env                    # 环境变量配置
├── python-packages/        # Python 离线包目录
│   ├── numpy-xxx.whl
│   ├── pydantic-xxx.whl
│   └── ...
├── agent/
├── core/
├── llm/
├── skills/
├── static/
├── logs/                   # 日志目录（运行时生成）
└── data/                   # 数据目录（运行时生成）
```

---

## 常见问题

### 1. Docker 镜像导入失败

**问题**: `docker load` 报错

**解决**:
- 确保镜像文件完整
- 检查 Docker 版本兼容性

### 2. Python 包安装失败

**问题**: 构建时 pip 安装失败

**解决**:
- 确保 `python-packages` 目录与 Dockerfile 在同一层级
- 检查 Dockerfile 中的 COPY 路径正确

### 3. 端口被占用

**问题**: 18000 端口已被使用

**解决**:
```yaml
# 修改 docker-compose.intranet.yml
ports:
  - "8000:18000"  # 改为其他端口
```

### 4. 容器启动后立即退出

**问题**: 容器无法正常运行

**解决**:
```bash
# 查看日志
docker compose logs industrial-agent

# 检查环境变量
docker compose config
```

### 5. 如何更新部署

**问题**: 需要更新代码

**解决**:
```bash
# 停止旧容器
docker compose down

# 重新构建
docker compose -f docker-compose.intranet.yml build --no-cache

# 启动新容器
docker compose -f docker-compose.intranet.yml up -d
```

---

## 快速参考

### 外网机器命令汇总

```bash
# 1. 下载 Python 包
python download_packages.py

# 2. 拉取并导出 Docker 镜像
docker pull python:3.11-slim
docker save -o python-3.11-slim.tar python:3.11-slim

# 3. 打包项目
tar -czf industrial-agent-src.tar.gz --exclude='.git' --exclude='__pycache__' --exclude='logs' --exclude='data' .
```

### 内网机器命令汇总

```bash
# 1. 导入 Docker 镜像
docker load -i python-3.11-slim.tar

# 2. 构建镜像
docker compose -f docker-compose.intranet.yml build

# 3. 启动服务
docker compose -f docker-compose.intranet.yml up -d

# 4. 查看状态
docker compose ps
docker compose logs -f
curl http://localhost:18000/health
```

---

## 服务地址

部署完成后，可通过以下地址访问服务：

- **API 地址**: http://内网机器 IP:18000
- **健康检查**: http://内网机器 IP:18000/health
- **前端页面**: http://内网机器 IP:18000/static/index.html
