"""Benchmark estimator — Layer-2/pipeline helpers (tender snapshot, actuals xlsx, matcher).

Deterministic-first: the xlsx paths use openpyxl and never call a model; the priced-tender
PDF path reuses the existing chunked reply parser. See
``docs/PRODUCT_ARCHITECTURE_benchmark_estimator.md``.
"""
