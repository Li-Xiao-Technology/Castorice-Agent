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

COPY pyproject.toml .
RUN pip install --no-cache-dir -e . || pip install --no-cache-dir --no-deps -e .

COPY . .

RUN pip install --no-cache-dir -e .

EXPOSE 8000

CMD ["python", "-m", "castorice.main", "--mode", "http"]