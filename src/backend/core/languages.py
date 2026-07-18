"""The 17 target languages (SPEC Quick Reference).

Single source of truth for the code → English display-name mapping. The
document translator maps a language code to a name for the prompt; Sprint 5's
`/languages` endpoint and Sprint 6's picker read the same list (tiers are added
there, not here).
"""

# ISO 639-1 code → English display name. Order = SPEC Quick Reference.
LANGUAGES: dict[str, str] = {
    "en": "English",
    "ar": "Arabic",
    "de": "German",
    "es": "Spanish",
    "fr": "French",
    "hi": "Hindi",
    "hr": "Croatian",
    "id": "Indonesian",
    "it": "Italian",
    "ja": "Japanese",
    "ne": "Nepali",
    "nl": "Dutch",
    "pl": "Polish",
    "pt": "Portuguese",
    "sv": "Swedish",
    "th": "Thai",
    "ur": "Urdu",
}


def language_name(code: str) -> str:
    """English display name for a language code; falls back to the code itself."""
    return LANGUAGES.get((code or "").lower(), code)
