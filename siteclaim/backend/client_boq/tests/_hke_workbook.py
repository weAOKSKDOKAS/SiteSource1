"""The reference costing workbook, transcribed — one drilling job, priced by a real estimator.

Source: `FINAL Costing - HKE Exercise.xlsx`, three sheets (`Assumptions or Note` → `Costing` → `BOQ`).
It prices a single site: 60 m of soil and 72 m of rock, one rig, one crew. Every figure below is read
off that workbook, not invented here.

**This is the regression fixture for the whole costing design.** With one hole group and one set of
conditions, our engine must reproduce all ten of its rates to the cent. If it does not, the model is
wrong — not the spreadsheet.

The workbook itself is not committed: it is the user's own commercial working. What is committed is
this transcription of its structure and its inputs, which is what the tests need.
"""

from __future__ import annotations

from client_boq.boq.allocate import DAYS_ROCK, DAYS_SOIL, RateRecipe, RecipeTerm
from client_boq.boq.duration import simulate
from client_boq.boq.resources import (
    CLASS_CONSUMABLE,
    CLASS_EQUIPMENT,
    CLASS_LABOUR,
    CLASS_OTHER,
    CLASS_PLANT,
    CLASS_SUBCONTRACT,
    CLASS_SUPERVISION,
    CLASS_TRANSPORT,
    DRIVER_DRILLING,
    DRIVER_ON_SITE,
    MaterialGeometry,
    ResourceSheet,
    SheetLine,
    material_lines,
)

# --- the job -----------------------------------------------------------------------------------
SOIL_M = 60.0
ROCK_M = 72.0
SOIL_OUTPUT = 20.0      # m/day, before decay
ROCK_OUTPUT = 10.0
DECAY = 0.05            # per 20 m of depth
MARKUP_PCT = 33.0
MOB_DAYS = 4.0          # "1 day for transporting plant and equipment, 1 day to install/dismantle …"

# --- what the workbook computes, to check against ------------------------------------------------
EXPECT_TOTAL_DAYS = 11
EXPECT_SOIL_DAYS = 3.110803324099723
EXPECT_ROCK_CHARGED = 7.889196675900277
EXPECT_SOIL_COMPLETE_DAY = 4
EXPECT_ROCK_COMPLETE_DAY = 11

EXPECT_DAILY_COST = 12986.60        # one day of the drilling spread, coefficients applied
EXPECT_COST_TOTAL = 263457.1310531449
EXPECT_SELLING_TOTAL = 350397.9843006828

# The ten BOQ rates, as the workbook computes them (before the estimator's rounding pass).
EXPECT_RATES = {
    "A": 47349.596,             # Mobilise on Land
    "B": 43189.356,             # Move on Land
    "C": 895.5058122807018,     # Vertically downwards (Soil), per m
    "D": 1892.5501286549709,    # Vertically downwards (Rock), per m
    "E": 26473.824300682758,    # Backfilling Drillholes
    "F": 3990.0,                # Providing core box
    "G": 133.0,                 # Mazier Samples, per nr
    "H": 162.55555555555554,    # H-Size, N-Size rock core, per nr
    "I": 11783.8,               # Soil Tests
    "J": 11923.45,              # Rock Tests
}

# And what he rounded them to, holding the total (350,398 → 350,600).
EXPECT_ADJUSTED = {
    "A": 48000.0, "B": 43000.0, "C": 900.0, "D": 1900.0, "E": 26000.0,
    "F": 4000.0, "G": 150.0, "H": 150.0, "I": 11500.0, "J": 12000.0,
}

# The resources that stand on site each drilling day. Their sum is EXPECT_DAILY_COST, and it is what
# both drilling rates are built on.
DAILY_KEYS = [
    "rig", "pump", "sed_tanks", "toolbox", "drill_rig", "casing", "racks", "diesel_tank",
    "bentonite_storage", "storage",              # plant + equipment, each at coefficient 1.23
    "driller", "workers", "pm", "site_engineer", "geologist", "foreman",
]
PLANT_EQUIP_KEYS = DAILY_KEYS[:10]


