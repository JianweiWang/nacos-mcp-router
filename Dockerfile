FROM python:3.12-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    build-essential \
    curl nodejs npm \
    && rm -rf /var/lib/apt/lists/*
# 复制项目文件
COPY pyproject.toml .
COPY README.md .
COPY src/ src/

# 安装 Python 依赖
RUN pip install --no-cache-dir .

# 启动服务
CMD ["python", "-m", "nacos_mcp_router"] 