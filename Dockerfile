FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV HF_ENDPOINT=https://hf-mirror.com

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libssl-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 复制全部源码（.dockerignore 已排除前端/数据/缓存/venv等）
COPY . .

# 安装核心依赖 + HTTP 服务器依赖（fastapi/uvicorn）
RUN pip install --no-cache-dir ".[http]"

EXPOSE 5477

CMD ["python", "-m", "castorice.main", "--mode", "http"]
