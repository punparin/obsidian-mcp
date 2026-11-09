FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install only the runtime package (no dev/test deps, no fastembed — it
# adds ~130MB and downloads a model on first run). Semantic search uses a
# remote Ollama / OpenAI-compatible server instead; users provide:
#   OBSIDIAN_EMBEDDER_MODEL  (e.g. qwen3-embedding:8b, bge-m3, ...)
#   OLLAMA_URL               (defaults to http://localhost:11434)
COPY pyproject.toml .
COPY obsidian_mcp/ obsidian_mcp/
RUN pip install --no-cache-dir . && rm -rf /app/obsidian_mcp

# Run as an unprivileged user. If your vault is owned by a different
# uid, pass `--user "$(id -u):$(id -g)"` to docker run.
RUN useradd --uid 1000 --no-create-home --shell /usr/sbin/nologin obsidian
USER 1000:1000

ENV OBSIDIAN_VAULT_PATH=/vault
ENV OBSIDIAN_EMBEDDER=ollama

ENTRYPOINT ["python", "-m", "obsidian_mcp"]
