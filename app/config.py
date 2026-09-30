"""Settings from environment variables, with .env for local runs."""

import os
from dataclasses import dataclass
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


@dataclass(frozen=True)
class Settings:
    deepseek_api_key: str
    deepseek_base_url: str
    deepseek_model: str
    typesafe_api_key: str
    jev_model: str


def load_dotenv(path: Path = ENV_FILE) -> None:
    """Load KEY=VALUE lines. Existing variables win."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def load_settings() -> Settings:
    """RECRUITLY_AI=off disables the AI layer even if keys are set."""
    off = os.environ.get("RECRUITLY_AI", "").lower() == "off"
    if not off:
        load_dotenv()

    def env(name: str, default: str = "") -> str:
        return os.environ.get(name, "").strip() or default

    return Settings(
        deepseek_api_key="" if off else env("DEEPSEEK_API_KEY"),
        deepseek_base_url=env("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        deepseek_model=env("DEEPSEEK_MODEL", "deepseek-chat"),
        # JEV_API_KEY also accepted.
        typesafe_api_key="" if off else env("TYPESAFE_API_KEY") or env("JEV_API_KEY"),
        # Pinned so scores and thresholds don't shift between releases.
        jev_model=env("JEV_MODEL", "jev-1.13.0"),
    )
