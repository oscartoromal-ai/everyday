from app.checklist import normalize, parse, progress, reset, toggle

BODY = """Work calendar uses ICS; Outlook blocks OAuth.
- [ ] fetch the feed
- [x] parse VEVENTs
    watch out for TZID quirks
- ICS, not CalDAV

* [ ] dedupe recurring instances
  - [ ] nested one"""


def test_boxed_lines_are_items_bare_ones_bullets_and_everything_else_text() -> None:
    lines = parse(BODY)
    kinds = [(line.kind, line.text) for line in lines]
    assert kinds == [
        ("text", "Work calendar uses ICS; Outlook blocks OAuth."),
        ("item", "fetch the feed"),
        ("item", "parse VEVENTs"),
        ("text", "    watch out for TZID quirks"),
        ("bullet", "ICS, not CalDAV"),
        ("blank", ""),
        ("item", "dedupe recurring instances"),
        ("item", "nested one"),
    ]
    items = [line for line in lines if line.kind == "item"]
    assert [i.index for i in items] == [0, 1, 2, 3]
    assert [i.checked for i in items] == [False, True, False, False]
    assert [i.depth for i in items] == [0, 0, 0, 1]


def test_a_bare_dash_or_a_rule_is_neither_item_nor_bullet() -> None:
    assert [line.kind for line in parse("-\n- \n---\n-no space")] == [
        "text",
        "text",
        "text",
        "text",
    ]


def test_plus_lists_work_as_dashes_do() -> None:
    assert [line.kind for line in parse("+ [ ] a\n+ b")] == ["item", "bullet"]


def test_lines_in_fenced_code_are_code() -> None:
    notes = "```\n- [ ] not a sub-task\n- nor a bullet\n```\n- [ ] a sub-task"
    assert [line.kind for line in parse(notes)] == ["text", "text", "text", "text", "item"]
    assert progress(notes) == (0, 1)
    ticked = toggle(notes, 0, "a sub-task")
    assert ticked is not None
    assert ticked.endswith("- [x] a sub-task")
    assert "- [ ] not a sub-task" in ticked


def test_progress_counts_done_items_not_bullets() -> None:
    assert progress(BODY) == (1, 4)
    assert progress("just prose\n- and a bullet") == (0, 0)


def test_toggle_checks_and_unchecks_in_place() -> None:
    checked = toggle(BODY, 0, "fetch the feed")
    assert checked is not None
    assert "- [x] fetch the feed" in checked
    assert progress(checked) == (2, 4)
    # Everything else is untouched.
    assert checked.replace("- [x] fetch the feed", "- [ ] fetch the feed") == BODY

    unchecked = toggle(checked, 0, "fetch the feed")
    assert unchecked == BODY

    nested = toggle(BODY, 3, "nested one")
    assert "  - [x] nested one" in nested


def test_toggle_refuses_a_stale_item() -> None:
    # The description changed since the page rendered: index 0 is now another item.
    assert toggle(BODY, 0, "something else") is None
    assert toggle(BODY, 9, "fetch the feed") is None


def test_reset_unchecks_everything() -> None:
    assert progress(reset(BODY)) == (0, 4)
    assert "- [ ] parse VEVENTs" in reset(BODY)
    assert "- ICS, not CalDAV" in reset(BODY)


def test_normalize_unifies_line_endings_and_trims_the_edges() -> None:
    assert normalize("\r\n- a\r\n- b  \r\n\r\n") == "- a\n- b"
    assert normalize("  indented first line\n") == "  indented first line"
