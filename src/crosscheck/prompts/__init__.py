"""Versioned prompt library for CrossCheck.

Every LLM prompt lives here as a text file, never inlined in Python (spec v2 §11).
Files are named ``<name>.v<version>.md`` — e.g. ``claim_extraction_system.v1.md``.
:func:`load_prompt` reads a prompt by name and defaults to the highest version on
disk, so revising a prompt means adding a new ``.vN.md`` file (the old version stays
for reproducibility and diffing) rather than editing history in place.
"""

import re
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files

_PROMPT_PACKAGE = __package__ or "crosscheck.prompts"
_FILENAME_RE = re.compile(r"^(?P<name>.+)\.v(?P<version>\d+)\.md$")


@dataclass(frozen=True)
class Prompt:
    """A single versioned prompt loaded from disk."""

    name: str
    version: int
    text: str

    def render(self, **substitutions: str) -> str:
        """Return the prompt text with ``{{key}}`` placeholders substituted.

        Substitution is literal string replacement, not :meth:`str.format`, so any
        braces in the substituted document text can never be misread as format fields.

        Args:
            **substitutions: Placeholder name to replacement value. ``chunks="..."``
                replaces every ``{{chunks}}`` in the prompt text.

        Returns:
            The prompt text with all given placeholders replaced.
        """
        text = self.text
        for key, value in substitutions.items():
            text = text.replace("{{" + key + "}}", value)
        return text


@lru_cache(maxsize=1)
def _index() -> dict[str, dict[int, str]]:
    """Scan the prompt package once, returning ``{name: {version: text}}``."""
    index: dict[str, dict[int, str]] = {}
    for entry in files(_PROMPT_PACKAGE).iterdir():
        match = _FILENAME_RE.match(entry.name)
        if match is None or not entry.is_file():
            continue
        name = match.group("name")
        version = int(match.group("version"))
        index.setdefault(name, {})[version] = entry.read_text(encoding="utf-8")
    return index


def load_prompt(name: str, *, version: int | None = None) -> Prompt:
    """Load a prompt by name, defaulting to its highest version.

    Args:
        name: The prompt's base name, without the ``.vN.md`` suffix
            (e.g. ``"claim_extraction_system"``).
        version: A specific version to load; if None, the highest on disk is used.

    Returns:
        The requested :class:`Prompt`, with surrounding whitespace stripped.

    Raises:
        KeyError: If no prompt by that name exists, or the requested version does not.
    """
    versions = _index().get(name)
    if not versions:
        available = ", ".join(sorted(_index())) or "none"
        raise KeyError(f"No prompt named {name!r} (available: {available}).")
    resolved = max(versions) if version is None else version
    if resolved not in versions:
        have = ", ".join(f"v{v}" for v in sorted(versions))
        raise KeyError(f"Prompt {name!r} has no version {resolved} (have: {have}).")
    return Prompt(name=name, version=resolved, text=versions[resolved].strip())
