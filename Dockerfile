FROM python:3.11-slim
WORKDIR /app

# Install system dependencies and Linux version of sing-box and xray
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    tar \
    unzip \
    && curl -Lo sing-box.tar.gz https://github.com/SagerNet/sing-box/releases/download/v1.9.3/sing-box-1.9.3-linux-amd64.tar.gz \
    && tar -xzf sing-box.tar.gz --strip-components=1 -C /usr/local/bin/ sing-box-1.9.3-linux-amd64/sing-box \
    && rm -rf sing-box.tar.gz \
    && curl -Lo xray.zip https://github.com/XTLS/Xray-core/releases/download/v26.3.27/Xray-linux-64.zip \
    && unzip xray.zip xray -d /usr/local/bin/ \
    && chmod +x /usr/local/bin/xray \
    && rm -rf xray.zip \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy everything including local prebuilt frontend/dist
COPY . .

# Set environment variables for docker setup
ENV SING_BOX_PATH=sing-box
ENV XRAY_PATH=xray
ENV CACHE_DB_PATH=/app/data/probe_cache.sqlite3
ENV API_DB_PATH=/app/data/api.sqlite3
ENV RUNTIME_SETTINGS_PATH=/app/data/runtime_settings.json

# Expose FastAPI server port
EXPOSE 8000

# Start application
CMD ["uvicorn", "api_server:app", "--host", "0.0.0.0", "--port", "8000"]
