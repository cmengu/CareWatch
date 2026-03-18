# CareWatch pipeline image — Python 3.12
FROM python:3.12-slim

WORKDIR /app

# Install Python dependencies first (layer cache optimisation)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ app/
COPY src/ src/
COPY run_pipeline.py .

COPY data/ data/
# .env injected via environment in docker-compose.yml — never copied into image
# model/*.pt not needed — pipeline reads from DB, not camera

RUN useradd --create-home carewatch
USER carewatch

CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000"]
