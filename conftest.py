"""Root conftest — mock unavailable optional dependencies."""
import sys
from unittest.mock import MagicMock

# Mock fastmcp before any benchmark_platform imports
_fastmcp = MagicMock()
_fastmcp.FastMCP.return_value.http_app.return_value.lifespan = MagicMock()
sys.modules.setdefault("fastmcp", _fastmcp)
sys.modules.setdefault("fastmcp.server", MagicMock())
sys.modules.setdefault("fastmcp.server.dependencies", MagicMock())
