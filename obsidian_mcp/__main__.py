"""Allow running as `python -m obsidian_mcp`."""

import os

# Don't phone home to PyPI for FastMCP update checks. Must be set before
# fastmcp is imported (its settings are read at import time).
os.environ.setdefault("FASTMCP_CHECK_FOR_UPDATES", "off")

from .server import mcp  # noqa: E402

mcp.run(show_banner=False)
