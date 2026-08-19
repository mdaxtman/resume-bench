"""Re-scoring previously generated resumes under the current judges.

The point of this path is to hold the documents fixed and vary only the ruler,
which answers a question a fresh sweep cannot: did the pipeline get worse, or
did the measurement get honest?

That only works if the documents reach the judges anonymised. In the archive
they do not: every control resume opens with the literal line `# Control
Resume`, so the "blind" judge that scored it could read the arm off line one.
Pipeline documents open with `# Resume`, `# Refined Resume`, `# Resume Draft`,
or the candidate's own name — the last appearing on the pipeline side only,
which is its own asymmetry. So the rule is to drop any leading H1 rather than
to blocklist the labels we happen to have seen.
"""

from evaluation.rescore import redacted_slug, strip_leading_title

BODY = "## Summary\nFrontend engineer with 11 years.\n\n## Experience\n"


def test_the_control_label_is_removed() -> None:
    assert strip_leading_title("# Control Resume\n\n" + BODY) == BODY


def test_every_pipeline_label_variant_is_removed() -> None:
    for title in ("# Resume", "# Refined Resume", "# Resume Draft"):
        assert strip_leading_title(f"{title}\n\n{BODY}") == BODY


def test_a_name_header_is_removed_too() -> None:
    """Present on pipeline documents only, so leaving it in favours one arm."""
    assert strip_leading_title("# Jane Doe — Frontend Engineer\n\n" + BODY) == BODY


def test_only_a_leading_h1_is_touched() -> None:
    """An H1 further down is document content, not a label."""
    doc = BODY + "\n# Not A Title\n"
    assert strip_leading_title(doc) == doc


def test_h2_is_never_stripped() -> None:
    """Stripping `## Summary` would remove a section the judge scores."""
    assert strip_leading_title(BODY) == BODY


def test_leading_blank_lines_do_not_hide_the_title() -> None:
    assert strip_leading_title("\n\n# Control Resume\n\n" + BODY) == BODY


def test_a_document_that_is_only_a_title_becomes_empty() -> None:
    assert strip_leading_title("# Control Resume\n") == ""


def test_slug_is_mapped_to_its_redacted_form() -> None:
    mapping = {"anthropic-staff_swe_claude_code": "staff-swe-devtools-01"}
    assert redacted_slug("anthropic-staff_swe_claude_code", mapping) == "staff-swe-devtools-01"


def test_an_unmapped_slug_is_anonymised_not_passed_through() -> None:
    """A report printing real employer names is the thing the corpus redaction
    exists to prevent; an unmapped source must not defeat it."""
    out = redacted_slug("some-company_role", {})
    assert "some-company" not in out and out.startswith("unmapped-")
