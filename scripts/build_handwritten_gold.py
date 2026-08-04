"""Build the gold labels for the hand-written validation set (spec v2 §9.1).

The corpus in ``benchmarks/handwritten/corpus/`` is authored by hand; this script turns the
contradictions planted in it into a :class:`~crosscheck.evaluation.gold.GoldSet` that the metrics
module can score alongside the injected synthetic benchmark.

**Why a script rather than a hand-written JSON file.** A gold label has to carry a ``section_id``,
and a section id is a content hash of the document text — it changes the moment a sentence is
edited. Transcribing 28 pairs of those by hand is exactly the kind of copying that has already
broken this project once (D31). So the pairs below are written the way a human can check them —
file name, heading, and the verbatim sentence — and the ids and character spans are *resolved* by
parsing the corpus with the same parser the pipeline uses. Edit a document, re-run this, and the
gold set follows.

Every quote is located with :func:`crosscheck.text.locate_quote`, so the hard line wraps in the
Markdown source do not have to be reproduced in the spec. A quote that cannot be found is a hard
error: a gold label pointing at text that is not there would silently become an unreachable
false negative.

The script also refuses to write a gold set whose pairs collide at section level. Matching is on
the unordered pair of sections (D36), so two contradictions spanning the same two sections cannot
be told apart and one would score as already-found.

Run from anywhere::

    uv run python scripts/build_handwritten_gold.py
"""

from pathlib import Path
from typing import NamedTuple

from crosscheck.detection.taxonomy import ContradictionType
from crosscheck.evaluation.gold import (
    GoldPair,
    GoldSet,
    GoldSide,
    duplicate_section_keys,
    gold_id,
    write_gold_set,
)
from crosscheck.ingestion.parsers import parse
from crosscheck.models import Document
from crosscheck.text import locate_quote

_ROOT = Path(__file__).resolve().parent.parent / "benchmarks" / "handwritten"
_CORPUS_DIR = _ROOT / "corpus"
_GOLD_PATH = _ROOT / "gold.json"

#: The judge these labels were authored against, recorded for the §9.1 provenance block.
_JUDGE_AT_AUTHORING = "claude-haiku-4-5"

_NOTICE = "01_privacy_notice.md"
_DPA = "02_data_processing_addendum.md"
_STANDARD = "03_data_handling_standard.md"
_OVERVIEW = "04_trust_and_security_overview.md"
_RUNBOOK = "05_incident_response_runbook.md"


class _SideSpec(NamedTuple):
    """One side of a planted contradiction, as a human writes it down."""

    document: str
    heading: str
    quote: str


class _PairSpec(NamedTuple):
    """A planted contradiction and why it is one."""

    contradiction_type: ContradictionType
    a: _SideSpec
    b: _SideSpec
    notes: str


