# ============ 后端 FastAPI + CrewAI 镜像 ============
# 构建上下文：backend/ 目录（docker-compose 里指定 context 为 backend）
# 部署目标：WSL2 (Ubuntu) + 原生 docker-ce，python 3.11

# ---- 阶段 1：安装依赖（利用 docker layer 缓存，代码变更无需重装依赖）----
FROM python:3.11-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# crewai / pymysql / cryptography 等需要编译工具链
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        g++ \
        libffi-dev \
        libssl-dev \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先只拷贝依赖清单，利用缓存
# 使用阿里云 pip 镜像源，加速国内构建
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
        -i https://mirrors.aliyun.com/pypi/simple/

# ---- 阶段 2：运行镜像（只带代码 + 依赖，瘦身）----
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Shanghai \
    PORT=8000

# 运行期若用到编译产物（如 cryptography）需要 libssl，这里补上运行时库
RUN apt-get update && apt-get install -y --no-install-recommends \
        libssl3 \
        tzdata \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 从 builder 拷贝已安装的 site-packages
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
