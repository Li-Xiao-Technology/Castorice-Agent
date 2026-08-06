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

# 先复制依赖定义和完整包结构，利用 Docker 层缓存
COPY pyproject.toml README.md ./
COPY castorice ./castorice

RUN pip install --no-cache-dir .

# 再复制剩余文件（如 .dockerignore 排除的文件，不触发重新安装依赖）
COPY . .

EXPOSE 5477

CMD ["python", "-m", "castorice.main", "--mode", "http"]
