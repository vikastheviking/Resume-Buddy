# Production multi-runtime container (Node.js 18 + Python 3.11)
FROM node:18-bullseye-slim

# Python 3, pip, and build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Alias python -> python3
RUN ln -s /usr/bin/python3 /usr/bin/python

WORKDIR /app

# Python dependencies
COPY requirements.txt ./
RUN pip3 install --no-cache-dir -r requirements.txt

# Node.js dependencies
COPY package.json package-lock.json* ./
RUN npm ci --omit=dev || npm install --omit=dev

# Application source
COPY engine/ ./engine/
COPY server/ ./server/
COPY public/ ./public/

ENV PORT=3000
ENV PYTHON_PORT=5001
ENV NODE_ENV=production
# `engine.*` imports resolve from the app root; unbuffered so Python logs
# stream through the Node parent process instead of sitting in a buffer.
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV RESUME_BUDDY_DATA_DIR=/app/data

EXPOSE 3000

CMD ["node", "server/index.js"]
