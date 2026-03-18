# CareWatch pipeline image — Python 3.12, src + prompts only; data mounted at runtime
FROM python:3.12-slim

WORKDIR /app

# Install Python dependencies first (layer cache optimisation)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ app/
COPY src/ src/
COPY run_pipeline.py .

# Copy prompt templates (required by prompt_registry.py)
COPY data/prompts/ data/prompts/

# data/ mounted as volume at runtime — DB and ChromaDB persist across restarts
# .env injected via environment in docker-compose.yml — never copied into image
# model/*.pt not needed — pipeline reads from DB, not camera

RUN useradd --create-home carewatch
USER carewatch

CMD ["python", "run_pipeline.py", "--find-red"]
