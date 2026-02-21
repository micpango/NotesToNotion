"""
Stable app-level constants used by runtime + tests.
Keep this file dependency-free (no rumps/requests/etc).
"""

APP_NAME = "NotesToNotion"
APP_VERSION = "v0.2.4"  # bump when you ship
NOTION_VERSION = "2025-09-03"
DEFAULT_OPENAI_MODEL = "gpt-5-mini"

# TODO: Replace with your current official OpenAI pricing for the model you use.
PRICE_PER_1M_INPUT_TOKENS_USD = 1.00
PRICE_PER_1M_OUTPUT_TOKENS_USD = 3.00
