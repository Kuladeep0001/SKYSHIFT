# SkyShift: one container serves the website and the API.

# 1) build the React website
FROM node:20-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# 2) Python API that also serves the built site
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 SKYSHIFT_CACHE=/app/data/cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend backend
COPY scripts scripts
COPY --from=web /web/dist frontend/dist
# Hugging Face Spaces and Render both pass $PORT; default 7860 (HF Spaces).
ENV PORT=7860
EXPOSE 7860
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT}"]
