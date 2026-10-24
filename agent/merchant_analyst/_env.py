"""Load the repo-root `.env` (if any) exactly once, searching upwards from this package."""

from __future__ import annotations

from pathlib import Path

from dotenv import find_dotenv, load_dotenv

_loaded_path: str | None = None
_attempted = False


def load_env() -> str | None:
    """Load the nearest `.env` found walking up from this package (falls back to cwd search).

    Existing environment variables win over `.env` values. Returns the path that was loaded,
    or None when no `.env` exists. Subsequent calls are no-ops.
    """
    global _attempted, _loaded_path
    if _attempted:
        return _loaded_path
    _attempted = True
    here = Path(__file__).resolve()
    for directory in [here.parent, *here.parents]:
        candidate = directory / ".env"
        if candidate.is_file():
            _loaded_path = str(candidate)
            break
    else:
        _loaded_path = find_dotenv(usecwd=True) or None
    if _loaded_path:
        load_dotenv(_loaded_path, override=False)
    return _loaded_path
