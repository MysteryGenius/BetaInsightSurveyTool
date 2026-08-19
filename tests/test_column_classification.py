from surveytool.core.column_classification import ColumnClassification, UnclassifiedColumnError


def test_column_classification_members():
    assert {c.name for c in ColumnClassification} == {
        "QUESTION", "DEMOGRAPHIC", "METADATA", "QUALITY", "OPEN_END", "UNCLASSIFIED",
    }


def test_unclassified_column_error_names_column_and_header():
    err = UnclassifiedColumnError(column="Q99xyz", header_text="Q99xyz")
    assert "Q99xyz" in err.message or "Q99xyz" in (err.detail or "")
    assert err.code.value == "UNCLASSIFIED_COLUMN"
