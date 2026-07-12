# Stage 1: build the React front
FROM node:22-alpine AS web
WORKDIR /web
COPY web/package*.json ./
RUN npm ci --no-fund --no-audit
COPY web/ .
RUN npm run build

# Stage 2: python runtime with the database baked at build time
FROM python:3.12-slim
RUN useradd -m -u 1000 appuser
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ app/
# generate + bake + selfcheck: a red assertion fails the image build
RUN python -m app.build_db
COPY --from=web /web/dist web/dist
USER appuser
ENV PORT=7860
EXPOSE 7860
CMD ["sh", "-c", "uvicorn app.api:app --host 0.0.0.0 --port ${PORT}"]
