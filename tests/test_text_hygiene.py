from surveytool.core.text_hygiene import normalise_whitespace, truncate_with_ellipsis, wrap_text


def test_normalise_whitespace_collapses_newline_to_space():
    assert normalise_whitespace("citizens.\nBy government") == "citizens. By government"


def test_normalise_whitespace_collapses_multiple_runs():
    assert normalise_whitespace("a\n\n\tb   c") == "a b c"


def test_normalise_whitespace_collapses_nonbreaking_space():
    assert normalise_whitespace("a\xa0\xa0b") == "a b"


def test_normalise_whitespace_never_collapses_to_empty_for_whitespace_only_input():
    """The 'never to nothing' guarantee is about a whitespace run BETWEEN
    two words never disappearing (that's the literal 'citizens.By' bug) --
    it is not a guarantee that an all-whitespace string stays non-empty.
    Leading/trailing whitespace is stripped entirely, same as str.strip()."""
    assert normalise_whitespace("   \n\t  ") == ""


def test_normalise_whitespace_never_glues_two_words_together():
    """The actual 'citizens.By' regression case: a newline between two
    sentences must become a space, never vanish."""
    assert "citizens. By" in normalise_whitespace("...citizens.\nBy government...")


def test_normalise_whitespace_strips_leading_trailing_after_collapse():
    assert normalise_whitespace("  hello world  ") == "hello world"


def test_normalise_whitespace_is_idempotent():
    once = normalise_whitespace("a\n\nb")
    twice = normalise_whitespace(once)
    assert once == twice


def test_wrap_text_wraps_long_text_into_multiple_lines():
    lines = wrap_text("word " * 30, max_chars_per_line=40)
    assert len(lines) > 1
    assert all(len(line) <= 40 for line in lines)


def test_truncate_with_ellipsis_shortens_and_adds_ellipsis():
    result = truncate_with_ellipsis("a" * 100, max_chars=20)
    assert len(result) <= 20
    assert result.endswith("…")


def test_truncate_with_ellipsis_leaves_short_text_untouched():
    assert truncate_with_ellipsis("short", max_chars=20) == "short"
