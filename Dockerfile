FROM python:3.11-slim
WORKDIR /app

# Install system dependencies and Linux version of sing-box and xray
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    tar \
    traceroute \
    unzip \
    && curl -fLo sing-box.tar.gz https://github.com/SagerNet/sing-box/releases/download/v1.14.3/sing-box-1.14.3-linux-amd64.tar.gz \
    && tar -xzf sing-box.tar.gz --strip-components=1 -C /usr/local/bin/ sing-box-1.14.3-linux-amd64/sing-box \
    && rm -rf sing-box.tar.gz \
    && curl -fLo xray.zip https://github.com/XTLS/Xray-core/releases/download/v26.3.27/Xray-linux-64.zip \
    && unzip xray.zip xray -d /usr/local/bin/ \
    && chmod +x /usr/local/bin/xray \
    && rm -rf xray.zip \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source and prebuilt frontend/dist; private data is excluded by .dockerignore
COPY . .

# Set environment variables for docker setup
ENV SING_BOX_PATH=sing-box
ENV XRAY_PATH=xray
ENV DATA_DIR=/app/data

# Expose FastAPI server port
EXPOSE 8000

HEALTHCHECK --interval=5s --timeout=5s --start-period=30s --retries=12 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/subscriptions', timeout=4).read()"

# Start application
CMD ["uvicorn", "api_server:app", "--host", "0.0.0.0", "--port", "8000"]
