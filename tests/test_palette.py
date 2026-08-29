from surveytool.charts.palette import CATEGORICAL_PALETTE, assign_series_colours
from surveytool.charts.errors import PaletteExhaustedError
import pytest


def test_palette_has_at_least_twelve_entries():
    assert len(CATEGORICAL_PALETTE) >= 12


def test_palette_entries_are_unique_hex_colours():
    assert len(set(CATEGORICAL_PALETTE)) == len(CATEGORICAL_PALETTE)
    for colour in CATEGORICAL_PALETTE:
        assert colour.startswith("#") and len(colour) == 7


def test_assign_series_colours_gives_distinct_colours_to_seven_series():
    identities = [f"Option {i}" for i in range(7)]
    assignment = assign_series_colours(identities)
    assert len(assignment) == 7
    assert len(set(assignment.values())) == 7


def test_assign_series_colours_is_stable_by_identity_not_position():
    full = assign_series_colours(["A", "B", "C", "D"])
    subset = assign_series_colours(["B", "D"])
    assert subset["B"] == full["B"]
    assert subset["D"] == full["D"]


def test_assign_series_colours_reordering_input_does_not_change_assignment():
    a = assign_series_colours(["Red", "Blue", "Green"])
    b = assign_series_colours(["Green", "Red", "Blue"])
    assert a == b


def test_assign_series_colours_raises_when_exceeding_palette_size():
    too_many = [f"Option {i}" for i in range(len(CATEGORICAL_PALETTE) + 1)]
    with pytest.raises(PaletteExhaustedError):
        assign_series_colours(too_many)


def test_palette_exhausted_error_message_is_plain_english():
    too_many = [f"Option {i}" for i in range(len(CATEGORICAL_PALETTE) + 1)]
    try:
        assign_series_colours(too_many)
    except PaletteExhaustedError as exc:
        assert "colour" in exc.message.lower() or "color" in exc.message.lower()
        assert exc.next_action
