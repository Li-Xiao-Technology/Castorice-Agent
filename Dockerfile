# Castorice Agent - Docker 部署
FROM python:3.11-slim

WORKDIR /app

# 复制依赖清单
COPY pyproject.toml ./
COPY castorice ./castorice
COPY castorice_config.yaml ./

# 安装依赖
RUN pip install --no-cache-dir -e ".[memory,ollama]"

# 复制配置模板
COPY .env.example .env.example

# 数据目录挂载点
VOLUME ["/app/castorice_data"]

# 启动命令（可通过 docker run --env-file .env 注入密钥）
CMD ["python", "-m", "castorice.main", "--mode", "interactive"]
