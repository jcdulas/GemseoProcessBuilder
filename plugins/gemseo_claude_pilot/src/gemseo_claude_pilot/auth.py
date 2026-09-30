"""The API key of the API key backend (spec § 5.2).

Read from ``ANTHROPIC_API_KEY``, else from the OS keyring. The key never goes
into a project, a run folder, the journal, the logs or a generated script.
The application's preferences write it to the keyring with :func:`store_api_key`.
"""

import os
from contextlib import suppress

KEYRING_SERVICE = "gemseo-claude-pilot"
KEYRING_USER = "anthropic-api-key"
KEY_VARIABLE = "ANTHROPIC_API_KEY"


def api_key() -> str | None:
    """The API key: from the environment, else from the keyring, else ``None``."""
    key = os.environ.get(KEY_VARIABLE, "").strip()
    if key:
        return key
    try:
        import keyring

        stored = keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
    except Exception:  # No keyring backend on this machine, or it is locked.
        return None
    return stored or None


def store_api_key(key: str) -> None:
    """Keep the API key in the OS keyring."""
    import keyring

    keyring.set_password(KEYRING_SERVICE, KEYRING_USER, key.strip())


def delete_api_key() -> None:
    """Remove the API key from the OS keyring, if it is there."""
    import keyring
    from keyring.errors import PasswordDeleteError

    with suppress(PasswordDeleteError):
        keyring.delete_password(KEYRING_SERVICE, KEYRING_USER)
