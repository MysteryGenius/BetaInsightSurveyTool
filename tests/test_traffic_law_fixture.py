"""
Traffic-law-file classification exit condition (spec Prompt 4/Prompt 5).

Skipped until the traffic law survey fixture is supplied — its filename and
vendor are not yet known (the spec names S5/S6/Q1-Q10 but not a file path).
Once the file arrives, replace _TRAFFIC_LAW_PATH below with its real path
and vendor, and fill in the loader call.
"""
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent
_TRAFFIC_LAW_PATH = _ROOT / "traffic_law_survey_data.xlsx"  # placeholder name — confirm against the real filename when supplied


@pytest.mark.skipif(
    not _TRAFFIC_LAW_PATH.exists(),
    reason="Traffic law survey fixture not yet supplied by the client — filename and vendor unconfirmed.",
)
def test_traffic_law_s5_classifies_binary():
    pytest.skip("Awaiting traffic law fixture and confirmation of which vendor adapter parses it.")


@pytest.mark.skipif(
    not _TRAFFIC_LAW_PATH.exists(),
    reason="Traffic law survey fixture not yet supplied by the client — filename and vendor unconfirmed.",
)
def test_traffic_law_s6_classifies_calendar_frequency():
    pytest.skip("Awaiting traffic law fixture.")


@pytest.mark.skipif(
    not _TRAFFIC_LAW_PATH.exists(),
    reason="Traffic law survey fixture not yet supplied by the client — filename and vendor unconfirmed.",
)
def test_traffic_law_q1_to_q10_classify_agreement_scale():
    pytest.skip("Awaiting traffic law fixture.")


@pytest.mark.skipif(
    not _TRAFFIC_LAW_PATH.exists(),
    reason="Traffic law survey fixture not yet supplied by the client — filename and vendor unconfirmed.",
)
def test_traffic_law_top_two_box_on_s5_raises():
    pytest.skip("Awaiting traffic law fixture.")
