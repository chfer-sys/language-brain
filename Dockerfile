# Production image for language-brain.
#
# Build:
#     docker build -f Dockerfile -t language-brain-prod .
#
# Run:
#     docker run --rm -p 8000:8000 -v $(pwd)/vault:/app/vault \
#         -e LANGUAGE_BRAIN_VAULT=/app/vault language-brain-prod

FROM python:3.12-slim

# System deps that some Python wheels expect.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy pyproject.toml first, then app source. The single-layer install
# leverages Docker cache for dependencies.
COPY pyproject.toml ./
COPY api ./api
COPY scripts ./scripts

# Install CPU-only torch first (avoids ~5GB of nvidia/CUDA packages
# that a CPU-only server doesn't need), then the rest of the deps.
# ponytail: ceiling — if we ever run on a GPU host, drop the --index-url
# and let pip pull the default CUDA-enabled torch.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir -e .

# HF mirror for sentence-transformers model downloads.
ENV HF_ENDPOINT=https://hf-mirror.com
ENV HF_HOME=/root/.cache/huggingface

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]