# The planted contradictions, grouped by the subject they drift on. Each is a genuine conflict of
# substance stated in two registers that share as little vocabulary as the subject allows — that
# combination is the whole point of this set (§9.1), and it is what the injected benchmark cannot
# produce.
_PAIRS: tuple[_PairSpec, ...] = (
    # --- Retention and deletion -------------------------------------------------------------
    _PairSpec(
        ContradictionType.NUMERICAL_MISMATCH,
        _SideSpec(
            _NOTICE,
            "3. Where we keep",
            "We keep the records we hold about your account for two years after you close it",
        ),
        _SideSpec(
            _DPA,
            "4. Transfers",
            "shall complete that deletion within 30 days of termination",
        ),
        "Closing an account is termination, and account records are Personal Data, so two "
        "years and 30 days cannot both hold.",
    ),
    _PairSpec(
        ContradictionType.NUMERICAL_MISMATCH,
        _SideSpec(
            _DPA,
            "4. Transfers",
            "shall complete that deletion within 30 days of termination",
        ),
        _SideSpec(
            _STANDARD,
            "2. Storage",
            "The retention lifecycle job purges objects belonging to terminated tenants on a "
            "90-day cadence.",
        ),
        "The contractual deadline is 30 days; the job that would meet it runs on a 90-day "
        "cycle, so it cannot.",
    ),
    _PairSpec(
        ContradictionType.DIRECT_NEGATION,
        _SideSpec(
            _OVERVIEW,
            "4. Deletion",
            "Deletion is immediate and irreversible: when you delete a record it is gone from "
            "our systems at once, with no waiting period and no hidden copy.",
        ),
        _SideSpec(
            _STANDARD,
            "2. Storage",
            "Deleted objects remain recoverable from the soft-delete tier for 35 days before "
            "the compaction job removes them permanently.",
        ),
        "'No waiting period and no hidden copy' is precisely denied by a 35-day recoverable "
        "soft-delete tier.",
    ),
    _PairSpec(
        ContradictionType.DIRECT_NEGATION,
        _SideSpec(
            _NOTICE,
            "3. Where we keep",
            "Nothing we hold about you is kept indefinitely; every category of information we "
            "collect has an end date",
        ),
        _SideSpec(
            _STANDARD,
            "1. Purpose",
            "Buckets provisioned before the Helios migration are exempt from the retention "
            "lifecycle job and retain every object version indefinitely",
        ),
        "The exemption is buried in a legacy-estate paragraph, which is where real corpora "
        "hide the thing that contradicts the public promise.",
    ),
    _PairSpec(
        ContradictionType.NUMERICAL_MISMATCH,
        _SideSpec(
            _NOTICE,
            "3. Where we keep",
            "Support tickets and their attachments are deleted after 12 months.",
        ),
        _SideSpec(
            _STANDARD,
            "2. Storage",
            "The support archive, which holds ticket bodies and their attachments, is retained "
            "for seven years to satisfy our insurers.",
        ),
        "Same objects, twelve months against seven years. Only the phrase 'attachments' is "
        "shared; 'support archive' never appears in the notice.",
    ),
    # --- Sub-processors and vendors ---------------------------------------------------------
    _PairSpec(
        ContradictionType.NUMERICAL_MISMATCH,
        _SideSpec(
            _DPA,
            "2. Roles",
            "Vantis shall give Customer at least 30 days' prior written notice before "
            "appointing a new Sub-processor",
        ),
        _SideSpec(
            _OVERVIEW,
            "3. Residency",
            "we publish new vendor additions to the trust centre two weeks before they go live",
        ),
        "Two weeks is less than the 30 days the contract requires. 'Sub-processor' and "
        "'vendor addition' are the same thing under two names.",
    ),
    _PairSpec(
        ContradictionType.DIRECT_NEGATION,
        _SideSpec(
            _NOTICE,
            "2. What we do",
            "We do not share your information with any third party for their own purposes.",
        ),
        _SideSpec(
            _STANDARD,
            "4. Logging",
            "Aggregated query telemetry is forwarded to our analytics vendor, who may use it "
            "to improve their own models.",
        ),
        "'For their own purposes' is exactly what 'to improve their own models' describes.",
    ),
    _PairSpec(
        ContradictionType.OBLIGATION_REVERSAL,
        _SideSpec(
            _DPA,
            "2. Roles",
            "Vantis shall not onboard that Sub-processor for so long as the objection remains "
            "outstanding",
        ),
        _SideSpec(
            _STANDARD,
            "4. Logging",
            "customer objections are recorded in the vendor register but do not block go-live",
        ),
        "The contract makes an objection blocking; the engineering standard makes it advisory.",
    ),
    _PairSpec(
        ContradictionType.OBLIGATION_REVERSAL,
        _SideSpec(
            _DPA,
            "2. Roles",
            "Vantis shall Process Personal Data only on documented instructions from Customer",
        ),
        _SideSpec(
            _STANDARD,
            "3. Access",
            "Platform engineering may query tenant datasets directly, without a customer "
            "ticket, when investigating a performance regression.",
        ),
        "Querying without a ticket is processing without a documented instruction.",
    ),
    # --- Residency and jurisdiction ---------------------------------------------------------
    _PairSpec(
        ContradictionType.SCOPE_JURISDICTION,
        _SideSpec(
            _OVERVIEW,
            "3. Residency",
            "Choose EU residency and your data never leaves the European Union",
        ),
        _SideSpec(
            _STANDARD,
            "2. Storage",
            "Backup snapshots from all regions replicate nightly to the us-east-2 "
            "disaster-recovery bucket",
        ),
        "The overview closes the loophole explicitly ('not your backups'), and the standard "
        "opens it for every region.",
    ),
    _PairSpec(
        ContradictionType.SCOPE_JURISDICTION,
        _SideSpec(
            _DPA,
            "4. Transfers",
            "Vantis shall not transfer Personal Data outside the European Economic Area, nor "
            "permit access to it from outside the European Economic Area",
        ),
        _SideSpec(
            _NOTICE,
            "2. What we do",
            "Our support team, which is based in Manila and Bangalore, may open your workspace "
            "when that is the only way to resolve a ticket you have raised.",
        ),
        "Support access from a third country is the access the DPA forbids. Neither side uses "
        "the other's vocabulary.",
    ),
    _PairSpec(
        ContradictionType.SCOPE_JURISDICTION,
        _SideSpec(
            _NOTICE,
            "3. Where we keep",
            "Your information is stored in the region you select when you sign up",
        ),
        _SideSpec(
            _STANDARD,
            "4. Logging",
            "Query logs, which include the full text of submitted queries and any literal "
            "values they contain, are written to the central log estate in eu-west-1 "
            "regardless of the tenant's region.",
        ),
        "Query literals are the customer's information, so a non-EU tenant's data leaves its "
        "selected region.",
    ),
    # --- Encryption -------------------------------------------------------------------------
    _PairSpec(
        ContradictionType.DIRECT_NEGATION,
        _SideSpec(
            _OVERVIEW,
            "2. Encryption",
            "Every byte we hold is encrypted at rest with keys you control",
        ),
        _SideSpec(
            _STANDARD,
            "3. Access",
            "Customer-managed keys are available on the Enterprise plan; every other tenant is "
            "served by platform-managed keys held in the regional key service.",
        ),
        "'Keys you control' is true for one plan, and the overview claims it universally.",
    ),
    _PairSpec(
        ContradictionType.DIRECT_NEGATION,
        _SideSpec(
            _OVERVIEW,
            "2. Encryption",
            "there is no unencrypted path into Vantis, and there never has been",
        ),
        _SideSpec(
            _STANDARD,
            "1. Purpose",
            "The legacy ingest endpoint on the Atlas fabric accepts unencrypted connections "
            "from allow-listed source ranges",
        ),
        "An absolute claim against a named exception. The retrieval problem is that the two "
        "sentences share almost no words beyond 'unencrypted'.",
    ),
    # --- Incidents --------------------------------------------------------------------------
    _PairSpec(
        ContradictionType.NUMERICAL_MISMATCH,
        _SideSpec(
            _DPA,
            "3. Security",
            "Vantis shall notify Customer of a Security Incident without undue delay and in "
            "any event within 24 hours of becoming aware of it",
        ),
        _SideSpec(
            _RUNBOOK,
            "3. Notification",
            "Customer notification is sent within 72 hours of an incident being declared",
        ),
        "The runbook that implements the obligation allows three times the contractual window.",
    ),
    _PairSpec(
        ContradictionType.NUMERICAL_MISMATCH,
        _SideSpec(
            _OVERVIEW,
            "1. Our approach",
            "we commit to notifying regulators within 24 hours of any confirmed breach",
        ),
        _SideSpec(
            _RUNBOOK,
            "3. Notification",
            "Regulator notification is prepared within 72 hours where the incident is reportable",
        ),
        "Same obligation, sales voice against operational voice, 24 hours against 72.",
    ),
    _PairSpec(
        ContradictionType.OBLIGATION_REVERSAL,
        _SideSpec(
            _OVERVIEW,
            "4. Deletion",
            "every security event, however minor, is disclosed to the affected customers "
            "rather than triaged away quietly",
        ),
        _SideSpec(
            _RUNBOOK,
            "3. Notification",
            "Severity 3 and 4 incidents are recorded in the incident register and are not "
            "communicated to customers.",
        ),
        "'However minor' is contradicted by an explicit floor on what gets communicated.",
    ),
    _PairSpec(
        ContradictionType.OBLIGATION_REVERSAL,
        _SideSpec(
            _DPA,
            "3. Security",
            "Customer may audit Vantis' processing facilities and records once per calendar "
            "year, on 30 days' prior written notice",
        ),
        _SideSpec(
            _OVERVIEW,
            "1. Our approach",
            "In place of customer audits we provide our SOC 2 report; on-site inspection of "
            "our facilities is not offered",
        ),
        "A contractual right withdrawn by a policy document.",
    ),
    # --- Access control ---------------------------------------------------------------------
    _PairSpec(
        ContradictionType.DIRECT_NEGATION,
        _SideSpec(
            _NOTICE,
            "2. What we do",
            "Only you can see the contents of your workspace.",
        ),
        _SideSpec(
            _STANDARD,
            "3. Access",
            "Support engineers may assume a tenant session through the break-glass console "
            "with a recorded justification",
        ),
        "An exclusive-access promise against a documented internal path to the same data.",
    ),
    _PairSpec(
        ContradictionType.NUMERICAL_MISMATCH,
        _SideSpec(
            _STANDARD,
            "3. Access",
            "A break-glass grant expires automatically after 8 hours and cannot be extended in "
            "place.",
        ),
        _SideSpec(
            _RUNBOOK,
            "4. Evidence",
            "Investigators retain elevated access for the duration of the incident and for 14 "
            "days afterwards",
        ),
        "Fourteen days of retained elevated access cannot coexist with a non-extendable "
        "eight-hour grant.",
    ),
    _PairSpec(
        ContradictionType.OBLIGATION_REVERSAL,
        _SideSpec(
            _STANDARD,
            "1. Purpose",
            "Fields classified PII-2 or above must not be written to application logs under "
            "any circumstances.",
        ),
        _SideSpec(
            _RUNBOOK,
            "2. Detection",
            "Triage begins by searching the request logs for the affected user's email "
            "address, which is recorded on every authenticated request",
        ),
        "The runbook depends on the logs containing what the standard forbids them to "
        "contain. Neither sentence mentions the other's key term.",
    ),
    # --- Data subject rights ----------------------------------------------------------------
    _PairSpec(
        ContradictionType.NUMERICAL_MISMATCH,
        _SideSpec(
            _NOTICE,
            "4. Your choices",
            "We answer requests about your information within ten days.",
        ),
        _SideSpec(
            _DPA,
            "4. Transfers",
            "Vantis shall assist Customer in responding to a request from a data subject to "
            "exercise their rights within ten Business Days of receiving the request",
        ),
        "The defined-term trap: 'Business Day' is defined in DPA section 1 as excluding "
        "weekends and Irish public holidays, so ten Business Days always exceeds ten days. "
        "Resolving it needs a third section, which is why real drift like this survives "
        "review.",
    ),
    _PairSpec(
        ContradictionType.DIRECT_NEGATION,
        _SideSpec(
            _NOTICE,
            "4. Your choices",
            "You can download a copy of everything we hold about you at any time from the "
            "account page",
        ),
        _SideSpec(
            _STANDARD,
            "2. Storage",
            "Neither the support archive nor the query-log estate is exposed through the "
            "tenant export API.",
        ),
        "'Everything' against two named exclusions.",
    ),
    # --- Versioning and supersession --------------------------------------------------------
    _PairSpec(
        ContradictionType.TEMPORAL_CONFLICT,
        _SideSpec(
            _NOTICE,
            "1. About this notice",
            "This notice, version 3.0, replaces the version we published in March 2024 and "
            "takes effect on 1 September 2025.",
        ),
        _SideSpec(
            _OVERVIEW,
            "1. Our approach",
            "Our practices are described in our Privacy Notice v2.1 (March 2024), which "
            "remains the authoritative statement of how we handle customer information",
        ),
        "A superseded version is asserted to be authoritative while its replacement is in "
        "force — the canonical stale-document conflict of §6.",
    ),
    _PairSpec(
        ContradictionType.TEMPORAL_CONFLICT,
        _SideSpec(
            _STANDARD,
            "1. Purpose",
            "The Atlas fabric was retired to new tenants on 1 January 2025 and now carries "
            "only the accounts migrated before that date.",
        ),
        _SideSpec(
            _OVERVIEW,
            "3. Residency",
            "New customers are onboarded onto our Atlas storage fabric, which underpins the "
            "residency guarantees described above.",
        ),
        "The overview still sells a fabric that stopped taking new tenants.",
    ),
    _PairSpec(
        ContradictionType.TEMPORAL_CONFLICT,
        _SideSpec(
            _RUNBOOK,
            "1. Scope",
            "This runbook, version 4, replaces the Security Incident Playbook version 2, which "
            "is withdrawn and must not be used.",
        ),
        _SideSpec(
            _OVERVIEW,
            "4. Deletion",
            "Our incident response follows the Security Incident Playbook, which is reviewed "
            "annually and is currently at version 2",
        ),
        "A withdrawn document is named as the live procedure.",
    ),
    _PairSpec(
        ContradictionType.TEMPORAL_CONFLICT,
        _SideSpec(
            _NOTICE,
            "4. Your choices",
            "As of version 3.0 we no longer embed third-party analytics scripts on the Vantis "
            "console",
        ),
        _SideSpec(
            _STANDARD,
            "4. Logging",
            "The console loads the Segment and FullStory scripts on all authenticated pages.",
        ),
        "A discontinued practice that the engineering standard still describes as current. "
        "The vendor names never appear in the notice, so lexical overlap is near zero.",
    ),
    # --- Availability -----------------------------------------------------------------------
    _PairSpec(
        ContradictionType.NUMERICAL_MISMATCH,
        _SideSpec(
            _OVERVIEW,
            "3. Residency",
            "We back the platform with a 99.99% availability commitment, measured monthly and "
            "written into the service level agreement.",
        ),
        _SideSpec(
            _RUNBOOK,
            "1. Scope",
            "The platform availability objective is 99.9% measured monthly",
        ),
        "One nine apart, same metric and same measurement window.",
    ),
)


