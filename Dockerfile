FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive \
    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    ffmpeg \
    wget \
    curl \
    ca-certificates \
    fonts-liberation \
    fonts-noto-cjk \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libexpat1 \
    libgbm1 \
    libglib2.0-0 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libxkbcommon0 \
    libxcb1 \
    libx11-6 \
    libx11-xcb1 \
    libxext6 \
    && rm -rf /var/lib/apt/lists/*

# Install cloudflared binary inside container for auto-tunneling
RUN curl -fsSL -o /usr/local/bin/cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
    && chmod +x /usr/local/bin/cloudflared

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN mkdir -p downloads thumbnails

COPY . .

EXPOSE 8080

CMD ["python", "bot.py"]