def build_sheet(label: str = "HKE") -> ResourceSheet:
    """The `Costing` sheet, line for line."""
    duration = simulate(SOIL_M, ROCK_M, soil_output=SOIL_OUTPUT, rock_output=ROCK_OUTPUT, decay=DECAY)
    geometry = MaterialGeometry()

    def on_site(key, label_, cls, rate, coefficient=1.23, note=""):
        return SheetLine(key=key, label=label_, resource_class=cls, coefficient=coefficient,
                         driver=DRIVER_ON_SITE, unit="day", rate=rate, note=note)

    lines = [
        on_site("rig", "Rig", CLASS_PLANT, 500),
        on_site("pump", "Pump", CLASS_PLANT, 200, note="Water pump and hydraulic pump"),
        on_site("sed_tanks", "Sedimentation tanks", CLASS_PLANT, 100),
        on_site("toolbox", "ToolBox", CLASS_EQUIPMENT, 50),
        on_site("drill_rig", "Drill rig", CLASS_EQUIPMENT, 300),
        on_site("casing", "Casing", CLASS_EQUIPMENT, 100),
        on_site("racks", "Racks", CLASS_EQUIPMENT, 20),
        on_site("diesel_tank", "Diesel tank", CLASS_EQUIPMENT, 50),
        on_site("bentonite_storage", "Bentonite storage", CLASS_EQUIPMENT, 50),
        on_site("storage", "Storage", CLASS_EQUIPMENT, 50),

        SheetLine(key="driller", label="Driller", resource_class=CLASS_LABOUR, coefficient=1,
                  driver=DRIVER_ON_SITE, unit="day", rate=2000),
        SheetLine(key="workers", label="Workers", resource_class=CLASS_LABOUR, coefficient=2,
                  driver=DRIVER_ON_SITE, unit="day", rate=1500, note="Two on the rig."),

        SheetLine(key="pm", label="Project Manager", resource_class=CLASS_SUPERVISION,
                  coefficient=0.33, driver=DRIVER_ON_SITE, unit="day", rate=3000,
                  note="Not entirely focused on this project; assume split across three."),
        SheetLine(key="site_engineer", label="Site Engineer", resource_class=CLASS_SUPERVISION,
                  coefficient=1, driver=DRIVER_ON_SITE, unit="day", rate=2000,
                  note="Focused on this project."),
        SheetLine(key="geologist", label="Geologist", resource_class=CLASS_SUPERVISION,
                  coefficient=0.5, driver=DRIVER_ON_SITE, unit="day", rate=2500,
                  note="Also not entirely focused on this project."),
        SheetLine(key="foreman", label="Foreman", resource_class=CLASS_SUPERVISION, coefficient=1,
                  driver=DRIVER_ON_SITE, unit="day", rate=2000, note="Focused on this project."),

        SheetLine(key="surveying", label="Surveying", resource_class=CLASS_SUBCONTRACT,
                  qty=1, unit="location", rate=1000),

        # Laboratory testing — a subcontract, priced per test.
        SheetLine(key="lab_moisture", label="Moisture content test", resource_class=CLASS_SUBCONTRACT,
                  qty=5, unit="nr", rate=65, note="Moisture content by oven drying"),
        SheetLine(key="lab_atterberg", label="Atterberg's limits test",
                  resource_class=CLASS_SUBCONTRACT, qty=5, unit="nr", rate=695),
        SheetLine(key="lab_psd", label="Particle size distribution test",
                  resource_class=CLASS_SUBCONTRACT, qty=5, unit="nr", rate=295,
                  note="By wet sieving method"),
        SheetLine(key="lab_bulk_density", label="Bulk density test", resource_class=CLASS_SUBCONTRACT,
                  qty=5, unit="nr", rate=86, note="BS 1377 Part 2"),
        SheetLine(key="lab_specific_gravity", label="Specific gravity test",
                  resource_class=CLASS_SUBCONTRACT, qty=5, unit="nr", rate=100,
                  note="None in the schedule of rates."),
        SheetLine(key="lab_ph", label="pH value determination test", resource_class=CLASS_SUBCONTRACT,
                  qty=3, unit="nr", rate=150),
        SheetLine(key="lab_sulphate", label="Sulphate content determination test",
                  resource_class=CLASS_SUBCONTRACT, qty=3, unit="nr", rate=390),
        SheetLine(key="lab_chloride", label="Chloride content determination test",
                  resource_class=CLASS_SUBCONTRACT, qty=3, unit="nr", rate=345),
        SheetLine(key="lab_uu_triaxial", label="Unconsolidated undrained triaxial test",
                  resource_class=CLASS_SUBCONTRACT, qty=3, unit="nr", rate=650,
                  note="Without pore pressure"),
        SheetLine(key="lab_point_load", label="Point load test", resource_class=CLASS_SUBCONTRACT,
                  qty=5, unit="nr", rate=163),
        SheetLine(key="lab_ucs", label="UCS rock compression test", resource_class=CLASS_SUBCONTRACT,
                  qty=5, unit="nr", rate=1240),

        *material_lines(geometry, SOIL_M, ROCK_M, box_rate=150, tube_rate=100, grout_rate=30),

        SheetLine(key="small_consumables", label="Small consumables",
                  resource_class=CLASS_CONSUMABLE, driver=DRIVER_DRILLING, unit="day", rate=200,
                  note="Water and the like."),
        SheetLine(key="fuel", label="Fuel", resource_class=CLASS_CONSUMABLE,
                  driver=DRIVER_DRILLING, unit="day", rate=600, note="40 L/day at $12/L"),

        SheetLine(key="water_barriers", label="Water barriers", resource_class=CLASS_OTHER,
                  coefficient=0.2, qty=16, unit="nr", rate=665,
                  note="Site is 10 × 6 m; they survive about five jobs, so a fifth is charged here."),

        SheetLine(key="crane_lorry", label="Crane lorry", resource_class=CLASS_TRANSPORT,
                  qty=2, unit="day", rate=5000, note="One day in, one day out."),
        SheetLine(key="truck", label="Truck (extra equipment)", resource_class=CLASS_TRANSPORT,
                  qty=2, unit="day", rate=1500, note="Brings in the storage and equipment."),
    ]
    return ResourceSheet(label=label, lines=lines, duration=duration,
                         mob_days=MOB_DAYS, markup_pct=MARKUP_PCT)


