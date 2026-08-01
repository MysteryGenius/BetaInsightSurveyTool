from __future__ import annotations

# Canonical demographic vocabulary, shared by adapters (to flag Question.is_demographic
# from question text when a vendor has no structural marker like Rakuten's "S" qid prefix)
# and by compute/cross_tab.py (to resolve a demographic name/alias to a Question).
STANDARD_DEMOGRAPHIC_ALIASES: dict[str, tuple[str, ...]] = {
    "age": ("age", "how old are you"),
    "gender": ("gender", "sex"),
    "region": ("region", "residential status", "location", "residence"),
}
CONDITIONAL_DEMOGRAPHIC_ALIASES: dict[str, tuple[str, ...]] = {
    "income": ("income",),
    "race": ("race", "ethnicity"),
}


def text_matches_demographic(text: str) -> bool:
    """True if question text contains any standard or conditional demographic alias."""
    text_lower = text.lower()
    for aliases in (*STANDARD_DEMOGRAPHIC_ALIASES.values(), *CONDITIONAL_DEMOGRAPHIC_ALIASES.values()):
        if any(alias in text_lower for alias in aliases):
            return True
    return False
