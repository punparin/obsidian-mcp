FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY obsidian_mcp/ obsidian_mcp/
COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

ENV OBSIDIAN_VAULT_PATH=/vault

ENTRYPOINT ["python", "-m", "obsidian_mcp"]