# --- the ten recipes ------------------------------------------------------------------------------
def _spread_for(days: float) -> list[RecipeTerm]:
    """The whole spread, for a stated number of days. Used by mobilise and move."""
    return [RecipeTerm(key=key, units=days) for key in DAILY_KEYS]


def _daily_spread() -> list[RecipeTerm]:
    """One day of the spread. Multiplied by a day count from the duration model."""
    return [RecipeTerm(key=key, units=1) for key in DAILY_KEYS]


def recipes() -> dict[str, RateRecipe]:
    lab_soil = ["lab_moisture", "lab_atterberg", "lab_psd", "lab_bulk_density",
                "lab_specific_gravity", "lab_ph", "lab_sulphate", "lab_chloride"]
    lab_rock = ["lab_uu_triaxial", "lab_point_load", "lab_ucs"]

    return {
        # Two days of the whole spread, plus the one-off transport, the survey and the barriers.
        "A": RateRecipe(
            full_ref="A", label="Mobilise on Land", lump=True,
            terms=[*_spread_for(2),
                   RecipeTerm(key="surveying", units=1),
                   RecipeTerm(key="water_barriers"),
                   RecipeTerm(key="crane_lorry", units=1),
                   RecipeTerm(key="truck", units=1)],
        ),
        # The same, without the survey or the barriers — those are set up once, not on every move.
        "B": RateRecipe(
            full_ref="B", label="Move on Land", lump=True,
            terms=[*_spread_for(2),
                   RecipeTerm(key="crane_lorry", units=1),
                   RecipeTerm(key="truck", units=1)],
        ),
        "C": RateRecipe(full_ref="C", label="Vertically downwards (Soil)", terms=_daily_spread(),
                        days=DAYS_SOIL, divisor=SOIL_M, divisor_label="m"),
        "D": RateRecipe(full_ref="D", label="Vertically downwards (Rock)", terms=_daily_spread(),
                        days=DAYS_ROCK, divisor=ROCK_M, divisor_label="m"),
        "E": RateRecipe(full_ref="E", label="Backfilling Drillholes", lump=True,
                        terms=[RecipeTerm(key="cement_grout")]),
        "F": RateRecipe(full_ref="F", label="Providing core box", lump=True,
                        terms=[RecipeTerm(key="wooden_box")]),
        "G": RateRecipe(full_ref="G", label="Mazier Samples", terms=[RecipeTerm(key="soil_tube")],
                        divisor_key="soil_tube", divisor_label="nr"),
        "H": RateRecipe(full_ref="H", label="H-Size, N-Size rock core",
                        terms=[RecipeTerm(key="small_consumables"), RecipeTerm(key="fuel")],
                        divisor=ROCK_M, divisor_label="nr"),
        "I": RateRecipe(full_ref="I", label="Soil Tests", lump=True,
                        terms=[RecipeTerm(key=key) for key in lab_soil]),
        "J": RateRecipe(full_ref="J", label="Rock Tests", lump=True,
                        terms=[RecipeTerm(key=key) for key in lab_rock]),
    }
