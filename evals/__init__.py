"""Evals against the live APIs. Need both keys; only made-up data is sent."""

import sys

from app import ai as ai_layer
from app import config


def real_ai() -> ai_layer.AI:
    ai = ai_layer.build(config.load_settings())
    if not ai.enabled:
        sys.exit("Both API keys are needed to run the evals. Set DEEPSEEK_API_KEY and TYPESAFE_API_KEY in .env.")
    return ai
