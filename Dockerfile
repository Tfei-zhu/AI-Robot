# syntax=docker/dockerfile:1
# 第 5 批：容器化部署。
# 基础镜像只装核心依赖（requirements.txt），不含 crewai/ragas/torch——
# 多 Agent 与重排为可选能力，需要时在 compose 中预装或挂载体积缓存。
#
# 构建加速说明：
#   - pip 默认走清华镜像源（国内快），可用 --build-arg PIP_INDEX_URL=... 覆盖
#   - --mount=type=cache 复用 pip 下载缓存：只改代码重建时秒级完成；
#     改了依赖也只下载新增包，不用每次全量重装
FROM python:3.11-slim

ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/root/.cache/huggingface \
    AIROBOT_RERANK_ENABLED=false

WORKDIR /app

# 依赖分层缓存：requirements.txt 不变时复用镜像层；pip 下载缓存跨构建复用
COPY requirements.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --index-url ${PIP_INDEX_URL} -r requirements.txt

COPY app ./app
COPY data ./data
COPY .env.example .env.example

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
