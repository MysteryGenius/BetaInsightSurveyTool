from surveytool.charts.errors import UnresolvedQuestion, UnresolvedQuestionsError


def test_unresolved_questions_error_message_states_count():
    entries = [
        UnresolvedQuestion(variable="Q3", question_text="How often?", codes=[(1, "Purple")], reason="No family matched 'purple'."),
        UnresolvedQuestion(variable="Q7", question_text="How able?", codes=[(1, "Kinda")], reason="No family matched 'kinda'."),
        UnresolvedQuestion(variable="Q9", question_text="How much?", codes=[(1, "Bunches")], reason="No family matched 'bunches'."),
    ]
    err = UnresolvedQuestionsError(entries)
    assert "3" in err.message
    assert err.detail_entries == entries
    assert "scales.yaml" not in err.message.lower()
    assert "yaml" not in err.message.lower()
    assert "override" not in err.next_action.lower() or "resolver" in err.next_action.lower()


def test_unresolved_questions_error_next_action_is_plain_english():
    entries = [UnresolvedQuestion(variable="Q1", question_text="text", codes=[], reason="reason")]
    err = UnresolvedQuestionsError(entries)
    for forbidden in ("scales.yaml", ".yaml", "surveytool/", "repository"):
        assert forbidden not in err.next_action.lower()
        assert forbidden not in err.message.lower()
