from obsidian_mcp.groundedness import GENERIC_MARKERS, check_register


def test_empty_input_returns_empty():
    assert check_register("") == []
    assert check_register(None) == []  # type: ignore[arg-type]


def test_no_markers_returns_empty():
    answer = (
        "The note `projects/retrieval.md` describes a TF-IDF re-rank step "
        "that runs after the kNN candidate fetch. See `semantic.py` for the "
        "weight defaults."
    )
    assert check_register(answer) == []


def test_single_marker_hit():
    assert check_register("Generally speaking, your vault is structured well.") == [
        "generally speaking",
    ]


def test_case_insensitive():
    assert check_register("HOWEVER, BASED ON MY KNOWLEDGE this works.") == [
        "however, based on my knowledge",
    ]


def test_multiple_markers_all_returned():
    answer = (
        "Generally speaking, daily notes work like this. Typically, "
        "people add a date stamp at the top."
    )
    hits = check_register(answer)
    assert "generally speaking" in hits
    assert "typically," in hits


def test_marker_appears_only_once_in_result():
    answer = "typically, X. typically, Y. typically, Z."
    assert check_register(answer) == ["typically,"]


def test_partial_word_does_not_match():
    # "in general" without trailing comma should not fire (we keyed the
    # marker as "in general," to avoid matching "in generalised cases").
    assert check_register("in generalised retrieval") == []


def test_known_marker_set_is_stable():
    # Cheap regression check: if someone reorders or adds markers we
    # want the test to catch it so the explicit list is reviewed.
    assert "generally speaking" in GENERIC_MARKERS
    assert "i don't have access to" in GENERIC_MARKERS
