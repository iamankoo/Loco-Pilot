from __future__ import annotations

import socket

from backend.app.services import runtime_service


def test_find_free_port_avoids_the_backend_own_port(monkeypatch) -> None:
    """The exact bug this closes: a generated site's runtime must never be
    published on the LocoPilot backend's own port — "http://localhost:8000"
    must never resolve to the FastAPI backend instead of a generated site."""
    from backend.app.core.config import get_settings

    get_settings.cache_clear()
    backend_port = get_settings().api_port

    port = runtime_service._find_free_port()
    assert port != backend_port


def test_find_free_port_avoids_an_explicitly_given_port() -> None:
    """A real, deterministic collision (not merely astronomically unlikely
    ephemeral-range luck) is still closed by the explicit `avoid` set —
    e.g. a port a sibling runtime is already using."""
    # Reserve a real port first, so we know a concrete, currently-taken
    # port number to explicitly avoid.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reserved:
        reserved.bind(("127.0.0.1", 0))
        reserved_port = reserved.getsockname()[1]

        port = runtime_service._find_free_port(avoid={reserved_port})
        assert port != reserved_port


def test_find_free_port_retries_past_a_forced_collision(monkeypatch) -> None:
    """Directly exercises the retry loop: the first attempt is forced to
    collide with `avoid`, so a correct implementation must try again rather
    than returning the colliding port."""
    calls = {"n": 0}
    real_socket_cls = socket.socket

    class _ScriptedSocket:
        def __init__(self, *args, **kwargs):
            self._real = real_socket_cls(*args, **kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self._real.close()

        def bind(self, addr):
            self._real.bind(addr)

        def getsockname(self):
            calls["n"] += 1
            host, real_port = self._real.getsockname()
            # First call reports a scripted "colliding" port; subsequent
            # calls report the real, actually-bound port.
            return (host, 9999) if calls["n"] == 1 else (host, real_port)

    monkeypatch.setattr(socket, "socket", _ScriptedSocket)
    port = runtime_service._find_free_port(avoid={9999})
    assert port != 9999
    assert calls["n"] >= 2


async def test_get_status_reports_no_runtime_for_unknown_execution() -> None:
    status = await runtime_service.get_status("does-not-exist")
    assert status == {"status": "no_runtime", "url": None, "detail": None}


async def test_stop_runtime_returns_false_for_unknown_execution() -> None:
    assert await runtime_service.stop_runtime("does-not-exist") is False
