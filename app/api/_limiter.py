"""
Module-level slowapi Limiter and per-endpoint limit config.

Kept in a separate submodule to avoid circular imports:
  app/api/__init__.py  →  .routers.*  →  app/api/_limiter  (no further deps)

`create_app()` in __init__.py calls `configure_limiter()` to set runtime values.
Router decorators import `limiter` and `_endpoint_limits` from here.
"""
from typing import Dict

from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.wrappers import LimitGroup

# Module-level limiter — disabled by default; enabled by create_app().
limiter = Limiter(key_func=get_remote_address, enabled=False)

# Per-endpoint limit strings — defaults match config_manager defaults.
# Populated at runtime by create_app() via configure_limiter().
_endpoint_limits: Dict[str, str] = {
    "trigger": "2/minute",
    "initial_load_start": "1/hour",
    "push_regenerate": "5/hour",
    "push_reset": "1/hour",
    "invoice_download": "30/minute",
}


def configure_limiter(rl_config: dict) -> None:
    """Apply runtime rate-limit config to the module-level limiter and limits dict."""
    enabled = rl_config.get("enabled", False)
    default_limit = rl_config.get("default", "60/minute")

    limiter.enabled = enabled
    # _default_limits must be a list of LimitGroup objects (not raw strings)
    limiter._default_limits = [
        LimitGroup(default_limit, limiter._key_func, None, False, None, None, None, 1, False)
    ]

    for key in ("trigger", "initial_load_start", "push_regenerate", "push_reset", "invoice_download"):
        if key in rl_config:
            _endpoint_limits[key] = rl_config[key]
