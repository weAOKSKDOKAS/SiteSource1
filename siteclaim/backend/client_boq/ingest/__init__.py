"""INGEST — the front door of the client_boq workflow (stage s00, before REVIEW).

A real tender does not arrive as a tidy set of small files; it arrives as one 400-page
binder. This package turns that binder into an addressable structure BEFORE any review
happens: inspect it deterministically, let the model propose a split manifest, put that
manifest in front of a human, then cut the pages with code and interpret each part.

The order matters and is the whole point:

    upload -> inspect (Det) -> plan manifest (AI) -> GATE -> split (Det) -> interpret (AI)

The LLM proposes the cut; deterministic code validates and performs it. That is the same
principle the rest of the module runs on, applied to document structure.
"""
