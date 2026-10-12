import base64
import os
import tempfile
from pathlib import Path


def session_path_from_env(default_path: str) -> Path:
    """Resolve a local session file or materialize its base64 value in temp storage."""
    encoded = os.getenv("TELEGRAM_SESSION_BASE64", "").strip()
    if encoded:
        try:
            session_bytes = base64.b64decode(encoded, validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            raise ValueError("TELEGRAM_SESSION_BASE64 is not valid base64.") from exc
        if not session_bytes:
            raise ValueError("TELEGRAM_SESSION_BASE64 decoded to an empty file.")

        path = Path(tempfile.gettempdir()) / "telegram-relay-session.session"
        path.write_bytes(session_bytes)
        try:
            path.chmod(0o600)
        except OSError:
            pass
        return path

    return Path(default_path)
