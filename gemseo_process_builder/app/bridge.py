"""Communication between the web page and Python (SPEC § 3.4).

The page calls Python methods through a single QWebChannel object, ``bridge``:

- ``call(request)`` receives ``{"id", "method", "params"}`` as a JSON string;
- the answer comes back through the ``reply`` signal as
  ``{"id", "ok": true, "result"}`` or ``{"id", "ok": false, "error"}``;
- Python pushes events to the page through the ``page_event`` signal as
  ``{"type", "payload"}``.

Methods are registered in a ``MethodRegistry``, which does not depend on Qt so
that it can be tested on its own.
"""

import inspect
import json
import logging
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import ValidationError
from PySide6.QtCore import QObject
from PySide6.QtCore import QRunnable
from PySide6.QtCore import QThreadPool
from PySide6.QtCore import Signal
from PySide6.QtCore import Slot

_LOGGER = logging.getLogger(__name__)

Handler = Callable[..., Any]


class ErrorCode:
    """The error codes sent to the page."""

    INVALID_REQUEST = "invalid_request"
    UNKNOWN_METHOD = "unknown_method"
    INVALID_PARAMS = "invalid_params"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    WORKER_UNAVAILABLE = "worker_unavailable"
    INTERNAL = "internal"


class BridgeError(Exception):
    """An error reported to the page with a code, a message and details."""

    def __init__(self, code: str, message: str, details: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details

    def to_dict(self) -> dict[str, Any]:
        """Return the error as sent in a reply."""
        return {"code": self.code, "message": self.message, "details": self.details}


class Request(BaseModel):
    """A call from the page."""

    model_config = ConfigDict(extra="forbid")

    id: str
    method: str
    params: dict[str, Any] = {}


@dataclass(frozen=True)
class Method:
    """A registered method."""

    name: str
    handler: Handler
    params_model: type[BaseModel] | None
    background: bool


def _find_params_model(handler: Handler) -> type[BaseModel] | None:
    """Return the Pydantic model annotating the handler's only parameter, if any."""
    parameters = list(inspect.signature(handler, eval_str=True).parameters.values())
    if not parameters:
        return None
    if len(parameters) > 1:
        msg = f"{handler.__qualname__} must take at most one parameter."
        raise TypeError(msg)
    annotation = parameters[0].annotation
    if not (isinstance(annotation, type) and issubclass(annotation, BaseModel)):
        msg = f"The parameter of {handler.__qualname__} must be a Pydantic model."
        raise TypeError(msg)
    return annotation


class MethodRegistry:
    """The methods that the page can call, by name."""

    def __init__(self) -> None:
        self._methods: dict[str, Method] = {}

    def add(self, name: str, handler: Handler, *, background: bool = False) -> None:
        """Register a method.

        Args:
            name: The name used by the page, like ``"project.open"``.
            handler: A function taking either nothing or one Pydantic model
                holding the parameters, and returning a JSON-serializable value.
            background: Whether the handler runs in a thread pool instead of the
                Qt thread (for long operations).
        """
        if name in self._methods:
            msg = f"The method {name!r} is already registered."
            raise ValueError(msg)
        self._methods[name] = Method(
            name, handler, _find_params_model(handler), background
        )

    def method(
        self, name: str, *, background: bool = False
    ) -> Callable[[Handler], Handler]:
        """Register the decorated function as a method (see ``add``)."""

        def register(handler: Handler) -> Handler:
            self.add(name, handler, background=background)
            return handler

        return register

    def get(self, name: str) -> Method:
        """Return a method, or raise ``BridgeError`` if it does not exist."""
        try:
            return self._methods[name]
        except KeyError:
            raise BridgeError(
                ErrorCode.UNKNOWN_METHOD, f"Unknown method {name!r}."
            ) from None

    @property
    def names(self) -> list[str]:
        """The names of the registered methods."""
        return sorted(self._methods)


def parse_request(text: str) -> Request:
    """Decode a request, or raise ``BridgeError`` with ``invalid_request``."""
    try:
        return Request.model_validate_json(text)
    except ValidationError as error:
        raise BridgeError(
            ErrorCode.INVALID_REQUEST,
            "The request is not a valid JSON call.",
            error.errors(include_url=False),
        ) from None


def invoke(method: Method, params: dict[str, Any]) -> Any:
    """Validate the parameters and call the handler of a method."""
    if method.params_model is None:
        if params:
            raise BridgeError(
                ErrorCode.INVALID_PARAMS, f"{method.name} takes no parameters."
            )
        return method.handler()
    try:
        validated = method.params_model.model_validate(params)
    except ValidationError as error:
        raise BridgeError(
            ErrorCode.INVALID_PARAMS,
            f"Invalid parameters for {method.name}.",
            error.errors(include_url=False, include_context=False),
        ) from None
    return method.handler(validated)


def _to_json_compatible(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    msg = f"Object of type {type(value).__name__} is not JSON serializable."
    raise TypeError(msg)


def dumps(value: Any) -> str:
    """Encode a value as JSON, turning Pydantic models into plain data."""
    return json.dumps(value, default=_to_json_compatible, ensure_ascii=False)


def ok_reply(request_id: str, result: Any) -> str:
    """Encode a successful reply."""
    return dumps({"id": request_id, "ok": True, "result": result})


def error_reply(request_id: str, error: BridgeError) -> str:
    """Encode an error reply."""
    return dumps({"id": request_id, "ok": False, "error": error.to_dict()})


def internal_error(error: Exception, dev_mode: bool) -> BridgeError:
    """Wrap an unexpected exception; the traceback is only sent in dev mode."""
    details = traceback.format_exception(error) if dev_mode else None
    return BridgeError(ErrorCode.INTERNAL, str(error) or type(error).__name__, details)


class _BackgroundCall(QRunnable):
    """Run a method in the thread pool and hand the reply to the bridge."""

    def __init__(
        self,
        bridge: "Bridge",
        method: Method,
        request: Request,
    ) -> None:
        super().__init__()
        self._bridge = bridge
        self._method = method
        self._request = request

    def run(self) -> None:
        self._bridge._background_reply.emit(
            self._bridge._execute(self._method, self._request)
        )


class Bridge(QObject):
    """The object shared with the page through QWebChannel."""

    reply = Signal(str)
    """Emitted with the JSON reply of each call."""

    page_event = Signal(str)
    """Emitted with each JSON event pushed to the page."""

    # Emitted from pool threads; delivered in the Qt thread (queued connection).
    _background_reply = Signal(str)

    def __init__(self, registry: MethodRegistry, dev_mode: bool = False) -> None:
        super().__init__()
        self.registry = registry
        self.dev_mode = dev_mode
        self._background_reply.connect(self._forward_reply)

    @Slot(str)
    def call(self, request_text: str) -> None:
        """Handle one call from the page."""
        try:
            request = parse_request(request_text)
            method = self.registry.get(request.method)
        except BridgeError as error:
            request_id = _extract_id(request_text)
            _LOGGER.warning("Rejected call %s: %s", request_id, error.message)
            self.reply.emit(error_reply(request_id, error))
            return

        if method.background:
            QThreadPool.globalInstance().start(_BackgroundCall(self, method, request))
        else:
            self.reply.emit(self._execute(method, request))

    def emit_event(self, event_type: str, payload: Any = None) -> None:
        """Push an event to the page."""
        self.page_event.emit(dumps({"type": event_type, "payload": payload}))

    @Slot(str)
    def _forward_reply(self, reply_text: str) -> None:
        self.reply.emit(reply_text)

    def _execute(self, method: Method, request: Request) -> str:
        start = time.perf_counter()
        try:
            text = ok_reply(request.id, invoke(method, request.params))
        except BridgeError as error:
            text = error_reply(request.id, error)
        except Exception as error:
            _LOGGER.exception("Method %s failed", method.name)
            text = error_reply(request.id, internal_error(error, self.dev_mode))
        _LOGGER.debug(
            "%s answered in %.1f ms", method.name, (time.perf_counter() - start) * 1e3
        )
        return text


def _extract_id(request_text: str) -> str:
    """Best-effort extraction of the id of an invalid request."""
    try:
        data = json.loads(request_text)
    except ValueError:
        return ""
    if isinstance(data, dict) and isinstance(data.get("id"), str):
        return str(data["id"])
    return ""