def _find_section(document: Document, heading_prefix: str) -> tuple[str, str]:
    """Return the ``(section_id, text)`` of the one section whose heading starts as given.

    Args:
        document: The parsed corpus document.
        heading_prefix: Enough of the heading to identify it uniquely.

    Returns:
        The section's id and body text.

    Raises:
        ValueError: If no section matches, or more than one does.
    """
    matched = [
        section
        for section in document.sections
        if section.heading and section.heading.startswith(heading_prefix)
    ]
    if len(matched) != 1:
        headings = [section.heading for section in document.sections]
        raise ValueError(
            f"{heading_prefix!r} matched {len(matched)} section(s) in "
            f"{document.source_path.name}; headings are {headings}"
        )
    return matched[0].section_id, matched[0].text


def _build_side(documents: dict[str, Document], spec: _SideSpec) -> GoldSide:
    """Resolve one spec side into a :class:`GoldSide` with real ids and offsets.

    Args:
        documents: Parsed corpus, keyed by file name.
        spec: The hand-written side.

    Returns:
        The resolved gold side.

    Raises:
        ValueError: If the document is missing or the quote is not in the named section.
    """
    if spec.document not in documents:
        raise ValueError(f"{spec.document} is not in {_CORPUS_DIR}")
    document = documents[spec.document]
    identifier, text = _find_section(document, spec.heading)
    span = locate_quote(text, spec.quote)
    if span is None:
        raise ValueError(f"quote not found in {spec.document} / {spec.heading!r}: {spec.quote!r}")
    return GoldSide(
        document=spec.document,
        section_id=identifier,
        section_heading=_find_heading(document, identifier),
        text=text[span[0] : span[1]],
        evidence_quote=text[span[0] : span[1]],
        char_span=span,
    )


