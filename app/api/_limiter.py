"""
Module-level slowapi Limiter and per-endpoint limit config.

Kept in a separate submodule to avoid circular imports:
  app/api/__init__.py  →  .routers.*  →  app/api/_limiter  (no further deps)

`create_app()` in __init__.py calls `configure_limiter()` to set runtime values.
Router decorators import `limiter` and `_endpoint_limits` from here.
"""
from typing import Dict, Optional

from limits import RateLimitItem, parse as parse_rate_limit
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

# Parsed global default limit, applied by check_global_default_limit(). None = no
# global limit (disabled). Set at runtime by configure_limiter().
_default_limit_item: Optional[RateLimitItem] = None


def configure_limiter(rl_config: dict) -> None:
    """Apply runtime rate-limit config to the module-level limiter and limits dict."""
    global _default_limit_item

    enabled = rl_config.get("enabled", False)
    default_limit = rl_config.get("default", "60/minute")

    limiter.enabled = enabled
    # _default_limits must be a list of LimitGroup objects (not raw strings)
    limiter._default_limits = [
        LimitGroup(default_limit, limiter._key_func, None, False, None, None, None, 1, False)
    ]

    # Parse the global default into a limits.RateLimitItem for explicit enforcement
    # (see check_global_default_limit — slowapi's own default-limit middleware
    # no-ops on FastAPI include_router routes under Starlette 1.x).
    try:
        _default_limit_item = parse_rate_limit(default_limit) if enabled else None
    except ValueError:
        logger_msg = "Invalid api.rate_limit.default %r — global default limit disabled"
        import logging
        logging.getLogger(__name__).warning(logger_msg, default_limit)
        _default_limit_item = None

    for key in ("trigger", "initial_load_start", "push_regenerate", "push_reset", "invoice_download"):
        if key in rl_config:
            _endpoint_limits[key] = rl_config[key]


def check_global_default_limit(request) -> bool:
    """Return True if the request is within the global default limit (or none set).

    Enforces the configured global API default rate limit independently of
    slowapi's route-handler discovery. slowapi's SlowAPIMiddleware applies default
    limits only after locating the route's endpoint; under Starlette 1.x / FastAPI
    `include_router`, the route is wrapped in a `_IncludedRouter` with no
    `endpoint`, so slowapi treats every included-router route as exempt and the
    global default silently never applies. We check it explicitly here.

    Per-endpoint `@limiter.limit(...)` decorators are unaffected and keep working.
    """
    item = _default_limit_item
    if item is None or not limiter.enabled:
        return True
    key = get_remote_address(request)
    # Scope by path + client key (mirrors slowapi's per-endpoint default scoping).
    return limiter.limiter.hit(item, request.url.path, key)
