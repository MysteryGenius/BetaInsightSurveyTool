"""
Fixture: unknown label raises loudly.

A label set containing a label that matches no scale family
and has no neither…nor pattern must cause resolve_roles to raise ValueError.
"""

KNOWN_LABELS = ["Strongly Agree", "Agree", "Neutral", "Disagree", "Strongly Disagree"]

UNKNOWN_LABELS = ["Strongly Agree", "Agree", "Neutral", "Disagree", "Strongly Disagree", "Gobbledygook"]

UNRESOLVABLE_LABEL = "Gobbledygook"
