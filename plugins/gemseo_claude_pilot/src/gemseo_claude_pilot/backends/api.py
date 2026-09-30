"""The API key backend: the Messages API of Anthropic (spec § 5.1, § 5.2).

One turn per call; the exchange runs the loop of tool calls. The system prompt
and the tools are the same for every call of a run: they are cached. The turns
of Claude are sent back as received, thinking blocks included.
"""

from typing import Any

from gemseo_claude_pilot.auth import api_key
from gemseo_claude_pilot.backends.base import AuthenticationError
from gemseo_claude_pilot.backends.base import BackendError
from gemseo_claude_pilot.backends.base import BackendStatus
from gemseo_claude_pilot.backends.base import BackendTimeoutError
from gemseo_claude_pilot.backends.base import Message
from gemseo_claude_pilot.backends.base import RateLimitError
from gemseo_claude_pilot.backends.base import Reply
from gemseo_claude_pilot.backends.base import Request
from gemseo_claude_pilot.backends.base import ToolCall
from gemseo_claude_pilot.backends.base import Usage
from gemseo_claude_pilot.pricing import estimate_cost

NO_KEY = (
    "No API key: set ANTHROPIC_API_KEY, or store a key in the Copilot "
    "preferences of GEMSEO Process Builder."
)


class ApiKeyBackend:
    """Talks to Claude through the Messages API, with an API key.

    Args:
        key: The API key; by default from the environment or the keyring.
        timeout: The seconds to wait for one request.
        max_retries: The retries of the SDK on network errors, 429 and 5xx.
        max_tokens: The tokens Claude may write in one turn.
        client: A client with the interface of ``anthropic.Anthropic``, for
            the tests; created from the key by default.
    """

    name = "api_key"

    def __init__(
        self,
        key: str | None = None,
        timeout: float = 90.0,
        max_retries: int = 2,
        max_tokens: int = 16_000,
        client: Any = None,
    ) -> None:
        self._key = key
        self._timeout = timeout
        self._max_retries = max_retries
        self._max_tokens = max_tokens
        self._client = client

    def check(self) -> BackendStatus:
        """Whether a key is there; the key itself is checked by the first call."""
        if self._client is not None or self._key or api_key():
            return BackendStatus(True, "An API key is set.")
        return BackendStatus(False, NO_KEY)

    def send(self, request: Request) -> Reply:
        """Send the conversation and return the next turn of Claude.

        Raises:
            BackendError: When the call fails.
        """
        import anthropic

        client = self._get_client()
        try:
            response = client.messages.create(
                **request_parameters(request, self._max_tokens)
            )
        except (
            anthropic.AuthenticationError,
            anthropic.PermissionDeniedError,
        ) as error:
            raise AuthenticationError(f"The API key was refused: {error}") from error
        except anthropic.RateLimitError as error:
            raise RateLimitError(f"Rate limited: {error}") from error
        except anthropic.APITimeoutError as error:
            raise BackendTimeoutError("Claude did not answer in time.") from error
        except anthropic.APIConnectionError as error:
            raise BackendError(f"No connection to the API: {error}") from error
        except anthropic.APIStatusError as error:
            raise BackendError(f"API error {error.status_code}: {error}") from error
        return parse_response(response, request.model)

    def _get_client(self) -> Any:
        if self._client is None:
            key = self._key or api_key()
            if not key:
                raise AuthenticationError(NO_KEY)
            import anthropic

            self._client = anthropic.Anthropic(
                api_key=key, timeout=self._timeout, max_retries=self._max_retries
            )
        return self._client


def request_parameters(request: Request, max_tokens: int) -> dict[str, Any]:
    """The parameters of ``messages.create`` for a request."""
    parameters = {
        "model": request.model,
        "max_tokens": max_tokens,
        # The system prompt and the tools before it are the same at every call.
        "system": [
            {
                "type": "text",
                "text": request.system,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "tools": [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": dict(tool.input_schema),
            }
            for tool in request.tools
        ],
        "messages": [_message(message) for message in request.messages],
    }
    if request.effort:
        parameters["output_config"] = {"effort": request.effort}
    return parameters


def parse_response(response: Any, model: str) -> Reply:
    """The turn of Claude in a response of ``messages.create``."""
    texts = []
    calls = []
    for block in response.content:
        if block.type == "text":
            texts.append(block.text)
        elif block.type == "tool_use":
            calls.append(ToolCall(block.id, block.name, dict(block.input)))
    usage = response.usage
    written = getattr(usage, "cache_creation_input_tokens", 0) or 0
    read = getattr(usage, "cache_read_input_tokens", 0) or 0
    return Reply(
        text="\n\n".join(texts),
        tool_calls=tuple(calls),
        usage=Usage(
            input_tokens=usage.input_tokens + written,
            output_tokens=usage.output_tokens,
            cached_tokens=read,
            cost_usd=estimate_cost(
                model, usage.input_tokens, usage.output_tokens, written, read
            ),
        ),
        stop_reason=response.stop_reason or "",
        raw=response.content,
    )


def _message(message: Message) -> dict[str, Any]:
    if message.role == "assistant":
        if message.raw is not None:
            return {"role": "assistant", "content": message.raw}
        content: list[dict[str, Any]] = []
        if message.text:
            content.append({"type": "text", "text": message.text})
        content += [
            {"type": "tool_use", "id": call.id, "name": call.name, "input": call.input}
            for call in message.tool_calls
        ]
        return {"role": "assistant", "content": content}
    if message.tool_results:
        return {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": result.tool_call_id,
                    "content": result.content,
                    "is_error": result.is_error,
                }
                for result in message.tool_results
            ],
        }
    return {"role": "user", "content": message.text}
