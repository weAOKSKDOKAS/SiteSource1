"""Prompt E — the CIC register load + fuse, and the honest coverage composition.

Two layers of test:
* pure loader units (``register_loader``) — parsing, taxonomy mapping (never crashing on
  an unmapped specialty), and the merge/overlay/drop semantics, on synthetic + real data;
* a built-DB integration (a hermetic demo/live build) — the register population, the
  coverage composition summing to the total, a curated flagged firm fused onto its register
  row, the register fields flowing through ``/firms``, and the shortlist staying assessable-only.

Pure DB work — runs offline under the DEMO autouse fixture.
"""

import pytest

from db import register_loader as rl
from db import seed, store


# ---------------------------------------------------------------------------
# Loader units (pure, no DB)
# ---------------------------------------------------------------------------
def test_parse_trades_maps_group_and_specialty():
    raw = "01.02 Foundation and Piling :: Bored piles | 01.09 General Civil Works :: Road drainage and sewer"
    registered, canon = rl.parse_trades(raw)
    assert registered[0] == {"code": "01.02", "group": "Foundation and Piling", "specialty": "Bored piles"}
    assert "foundation_substructure" in canon
    assert "drainage_works" in canon            # a drainage specialty gets its own trade
    assert "ground_investigation" not in canon  # a bored-pile firm is not a GI firm


def test_ground_investigation_expands_to_field_work():
    _registered, canon = rl.parse_trades("01.09 General Civil Works :: Ground investigation")
    assert {"ground_investigation", "field_testing", "field_installations"} <= set(canon)


def test_unmapped_specialty_never_crashes_falls_back():
    # An unknown group/specialty must not raise; it falls back through the taxonomy
    # normaliser and finally to a general-civil default.
    got = rl._canonical_for("Totally Unknown Group", "Some Novel Specialty")
    assert got and got <= {"external_works"} or got  # non-empty, no exception


def test_load_csv_register_reads_the_real_register():
    firms = rl.load_csv_register(seed.CSV_REGISTER_PATH)
    assert 1300 <= len(firms) <= 1400          # ~1,365 after de-duping by BR No.
    assert all(f["provenance"] == "public_register" for f in firms)
    assert all(f["firm_id"] and f["name_en"] for f in firms)
    # BR No. de-dupe: no two register rows share a non-empty BR
    brs = [f["br_no"] for f in firms if f["br_no"]]
    assert len(brs) == len(set(brs))


def test_merge_fuses_flagged_keeps_overlay_and_drops_plain():
    register = [{
        "firm_id": "R1", "name_en": "Alpha Ltd", "name_zh": None, "trades": ["electrical"],
        "registered_grade": "CIC Registered Subcontractor", "value_band": None,
        "registers": ["CIC Registered Subcontractors Scheme"], "registered_trades": [],
        "description": "d", "enquiry_email": "a@x.hk", "br_no": "111", "address": "",
        "phone": "", "fax": "", "reg_date": "", "expiry_date": "", "provenance": "public_register",
        **rl._empty_extras(),
    }]
    curated = [
        {"firm_id": "alpha-x", "name_en": "Alpha Ltd", "trades": ["electrical"],
         "public_flags": [{"signal_type": "debarment", "label": "z"}]},   # matches R1 -> merged
        {"firm_id": "beta-flag", "name_en": "Beta Ltd", "trades": ["fire_services"],
         "public_flags": [{"signal_type": "winding_up", "label": "z"}]},  # no match, flagged -> overlay
        {"firm_id": "gamma-plain", "name_en": "Gamma Ltd", "trades": ["structural"]},  # no match, plain -> dropped
    ]
    by_id = {f["firm_id"]: f for f in rl.merge_register(register, curated, {})}
    # merged: kept its curated id + flags, gained the register's BR/e-mail
    assert by_id["alpha-x"]["br_no"] == "111" and by_id["alpha-x"]["public_flags"]
    assert "R1" not in by_id                                  # the register row was consumed
    assert by_id["beta-flag"]["provenance"] == "public_register" and not by_id["beta-flag"]["br_no"]  # overlay
    assert "gamma-plain" not in by_id                         # plain curated row superseded by the register


def test_illustrative_firm_keeps_closeout_and_is_illustrative():
    rec = {"firm_id": "F-EL-99", "name_en": "Demo Sparks Ltd", "trades": ["electrical"]}
    eos = {"report_text": ["strong closeout record"], "closeout_summary": "clean"}
    out = rl.illustrative_firm(rec, eos)
    assert out["provenance"] == "illustrative"
    assert out["report_text"] == ["strong closeout record"] and out["closeout_summary"] == "clean"


# ---------------------------------------------------------------------------
# Built-DB integration (hermetic)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def demo_conn(tmp_path_factory):
    path = tmp_path_factory.mktemp("reg-demo") / "demo.db"
    seed.build_database(path, profile="demo")
    conn = store.get_connection(path)
    yield conn
    conn.close()


def test_seed_loads_the_full_register_matching_coverage(demo_conn):
    real = demo_conn.execute("SELECT COUNT(*) AS n FROM firms WHERE provenance='public_register'").fetchone()["n"]
    assert 1350 <= real <= 1450                                   # ~1,407 real firms
    assert real == store.coverage(demo_conn)["total_firms"]       # coverage counts exactly the real pool


def test_coverage_composition_sums_and_is_consistent(demo_conn):
    cov = store.coverage(demo_conn)
    # the figure is a composition, never a bare total
    assert cov["register_count"] + cov["overlay_count"] == cov["total_firms"]
    assert cov["register_count"] > cov["overlay_count"] > 0        # register dominates, overlay real
    assert cov["flagged_count"] == cov["flagged_firms"] == 46
    assert cov["registers"] == len(cov["flag_sources"]) >= 1
    # register_count is exactly the real firms carrying a BR No.
    with_br = demo_conn.execute(
        "SELECT COUNT(*) AS n FROM firms WHERE provenance='public_register' AND br_number != ''"
    ).fetchone()["n"]
    assert cov["register_count"] == with_br


def test_a_curated_flagged_firm_is_fused_onto_its_register_row(demo_conn):
    # A merged curated firm keeps its curated (slug) id and flags but gains the register's BR
    # No. — a pure register row uses an R###### id, an overlay row has no BR, so this isolates
    # the fusion.
    fused = demo_conn.execute(
        "SELECT DISTINCT f.firm_id FROM firms f JOIN public_flags pf ON pf.firm_id = f.firm_id "
        "WHERE f.provenance='public_register' AND f.br_number != '' AND f.firm_id NOT GLOB 'R[0-9]*'"
    ).fetchall()
    assert fused  # at least one enforcement-flagged curated firm merged onto its register row


def test_illustrative_firms_are_the_assessable_shortlist_subset(demo_conn):
    # The shortlist draws only from firms with an EOS closeout record — in SiteSource those are
    # the 16 illustrative firms, never the register/overlay rows (which carry no closeout).
    assessable = store.eos_firm_ids(demo_conn)
    assert assessable and all(fid.startswith("F-") for fid in assessable)
    for f in store.shortlistable_firms_for_trade(demo_conn, "electrical"):
        assert f.firm_id.startswith("F-")


def test_firms_page_carries_register_fields_real_only(demo_conn):
    page, total = store.firms_page(demo_conn, limit=100, offset=0)
    assert total == store.coverage(demo_conn)["total_firms"]      # real-provenance only, no illustrative leak
    assert not any(f.firm_id.startswith("F-") for f in page)
    # a register firm surfaces its register contact/registration fields
    assert any(f.enquiry_email and f.br_no and f.registered_trades for f in page)
