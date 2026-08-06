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

# 先复制依赖定义文件，利用 Docker 层缓存
COPY pyproject.toml README.md ./
COPY castorice/__init__.py ./castorice/

RUN pip install --no-cache-dir -e .

# 再复制全部源码（代码改动不会触发重新安装依赖）
COPY . .

EXPOSE 5477

CMD ["python", "-m", "castorice.main", "--mode", "http"]
