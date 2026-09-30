"""Optional AI layer. Off unless both API keys are set."""

from dataclasses import dataclass

from ..config import Settings


@dataclass
class AI:
    deepseek: object | None = None  # deepseek.DeepSeekClient
    jev: object | None = None       # jev.JevClient

    @property
    def enabled(self) -> bool:
        # Search and rating each need both models.
        return self.deepseek is not None and self.jev is not None


def build(settings: Settings) -> AI:
    from .deepseek import DeepSeekClient
    from .jev import JevClient
    return AI(
        deepseek=DeepSeekClient(settings.deepseek_api_key, settings.deepseek_base_url, settings.deepseek_model)
        if settings.deepseek_api_key else None,
        jev=JevClient(settings.typesafe_api_key, settings.jev_model) if settings.typesafe_api_key else None,
    )
