# ============ 后端 FastAPI + CrewAI 镜像 ============
# 构建上下文：backend/ 目录（docker-compose 里指定 context 为 backend）
# 部署目标：WSL2 (Ubuntu) + 原生 docker-ce，python 3.11
#
# 说明：
# 1. 本项目依赖（crewai/pymysql/cryptography/bcrypt 等）在 Linux + Py3.11 上
#    均有预编译的 manylinux wheel，pip 直接下 wheel，不会触发源码编译，
#    因此【不需要】安装 gcc/g++/build-essential 等编译工具链（可省 ~85MB 下载）。
# 2. apt / pip 均切换为国内镜像源，避免 deb.debian.org 直连极慢的问题。

# ---- 阶段 1：安装 Python 依赖（利用 layer 缓存，代码变更无需重装）----
FROM python:3.11-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 先只拷贝依赖清单，利用缓存；pip 走阿里云源
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
        -i https://mirrors.aliyun.com/pypi/simple/

# ---- 阶段 2：运行镜像（只带代码 + 依赖，瘦身）----
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Shanghai \
    PORT=8000

# apt 源切换到阿里云 Debian 镜像（python:3.11-slim 基于 Debian，默认 deb.debian.org 极慢）
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g; s|security.debian.org|mirrors.aliyun.com|g' \
        /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's|deb.debian.org|mirrors.aliyun.com|g; s|security.debian.org|mirrors.aliyun.com|g' \
        /etc/apt/sources.list 2>/dev/null || true

# 运行期仅需 libssl3（cryptography 运行依赖）与 tzdata；无需编译工具链
RUN apt-get update && apt-get install -y --no-install-recommends \
        libssl3 \
        tzdata \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 从 builder 拷贝已安装的 site-packages 与命令
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# 拷贝应用代码
COPY app ./app

# 非 root 运行
RUN useradd --create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# 单进程运行（项目自带 ProcessPoolExecutor 后台任务池，勿用多 worker，避免进程数翻倍）
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
