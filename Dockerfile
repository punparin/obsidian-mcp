FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY obsidian_mcp/ obsidian_mcp/
COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

# fastembed is intentionally NOT installed in the image — it would add
# ~130MB of Python deps and trigger an ONNX model download on first run.
# The container expects a remote Ollama server; users provide:
#   OBSIDIAN_EMBEDDER_MODEL  (e.g. qwen3-embedding:8b, bge-m3, ...)
#   OLLAMA_URL               (defaults to http://localhost:11434)
# Set OBSIDIAN_EMBEDDER=fastembed and rebuild from the [fastembed] extra
# if you want the in-process default.
ENV OBSIDIAN_VAULT_PATH=/vault
ENV OBSIDIAN_EMBEDDER=ollama

ENTRYPOINT ["python", "-m", "obsidian_mcp"]
