FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends build-essential libsndfile1 && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY . .
# Smart Turn runs on the CPU. The default torch wheel drags 5 GB of CUDA into the image
# (QA gate C); the CPU wheels satisfy pipecat's pin, so the main install leaves them alone.
RUN uv pip install --system --no-cache "torch>=2.5,<3" "torchaudio>=2.5,<3" --index-url https://download.pytorch.org/whl/cpu
RUN uv pip install --system --no-cache .
# The deployed revision, reported by /healthz so the portal's health page can name it.
ARG GIT_COMMIT=""
ENV GIT_COMMIT=$GIT_COMMIT
EXPOSE 8000
CMD ["spatalk", "serve", "--host", "0.0.0.0", "--port", "8000"]
