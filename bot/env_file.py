"""Veilig lezen en schrijven van het .env-bestand.

De setup-wizard is de enige schrijver. Eisen die deze module afdwingt:

- bestaande regels, commentaar en volgorde blijven behouden; alleen de
  opgegeven sleutels worden vervangen of toegevoegd;
- schrijven gaat atomisch via een tijdelijk bestand in dezelfde map, zodat
  een onderbroken run nooit een half .env achterlaat;
- rechten staan op 0600 (alleen de eigenaar), ook op het tijdelijke bestand,
  zodat het secret nooit even wereldleesbaar op schijf staat.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Mapping

ENV_FILENAME = ".env"
EXAMPLE_FILENAME = ".env.example"
_OWNER_ONLY = 0o600


def project_root() -> Path:
    """Projectroot: bot/env_file.py -> bot -> root."""
    return Path(__file__).resolve().parent.parent


def env_path() -> Path:
    return project_root() / ENV_FILENAME


def example_path() -> Path:
    return project_root() / EXAMPLE_FILENAME


def _needs_quoting(value: str) -> bool:
    return value != value.strip() or any(ch in value for ch in "#\n")


def format_value(value: str) -> str:
    """Serialiseer een waarde zodat python-dotenv haar exact teruggeeft.

    Een PEM-sleutel staat in .env op één regel met literal \\n; die vorm
    blijft ongewijzigd, want de auth-laag vertaalt hem zelf terug.
    """
    normalized = value.replace("\r\n", "\n").replace("\n", "\\n")
    if _needs_quoting(normalized):
        escaped = normalized.replace('"', '\\"')
        return f'"{escaped}"'
    return normalized


def read_env(path: Path | None = None) -> dict[str, str]:
    """Lees .env als dict. Ontbrekend bestand levert een lege dict."""
    target = path or env_path()
    if not target.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in target.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def write_env_values(values: Mapping[str, str], path: Path | None = None) -> Path:
    """Zet `values` in .env en laat de rest van het bestand intact.

    Retourneert het pad dat is geschreven.
    """
    target = path or env_path()
    remaining = dict(values)
    lines: list[str] = []

    if target.exists():
        for raw_line in target.read_text(encoding="utf-8").splitlines():
            stripped = raw_line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                key = stripped.partition("=")[0].strip()
                if key in remaining:
                    lines.append(f"{key}={format_value(remaining.pop(key))}")
                    continue
            lines.append(raw_line)

    if remaining:
        if lines and lines[-1].strip():
            lines.append("")
        for key, value in remaining.items():
            lines.append(f"{key}={format_value(value)}")

    _atomic_write(target, "\n".join(lines).rstrip("\n") + "\n")
    return target


def _atomic_write(target: Path, content: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)

    handle, temp_name = tempfile.mkstemp(dir=str(target.parent), prefix=".env.", suffix=".tmp")
    temp_path = Path(temp_name)
    try:
        os.fchmod(handle, _OWNER_ONLY)
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, target)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise

    os.chmod(target, _OWNER_ONLY)


def ensure_env_from_example(path: Path | None = None) -> tuple[Path, bool]:
    """Maak .env vanaf .env.example als het nog niet bestaat.

    Retourneert (pad, aangemaakt). Een bestaand .env wordt nooit overschreven.
    """
    target = path or env_path()
    if target.exists():
        return target, False

    example = example_path()
    content = example.read_text(encoding="utf-8") if example.exists() else ""
    _atomic_write(target, content)
    return target, True


def permissions_are_owner_only(path: Path | None = None) -> bool:
    target = path or env_path()
    if not target.exists():
        return False
    return (target.stat().st_mode & 0o077) == 0
