# 使用 Python 3.11 基础镜像
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 设置环境变量避免交互式安装
ENV DEBIAN_FRONTEND=noninteractive

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \
    wget \
    curl \
    gcc \
    g++ \
    libc6-dev \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# 复制requirements.txt
COPY requirements.txt .

# 安装 Python 依赖
# 在 CPU 环境中优先使用 PyTorch CPU 轮子，避免拉取不必要的 CUDA 依赖并降低超时概率。
RUN grep -v -E '^(torch|torchaudio)==.*' requirements.txt > requirements.docker.txt \
    && pip install --no-cache-dir --default-timeout=1000 \
       --index-url https://download.pytorch.org/whl/cpu \
       torch==2.8.0+cpu torchaudio==2.8.0+cpu \
    && pip install --no-cache-dir --default-timeout=1000 -r requirements.docker.txt

# 复制项目文件
COPY . .

# 创建必要的目录
RUN mkdir -p /app/models /app/uploads /app/temp /app/logs /app/data

# 设置环境变量
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# 暴露端口
EXPOSE 8767

# 启动命令
CMD ["python", "run_server.py"]
