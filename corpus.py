"""Loading the JD corpus.

The corpus is a curated directory of plain markdown, not arbitrary pasted text:
frontmatter and other clipper artefacts are removed from the files themselves
when a JD is added. Nothing needs parsing at load time.
"""

from config import JOBS_DIR


def list_slugs() -> list[str]:
    return sorted(d.name for d in JOBS_DIR.iterdir() if d.is_dir() and (d / "jd.md").is_file())


def load_jd(slug: str) -> str:
    path = JOBS_DIR / slug / "jd.md"
    if not path.is_file():
        raise ValueError(f"No JD at {path}")
    return path.read_text()
