"""Retrieval layer: turn stored claims into cross-document candidate pairs (spec §7.3).

:mod:`candidate_gen` runs the pluggable retrieval strategy (hybrid BM25+dense by default,
dense-only for the ablation) over the claim store to produce deduplicated
:class:`~crosscheck.models.Pair` candidates; the reranker (next file) narrows them with a
cross-encoder before the detection stages.
"""
