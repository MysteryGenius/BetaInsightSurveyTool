from surveytool.core.precision import DISPLAY_PRECISION, format_percentage


def test_format_percentage_uses_display_precision_by_default():
    assert format_percentage(8.230453) == f"{8.230453:.{DISPLAY_PRECISION}f}%"


def test_format_percentage_rounds_correctly():
    assert format_percentage(8.230453, precision=1) == "8.2%"


def test_format_percentage_accepts_explicit_precision_override():
    assert format_percentage(8.230453, precision=3) == "8.230%"
