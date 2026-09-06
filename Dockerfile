# Production Multi-Runtime Container (Node.js 18 + Python 3.11)
FROM node:18-bullseye-slim

# Install Python 3, pip, and build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Set alias python -> python3
RUN ln -s /usr/bin/python3 /usr/bin/python

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt starlette uvicorn python-multipart

# Install Node.js dependencies
COPY package.json package-lock.json* ./
RUN npm ci --omit=dev || npm install --omit=dev

# Copy application source code
COPY . .

# Expose standard production port
ENV PORT=3000
ENV PYTHON_PORT=5001
ENV NODE_ENV=production
EXPOSE 3000

# Start unified production server
CMD ["node", "server.js"]
