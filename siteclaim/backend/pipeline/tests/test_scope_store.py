"""Per-tender canonical scope persistence (leveling fix, Commit 1) — the artifact the inbound
reply loop reads to route returned lines to their true SoR section."""

from pipeline.scope_store import load_scope, save_scope
from pipeline.workspace import Workspace
from schemas.models import ScopePackages, SorItem, TradeWorkPackage


def _scope() -> ScopePackages:
    return ScopePackages(
        project_name="GE/2026/14",
        packages=[
            TradeWorkPackage(
                trade="ground_investigation", scope_summary="GI",
                sor_items=[
                    SorItem(item_ref="G4", description="Trial pit", section="G"),
                    SorItem(item_ref="H12", description="Field vane test", section="H"),
                    SorItem(item_ref="J1", description="Standpipe", section="J"),
                ],
            )
        ],
    )


def test_scope_round_trips_through_the_workspace(tmp_path):
    ws = Workspace(tmp_path)
    save_scope(ws, "GE/2026/14", _scope())
    loaded = load_scope(ws, "GE/2026/14")
    assert loaded is not None
    assert loaded.project_name == "GE/2026/14"
    refs = [it.item_ref for pkg in loaded.packages for it in pkg.sor_items]
    assert refs == ["G4", "H12", "J1"]
    assert loaded.packages[0].sor_items[1].section == "H"


def test_missing_scope_loads_as_none(tmp_path):
    assert load_scope(Workspace(tmp_path), "no-such-tender") is None  # older tender -> ref-trade path
