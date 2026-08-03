"""The bridge — the join between the client_boq review and the procurement routing fork.

Belongs to neither product. It reads ``client_boq`` (imports only, never writes) and drives the
existing procurement engine (``pipeline.routing``, ``stage_01_ingest``) unchanged. See CONTEXT.md.
"""