def _find_heading(document: Document, identifier: str) -> str | None:
    """Return the heading of the section with the given id."""
    return next(
        (section.heading for section in document.sections if section.section_id == identifier),
        None,
    )


def build_gold_set(corpus_dir: Path) -> GoldSet:
    """Resolve every planted contradiction into a gold set.

    Args:
        corpus_dir: The hand-written corpus directory.

    Returns:
        The gold set, ready to write.

    Raises:
        ValueError: If a quote cannot be located, or two pairs collide at section level.
    """
    documents = {path.name: parse(path) for path in sorted(corpus_dir.glob("*.md"))}
    pairs: list[GoldPair] = []
    for spec in _PAIRS:
        side_a = _build_side(documents, spec.a)
        side_b = _build_side(documents, spec.b)
        if side_a.document == side_b.document:
            raise ValueError(
                f"both sides of a pair are in {side_a.document}; retrieval only considers "
                "cross-document candidates, so a same-document pair can never be found"
            )
        pairs.append(
            GoldPair(
                pair_id=gold_id(side_a, side_b),
                contradiction_type=spec.contradiction_type,
                a=side_a,
                b=side_b,
                origin="handwritten",
                notes=spec.notes,
            )
        )
    collisions = duplicate_section_keys(pairs)
    if collisions:
        raise ValueError(
            f"{len(collisions)} section-level collision(s): two pairs span the same two "
            f"sections and cannot be told apart when scoring — {collisions}"
        )
    return GoldSet(
        name="vantis-handwritten",
        version="v1",
        corpus_dir="corpus",
        origin="handwritten",
        generator_model=None,
        judge_model_at_authoring=_JUDGE_AT_AUTHORING,
        pairs=pairs,
    )


def main() -> None:
    """Rebuild ``benchmarks/handwritten/gold.json`` from the corpus and the specs above."""
    gold = build_gold_set(_CORPUS_DIR)
    write_gold_set(gold, _GOLD_PATH)
    print(f"wrote {_GOLD_PATH} with {len(gold.pairs)} pair(s)")
    for name, count in gold.type_counts.items():
        print(f"  {name}: {count}")


if __name__ == "__main__":
    main()
