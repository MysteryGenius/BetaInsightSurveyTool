from surveytool.core.hygiene import fold_label


def test_fold_label_en_dash_to_hyphen():
    assert fold_label("18–24") == "18-24"  # en-dash


def test_fold_label_em_dash_to_hyphen():
    assert fold_label("18—24") == "18-24"  # em-dash


def test_fold_label_non_breaking_hyphen_to_hyphen():
    assert fold_label("18‑24") == "18-24"  # non-breaking hyphen


def test_fold_label_non_breaking_space_to_space():
    assert fold_label("very satisfied") == "very satisfied"


def test_fold_label_curly_quotes_to_straight():
    assert fold_label("don’t know") == "don't know"
    assert fold_label("“yes”") == '"yes"'


def test_fold_label_case_folds():
    assert fold_label("STRONGLY AGREE") == "strongly agree"


def test_fold_label_collapses_whitespace_and_strips():
    assert fold_label("  strongly   agree  ") == "strongly agree"


def test_fold_label_no_stemming_or_fuzzy_matching():
    """fold_label must not alter word forms — only the exact listed
    transformations. 'agrees' must stay 'agrees', not become 'agree'."""
    assert fold_label("Agrees") == "agrees"
