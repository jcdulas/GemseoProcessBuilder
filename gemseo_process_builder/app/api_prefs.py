"""Preferences methods: ``prefs.*``."""

from typing import Any

from pydantic import BaseModel
from pydantic import ValidationError

from gemseo_process_builder.app.bridge import Bridge
from gemseo_process_builder.app.bridge import BridgeError
from gemseo_process_builder.app.bridge import ErrorCode
from gemseo_process_builder.app.preferences import PreferencesStore


class SetPreferencesParams(BaseModel):
    """Parameters of ``prefs.set``."""

    values: dict[str, Any]


def register_prefs_methods(bridge: Bridge, store: PreferencesStore) -> None:
    """Register ``prefs.get`` and ``prefs.set``.

    ``prefs.set`` emits a ``prefs.changed`` event with the new preferences.
    """

    def get() -> dict[str, Any]:
        return store.preferences.model_dump(mode="json")

    def set_(params: SetPreferencesParams) -> dict[str, Any]:
        try:
            preferences = store.update(params.values)
        except ValidationError as error:
            raise BridgeError(
                ErrorCode.INVALID_PARAMS,
                "Invalid preferences.",
                error.errors(include_url=False, include_context=False),
            ) from None
        data = preferences.model_dump(mode="json")
        bridge.emit_event("prefs.changed", data)
        return data

    bridge.registry.add("prefs.get", get)
    bridge.registry.add("prefs.set", set_)
