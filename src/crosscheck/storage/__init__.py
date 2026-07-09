"""Storage layer: the Qdrant claim store that is CrossCheck's system of record (spec §7.2).

:mod:`qdrant_client` owns the connection and collection lifecycle, :mod:`embeddings` turns
claim text into the dense and sparse vectors the collection holds, and :mod:`claim_repo`
exposes the CRUD + hybrid-retrieval API (:class:`~crosscheck.storage.claim_repo.ClaimRepo`)
that the rest of the pipeline builds on.
"""
