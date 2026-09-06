# ---------------------------------------------------------------------------
# Stage 1: build the React frontend.
#
# Vite and its plugins are devDependencies, so this stage installs everything and is
# then discarded — the runtime image never carries the build toolchain.
# ---------------------------------------------------------------------------
FROM node:18-bullseye-slim AS web

WORKDIR /build

COPY package.json package-lock.json* ./
RUN npm ci || npm install

COPY vite.config.mjs ./
COPY web/ ./web/
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2: production runtime (Node.js 18 + Python 3.11).
# ---------------------------------------------------------------------------
FROM node:18-bullseye-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN ln -s /usr/bin/python3 /usr/bin/python

WORKDIR /app

# Python dependencies
COPY requirements.txt ./
RUN pip3 install --no-cache-dir -r requirements.txt

# Node.js runtime dependencies only
COPY package.json package-lock.json* ./
RUN npm ci --omit=dev || npm install --omit=dev

# Application source
COPY engine/ ./engine/
COPY server/ ./server/

# Compiled frontend from stage 1
COPY --from=web /build/web/dist ./web/dist

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
