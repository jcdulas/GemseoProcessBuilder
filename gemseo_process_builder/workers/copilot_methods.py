"""The Claude copilot for the preferences and the driver editor (runs in the worker).

The worker runs the interpreter of the runs: it sees the same
``gemseo-claude-pilot`` package, Claude Code login and keyring as the runner.
"""

from typing import Any

from gemseo_process_builder.workers.server import RequestContext

INSTALL = (
    "The Claude copilot is not installed in this Python: install it with "
    'pip install "gemseo-claude-pilot @ git+https://github.com/jcdulas/'
    'GemseoProcessBuilder.git#subdirectory=plugins/gemseo_claude_pilot".'
)


def copilot_status(params: dict[str, Any], context: RequestContext) -> dict[str, Any]:
    """Whether the plugin is installed and the chosen backend can be used."""
    try:
        import gemseo_claude_pilot
        from gemseo_claude_pilot.backends import create_backend
    except ImportError:
        return {"installed": False, "ok": False, "message": INSTALL}
    backend = create_backend(str(params.get("backend") or "claude_code"))
    if backend is None:
        return {"installed": True, "ok": False, "message": "The copilot is off."}
    status = backend.check()  # type: ignore[union-attr]
    return {
        "installed": True,
        "version": gemseo_claude_pilot.__version__,
        "ok": status.ok,
        "message": status.message,
    }


def store_key(params: dict[str, Any], context: RequestContext) -> None:
    """Keep the API key in the OS keyring."""
    from gemseo_claude_pilot.auth import store_api_key

    store_api_key(str(params["key"]))


def delete_key(params: dict[str, Any], context: RequestContext) -> None:
    """Remove the API key from the OS keyring."""
    from gemseo_claude_pilot.auth import delete_api_key

    delete_api_key()


def register(server: Any) -> None:
    """Add the copilot methods to the worker."""
    server.add("copilot.status", copilot_status)
    server.add("copilot.store_key", store_key)
    server.add("copilot.delete_key", delete_key)
