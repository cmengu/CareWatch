# CareWatch pipeline image — Python 3.12
FROM python:3.12-slim

WORKDIR /app

# Install Python dependencies first (layer cache optimisation)
COPY requirements-api.txt .
RUN pip install --no-cache-dir -r requirements-api.txt

COPY app/ app/
COPY src/ src/
COPY run_pipeline.py .
COPY data/ data/
RUN python -m src.knowledge_base

EXPOSE 8000
RUN useradd --create-home carewatch && chown -R carewatch:carewatch /app
USER carewatch

CMD ["sh", "-c", "uvicorn app.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
