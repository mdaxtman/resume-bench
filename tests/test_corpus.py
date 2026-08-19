"""Corpus sanity. The JDs are curated files, so this only guards against a
malformed one being dropped in — not against arbitrary input."""

import corpus


def test_corpus_loads() -> None:
    slugs = corpus.list_slugs()
    assert len(slugs) >= 5
    for slug in slugs:
        body = corpus.load_jd(slug)
        assert len(body) > 500, f"{slug}: JD suspiciously short"
        assert not body.lstrip().startswith("---"), f"{slug}: strip the frontmatter before adding"
