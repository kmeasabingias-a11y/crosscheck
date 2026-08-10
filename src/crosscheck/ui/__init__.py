"""Logic behind the Streamlit demo (spec §7.7).

Everything here is deliberately **free of Streamlit imports**. The demo's entry point,
``ui/streamlit_app.py``, owns every widget call; this package owns the decisions it makes —
which mode to run in, how to talk to the service, how a passage should be split for
highlighting. That boundary is what lets the logic be type-checked under ``mypy --strict`` and
unit-tested without a Streamlit runtime, the same reasoning that moved the container warm-up out
of ``scripts/`` and into the package (D48).
"""
