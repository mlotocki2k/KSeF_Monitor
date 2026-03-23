"""
API Server — runs uvicorn in a daemon thread.

Failure to start the API server logs a warning but does NOT
block the main monitor loop (graceful degradation).
"""

import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)


class APIServer:
    """Manages uvicorn server lifecycle in a daemon thread."""

    def __init__(
        self,
        app,
        host: str = "127.0.0.1",
        port: int = 8080,
    ):
        self.app = app
        self.host = host
        self.port = port
        self._server = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> bool:
        """Start the API server in a background daemon thread.

        Returns True if started successfully, False on failure.
        """
        try:
            import uvicorn

            config = uvicorn.Config(
                app=self.app,
                host=self.host,
                port=self.port,
                log_level="warning",
                access_log=False,
            )
            self._server = uvicorn.Server(config)

            self._thread = threading.Thread(
                target=self._server.run,
                name="api-server",
                daemon=True,
            )
            self._thread.start()

            logger.info("API server started on %s:%d", self.host, self.port)
            return True

        except ImportError:
            logger.warning("uvicorn not installed — API server disabled")
            return False
        except Exception as e:
            logger.warning("Failed to start API server: %s", str(e))
            return False

    def stop(self) -> None:
        """Signal the server to shut down gracefully."""
        if self._server:
            self._server.should_exit = True
            logger.info("API server shutdown requested")
