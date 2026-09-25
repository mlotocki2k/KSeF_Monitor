"""api.forwarded_allow_ips reaches uvicorn; unset keeps uvicorn's default."""

from unittest.mock import MagicMock, patch

from app.api.server import APIServer


def _config_kwargs(**server_kwargs):
    with patch("uvicorn.Config") as cfg, patch("uvicorn.Server") as srv, \
         patch("threading.Thread") as thread:
        srv.return_value = MagicMock()
        thread.return_value = MagicMock()
        APIServer(MagicMock(), **server_kwargs).start()
    return cfg.call_args.kwargs


def test_forwarded_allow_ips_passed_to_uvicorn():
    kwargs = _config_kwargs(forwarded_allow_ips="192.168.8.5")
    assert kwargs["forwarded_allow_ips"] == "192.168.8.5"


def test_default_leaves_uvicorn_default():
    assert "forwarded_allow_ips" not in _config_kwargs()
