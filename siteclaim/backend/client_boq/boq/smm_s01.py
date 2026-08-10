"""SMM Section 1 — the item coverage for General & Preliminaries, transcribed from the pack.

Bucket: **Deterministic transcription.** No model, no inference, no network. This module is data and
the checks that keep the data honest about itself.

Source: ``GP&PP/I-ND_2025_04-SMM_S01-0.pdf`` (Particular Preambles, Section 1), ND/2025/04 — read
directly off the PDF. 42 clauses, 264 printed sub-heads.

WHAT THIS IS, AND THE THING IT IS NOT
-------------------------------------
These are this contract's **amendments** to the *Standard Method of Measurement for Civil Engineering
Works (1992)* — additions and substitutions. **The base SMM 1992 is not in the pack.** Every list
built from this module is therefore partial by construction, exactly as
:data:`client_boq.boq.coverage.PARTIAL_BY_CONSTRUCTION` says, and nothing here may be read as a
clause's whole item coverage.

The lettering proves it, and proves it precisely. ¶1.06 carries (c), (f), (h)–(p) and (w); the pack
prints no (a), (b), (d), (e), (g) or (q)–(v), which means those sub-heads live in the base document.
:data:`BASE_SMM_GAPS` derives that from the letters actually transcribed rather than asserting it, so
the claim cannot drift from the data. It reports INTERIOR gaps only — a clause running (a)–(e) with
no holes tells you nothing about whether the base carries an (f), and this module does not pretend
otherwise.

FIVE THINGS THE PACK DOES THAT A TIDY TRANSCRIPTION WOULD HAVE SWALLOWED
-----------------------------------------------------------------------
Each is kept as data rather than cleaned away, because every one of them is a reader's question:

* :data:`TRIMMED_BLEED` — the PDF extraction ran the NEXT section's heading onto the end of a
  sub-head 26 times ("…reinstatement of the Site. **Provision, maintenance and removal of screens or
  enclosures for smoky activities 1.77 The item for…**"). Left in, ¶1.76(d) would read as though it
  covered ¶1.77's separately-measured work. The literal below is verbatim including the bleed, and
  ``_head`` cuts it and RECORDS the cut — so the file still diffs against the source document, and a
  mistyped cut raises at import instead of silently keeping the wrong half.
* :data:`RUN_ON_SPLIT` — ¶1.14(z) had three further sub-heads run onto it, each carrying its own
  printed reference (``1.14(aa)``, ``(ab)``, ``(ac)``). They are real sub-heads and are split out.
* :data:`NOT_USED` — ¶1.14(o) and ¶1.78 are printed "NOT USED". They are recorded, and they are NOT
  heads: a checklist line an estimator must tick to reach "all covered" is an obligation, and the
  pack says there is none here.
* :data:`TRUNCATED` — three sub-heads stop mid-sentence in the source (¶1.96(d) "…as mentioned in
  sub-clause", ¶1.112(s) "…including, but without limitation to, the followings:", ¶1.156(c) "…for
  complying with"). They are kept exactly as they break. Completing them from knowledge of what such
  a clause usually says is the one thing this module must never do.
* :data:`FRAGMENTS` — ¶1.17 and ¶1.19 came out of the PDF as "(i) and substitute : Unit 1.17", which
  is the tail of a "Delete … and substitute …" instruction whose substituted text did not extract.
  They are named as fragments and produce no heads at all.

Two more anomalies are the PACK's, not the reading's, and are left alone: ¶1.77(b) and ¶1.85(b) both
print "accpetance", and ¶1.06 prints TWO sub-heads lettered (k) — see :data:`PUBLISHER_ANOMALIES`.
The second (k) is named in :data:`SECOND_K`; its words were not transcribed and are not invented.

A NOTE ON ORDER. The clauses below are keyed by number, and ¶1.112 sits numerically between ¶1.111
and ¶1.116 — but the bleed chain shows the PDF's own reading order was ¶1.111 → [24-HOUR TELEPHONE
LINE] → ¶1.116 → ¶1.117 → [ENVIRONMENTAL MANAGEMENT] → ¶1.112 → [DWSS] → ¶1.133. Printed order is
not extracted order. Nothing here depends on order, which is why that is a footnote and not a bug.

WHAT THIS MODULE DELIBERATELY DOES NOT DO
-----------------------------------------
It does not map clauses to BQ items. A BQ item number is not an SMM clause number (BQ 1.12 is
*Contract Computer Facilities*; SMM ¶1.12 is something else), so the mapping is by TITLE and lives in
:mod:`client_boq.boq.coverage`, read off the real BQ pages — where, since the full Bill 1 read
(BQ 3–7, 63 items), every one of the 40 transcribed clauses is claimed by at least one rule. The
test that proves that lives with the mapping, not here.
"""

from __future__ import annotations

from client_boq.boq.heads import CoverageHead

# ---------------------------------------------------------------------------
# The transcription's own record of what it did to the source text.
# ---------------------------------------------------------------------------
#: Where the extractor ran the next heading onto a sub-head, and what was cut off the label.
TRIMMED_BLEED: list[dict] = []

#: Sub-heads that stop mid-sentence in the source. Kept as they break; never completed.
TRUNCATED: list[dict] = []


def _head(clause: str, letter: str, text: str, *, ps: str = "", cites: str = "",
          bleed: str = "", truncated: str = "") -> CoverageHead:
    """One printed sub-head, as a tickable coverage head.

    ``text`` is verbatim from the source INCLUDING any bled-in heading, so this file can be diffed
    against the document line by line. ``bleed`` names the tail to cut and is checked against the
    text — a mistyped cut raises here rather than leaving the wrong half on a checklist.

    Two pieces of trailing punctuation are dropped from the label: the full stop that ends a printed
    sub-head, and the "; and" that joins the last two in a list. Both are typesetting, not content.
    The first character is capitalised to match the voice of every other head in this package; no
    other character is touched.
    """
    if bleed:
        if not text.endswith(bleed):
            raise ValueError(
                f"¶{clause}({letter}): declared bleed {bleed[:40]!r}… is not how the text ends. "
                f"The transcription and the cut have drifted apart — fix the literal, not this check")
        TRIMMED_BLEED.append({"clause": clause, "letter": letter, "trimmed": bleed})
        text = text[: -len(bleed)].rstrip()

    label = text.removesuffix("; and").rstrip().removesuffix(".").rstrip()
    label = label[:1].upper() + label[1:]

    if truncated:
        TRUNCATED.append({"clause": clause, "letter": letter, "label": label,
                          "breaks_at": truncated})

    ref = f"SMM S01 ¶{clause}({letter})"
    if ps:
        ref = f"{ref} · {ps}"
    return CoverageHead(key=f"smm.s01.{clause}.{letter}", label=label, clause_ref=ref, cites=cites)


# A NOTE ON `cites`. The head cites the FIRST clause its text names, bare, as the rest of this
# package does ("1.14" for a head whose reference reads "PS 1.14–1.15"). A head naming a whole
# SECTION cites the section number — but ONLY where that number cannot prefix another section's
# clauses: `DocumentMap.resolve` falls back to a prefix match, so "25" reaches 25.xx and nothing
# else, while a bare "1" would also reach 10.xx, 11.xx and 12.xx. "PS Section 1" is therefore left
# UNCITED. A `▸ show me` that lands on the wrong page is worse than one that admits it cannot say.
CLAUSES: dict[str, list[CoverageHead]] = {
    # -----------------------------------------------------------------------
    # PROJECT MANAGER'S SITE OFFICE
    # -----------------------------------------------------------------------
    "1.05": [  # taking over of Project Manager's Site Office
        _head("1.05", "a",
              "taking over the existing temporary buildings, structures, facilities, access road "
              "and the like as stipulated in PS Clause 1.49",
              ps="PS 1.49", cites="1.49"),
        _head("1.05", "b",
              "provision of office supplies, furniture, equipment, surveying and testing "
              "instruments including all necessary documentation, training and technical supports "
              "as specified in PS"),
        _head("1.05", "c",
              "preparing, amending as necessary and submitting to the Project Manager details of "
              "design and finishing"),
        _head("1.05", "d",
              "provision of water, sanitation, heating, air conditioning, power, lighting, "
              "telephone, communication services, security services and burglar alarm system"),
        _head("1.05", "e",
              "all necessary costs to bring the existing temporary buildings, structure and "
              "facilities, furniture and equipment handed over the Contractor to the status, "
              "condition, quality and suitability complying in every aspect with the contract "
              "requirements including but not limited to those specified in PS Clause 1.49",
              ps="PS 1.49", cites="1.49"),
        _head("1.05", "f", "security measures and services"),
        _head("1.05", "g",
              "any other costs and expenses associated with taking over and renovating the Project "
              "Manager's Site Office"),
    ],
    "1.06": [  # maintenance. The pack prints TWO sub-heads lettered (k) — see SECOND_K.
        _head("1.06", "c",
              "maintenance of office and laboratory furniture and equipment and survey equipment "
              "as specified in PS Appendix 1.12 and 1.13, and equivalent replacement of furniture, "
              "equipment and survey equipment when the original furniture, equipment and survey "
              "equipment are unserviceable",
              ps="PS Appendix 1.12, 1.13", cites="Appendix 1.12"),
        _head("1.06", "f",
              "operatives, field assistants, office attendants, chainmen and site clerks and "
              "payment for overtime"),
        _head("1.06", "h", "charges for mobile telephones"),
        _head("1.06", "i",
              "maintenance of mobile telephones and all accessories and equivalent replacement "
              "when the originals are damaged or unserviceable as mentioned in PS Clauses 1.49E "
              "and PS Appendix 1.14",
              ps="PS 1.49E · PS Appendix 1.14", cites="1.49E"),
        _head("1.06", "j", "24-hours security guard services and payment of overtime"),
        _head("1.06", "k", "additional insurance cover for working outside the Site"),
        _head("1.06", "l",
              "maintenance of fire service installations and equipment, and equivalent replacement "
              "when the originals are damaged or unserviceable"),
        _head("1.06", "m", "maintenance of security provisions and burglar alarm system"),
        _head("1.06", "n",
              "provision and extension of servicing to site staff from other contracts of the "
              "Client permitted to use the Project Manager's interim accommodation"),
        _head("1.06", "o", "insurance coverage against loss and damage of any kind"),
        _head("1.06", "p", "daily house keeping and cleaning"),
        _head("1.06", "w", "Complying with all requirements as specified in PS Clause 1.49",
              ps="PS 1.49", cites="1.49"),
    ],
    "1.07": [  # handing back
        _head("1.07", "a",
              "receiving back supplies, furniture, equipment, uniform and survey equipment not "
              "required by the Client"),
        _head("1.07", "e",
              "delivery of samples and cores as instructed by the Project Manager to any locations "
              "within Hong Kong's territory. TEMPORARY ACCOMMODATION FOR THE CONTRACTOR",
              bleed="TEMPORARY ACCOMMODATION FOR THE CONTRACTOR"),
    ],
    # -----------------------------------------------------------------------
    # TEMPORARY ACCOMMODATION FOR THE CONTRACTOR
    # -----------------------------------------------------------------------
    "1.11": [
        _head("1.11", "a",
              "erection, servicing and removal of everything required by the Contractor, including "
              "sheds, stores, mess rooms, latrines, workmen's accommodation, hard-paved area for "
              "the implementation of Pre-work Activities of Site Safety Cycle as specified in PS "
              "Clause 27.18, and welfare facilities for workers in accordance with PS Clause 1.50S "
              "and the like",
              ps="PS 27.18 · PS 1.50S", cites="27.18"),
        _head("1.11", "c", "provision of fire service installations and equipment"),
        _head("1.11", "d",
              "maintenance of fire service installations and equipment and equivalent replacement "
              "when the originals are damaged or unserviceable"),
        _head("1.11", "e",
              "complying with the obligations, requirements and restrictions as described in the "
              "Engineering Conditions in PS Clause 1.45 and PS Appendix 1.11",
              ps="PS 1.45 · PS Appendix 1.11", cites="1.45"),
        _head("1.11", "f",
              "complying with all the requirements as specified in PS Clause 1.50S. MAINTENANCE OF "
              "TRAFFIC FLOW",
              ps="PS 1.50S", cites="1.50S", bleed="MAINTENANCE OF TRAFFIC FLOW"),
    ],
    # -----------------------------------------------------------------------
    # MAINTENANCE OF TRAFFIC FLOW — provision (¶1.14) and maintenance (¶1.15)
    # -----------------------------------------------------------------------
    "1.14": [
        _head("1.14", "l",
              "temporary diversion or relocation of utilities, services, street lighting, traffic "
              "signals, emergency telephone system and other street furniture, road markings, "
              "traffic signs, road studs or fittings or provision of temporary facilities in "
              "connection with or for the purpose of maintenance of temporary traffic arrangements "
              "and control including payment of fees and charges to third parties"),
        _head("1.14", "m",
              "the services of an independent, qualified and experienced Traffic Consultant and "
              "traffic arrangement implementation Co-ordinator accepted by the Project Manager"),
        _head("1.14", "n", "setting up the Traffic Management Liaison Group (TMLG) Meeting"),
        # (o) is printed "NOT USED" — recorded in NOT_USED, deliberately not a head.
        _head("1.14", "p",
              "temporary and permanent lighting to carriageways, footways and cycle tracks as "
              "required in the contract"),
        _head("1.14", "q",
              "preparing, amending and submitting temporary traffic diversion proposals for "
              "Project Manager's acceptance"),
        _head("1.14", "r",
              "preparing, amending and submitting the Traffic Management Contingency Plan for the "
              "Project Manager's acceptance"),
        _head("1.14", "s",
              "complying with all requirements of temporary traffic arrangement as stipulated in "
              "PS Clause 1.14 to 1.15 inclusive",
              ps="PS 1.14–1.15", cites="1.14"),
        _head("1.14", "t",
              "all costs and charges for provision of measures to maintain traffic flow to "
              "carriageways, footways and cycle tracks"),
        _head("1.14", "u",
              "all costs and charges for provision of measures to maintain traffic flow for any "
              "work at all times, including working during normal working hours, outside normal "
              "working hours, within restricted working hours and during peak hours"),
        _head("1.14", "v",
              "all costs and charges due to constraints, restrictions or special requirements of "
              "use of roads, footways, cycle tracks and the like as stipulated in PS Clauses 1.16A "
              "to 1.18B inclusive",
              ps="PS 1.16A–1.18B", cites="1.16A"),
        _head("1.14", "x",
              "all cost and charges for provision, relocation and removal of publicity boards, "
              "display boards, light emitting diode display boards and the like"),
        _head("1.14", "y", "provision of temporary access roads"),
        # (z) and the three below arrived as ONE run-on bullet. Each of (aa)–(ac) carries its own
        # printed reference in the source text, so they are four sub-heads, not one. See
        # RUN_ON_SPLIT — this is where 264 printed bullets become 267 heads.
        _head("1.14", "z", "provision of temporary street lighting"),
        _head("1.14", "aa",
              "all costs and charges for providing fire fighting operations requirements"),
        _head("1.14", "ab", "provisions of temporary emergency telephone system"),
        _head("1.14", "ac",
              "all other works in connection with or arising out of the maintenance of traffic "
              "flow"),
    ],
    "1.15": [
        _head("1.15", "e", "preparation and submission of monthly report"),
        _head("1.15", "f",
              "provision of tow-truck as required by TMLG to attend any traffic incident"),
        _head("1.15", "g",
              "payment of energy fees and charges to third parties for temporary lighting"),
        _head("1.15", "h",
              "provision of equipment and operatives for implementation of trials and the accepted "
              "temporary traffic management scheme as instructed by the Project Manager"),
        _head("1.15", "i", "provision of equipment and operative for implementation"),
        _head("1.15", "j",
              "complying with all requirements of temporary traffic arrangement as stipulated in "
              "PS Clauses 1.14 to 1.15 inclusive",
              ps="PS 1.14–1.15", cites="1.14"),
        _head("1.15", "k",
              "all costs and charges for maintenance and operation of measures to maintain traffic "
              "flow to carriageways, footways and cycle tracks"),
        _head("1.15", "l",
              "all costs and charges for maintenance and operation of measures to maintain traffic "
              "flow for any work at all times, including working during normal working hours, "
              "outside normal working hours, within restricted working hours and during peak hours"),
        _head("1.15", "m",
              "all costs and charges due to constraints, restrictions or special requirements of "
              "use of roads, footways cycle tracks and the like as stipulated in PS Clauses 1.16A "
              "to 1.18B inclusive",
              ps="PS 1.16A–1.18B", cites="1.16A"),
        _head("1.15", "n", "all costs and charges to maintain temporary access roads"),
        _head("1.15", "p",
              "all cost and charges for maintenance of publicity boards, display boards, light "
              "emitting diode display boards and the like"),
        _head("1.15", "q", "all cost and charges to maintain temporary street lighting"),
        _head("1.15", "r", "all costs and charges for maintaining fire fighting operations "
                           "requirements"),
        _head("1.15", "s", "all costs and charges to maintain temporary emergency telephone system"),
        _head("1.15", "t",
              "all other works in connection with or arising out of the maintenance of traffic "
              "flow. THIRD PARTY INSURANCE AND PROFESSIONAL INDEMNITY INSURANCE",
              bleed="THIRD PARTY INSURANCE AND PROFESSIONAL INDEMNITY INSURANCE"),
    ],
    # -----------------------------------------------------------------------
    # THIRD PARTY INSURANCE AND PROFESSIONAL INDEMNITY INSURANCE
    # -----------------------------------------------------------------------
    "1.18": [
        # The insurance clauses cite the NEC conditions, not the Particular Specification, so there
        # is nothing for the specification index to resolve and nothing is cited.
        _head("1.18", "a",
              "in the case of third party insurance, procurement of third party insurance as "
              "specified in NEC Clause 84, 85 and additional conditions of contract",
              ps="NEC 84–85"),
        _head("1.18", "b",
              "in the case of professional indemnity insurance, procurement of professional "
              "indemnity insurance as specified in additional conditions of contract"),
        _head("1.18", "c",
              "all fees, premiums, charges for and in connection with the procurement of "
              "insurances"),
    ],
    # -----------------------------------------------------------------------
    # VEHICLES FOR THE PROJECT MANAGER — provision (¶1.22) and running (¶1.23)
    # -----------------------------------------------------------------------
    "1.22": [
        _head("1.22", "d", "handfree type mobile telephones and all accessories"),
        _head("1.22", "e", "auto-toll vehicle devices for all tunnels, bridges and expressways"),
        _head("1.22", "f", "provision of safety equipment and devices"),
        _head("1.22", "g",
              "provision of identification logo, lettering and characters in accordance with CEDD "
              "standard drawing No. C1011B",
              ps="CEDD Std Dwg C1011B"),
        _head("1.22", "h",
              "removal of identification signs, lettering, characters and education banners upon "
              "reverting back to Contractor"),
    ],
    "1.23": [
        _head("1.23", "a", "tax, licences, insurances, parking and tunnel charges"),
        _head("1.23", "b", "driver including payment for overtime"),
        _head("1.23", "f", "charges for handfree type mobile telephone and all accessories"),
        _head("1.23", "g",
              "maintenance for handfree type mobile telephone and equivalent replacement when the "
              "original is damaged or unserviceable"),
        _head("1.23", "h",
              "charges for auto-toll vehicle devices for all tunnels, bridges and expressways"),
        _head("1.23", "i",
              "maintenance of safety equipment and devices and equivalent replacement when the "
              "original is damaged or unserviceable"),
        _head("1.23", "j",
              "maintenance of identification signs, lettering, characters and education banners"),
        _head("1.23", "k",
              "allowing for the use of the transport by the Project Manager's staff or other "
              "persons as authorized by the Project Manager"),
        _head("1.23", "l", "allowing for use at all times in accordance with PS Clause 1.52",
              ps="PS 1.52", cites="1.52"),
        _head("1.23", "m",
              "maintaining log book for recording details of use of the vehicles including "
              "submission of records to the Project Manager"),
        _head("1.23", "n",
              "complying with all the requirements as specified in PS Clause 1.52. CONTRACT "
              "COMPUTER FACILITIES AND ELECTRONIC DOCUMENT MANAGEMENT SYSTEM FOR THE PROJECT "
              "MANAGER",
              ps="PS 1.52", cites="1.52",
              bleed="CONTRACT COMPUTER FACILITIES AND ELECTRONIC DOCUMENT MANAGEMENT SYSTEM FOR "
                    "THE PROJECT MANAGER"),
    ],
    # -----------------------------------------------------------------------
    # CONTRACT COMPUTER FACILITIES AND ELECTRONIC DOCUMENT MANAGEMENT SYSTEM
    # -----------------------------------------------------------------------
    # ONE clause, TWO bill items. The BQ bills the computer facilities and the EDMS separately and
    # ¶1.28 governs both — both sub-heads name both systems. Two title rules therefore share these
    # heads; `heads_for` de-duplicates on the key, so an item reached by both carries each once.
    "1.28": [
        _head("1.28", "s",
              "compliance with the requirements as specified in PS Clause 1.49A, 1.49C, Appendix "
              "1.15 for Contract Computer Facilities and Electronic Document Management System",
              ps="PS 1.49A, 1.49C · PS Appendix 1.15", cites="1.49A"),
        _head("1.28", "t",
              "providing replacement units of at least the same functional requirements where "
              "Contract Computer Facilities and Electronic Document Management System are stolen "
              "or lost. PHOTOGRAPHS",
              bleed="PHOTOGRAPHS"),
    ],
    # -----------------------------------------------------------------------
    # PHOTOGRAPHS · HOARDINGS
    # -----------------------------------------------------------------------
    "1.32": [
        _head("1.32", "g", "provision of digital camera"),
        _head("1.32", "h",
              "photo papers, ink, and all necessary consumables for production of the photographs "
              "taken by digital camera"),
    ],
    "1.37": [
        _head("1.37", "k", "fabrication of steelwork"),
        _head("1.37", "l", "erection of steelwork"),
        _head("1.37", "m", "protective treatment"),
        _head("1.37", "n", "temporary lighting system and energy costs"),
        _head("1.37", "o",
              "relocation and modification works of hoardings, temporary fences, signboards"),
        _head("1.37", "p",
              "in the case of hoardings, including complying with the Air Pollution Control "
              "(Construction Dust) Regulation and requirement of PS Clause 1.48",
              ps="PS 1.48", cites="1.48"),
        _head("1.37", "q", "complying with all the requirements as specified in PS Clause 1.48",
              ps="PS 1.48", cites="1.48"),
    ],
    # -----------------------------------------------------------------------
    # ENVIRONMENTAL MITIGATION MEASURES — provision / maintenance / removal
    # -----------------------------------------------------------------------
    "1.40": [  # provision of environmental mitigation measures not separately measured
        _head("1.40", "a",
              "engagement and maintaining the services of Environmental Officer to provide advice "
              "and service on the environmental mitigation measures"),
        _head("1.40", "b",
              "provision of environmental mitigation measures in accordance with GS and PS "
              "Section 25",
              ps="GS · PS Section 25", cites="25"),
        _head("1.40", "c",
              "provision of those environmental mitigation measures in accordance with PS "
              "Section 1 which are not separately measured under any other items of work",
              ps="GS · PS Section 1"),
        _head("1.40", "d", "complying with the requirements on environmental mitigation"),
        _head("1.40", "e",
              "provision and setting up of equipment, facilities, instruments, operatives and "
              "technicians"),
        _head("1.40", "f", "attending meetings, District Council meetings etc"),
    ],
    "1.41": [  # maintenance of environmental mitigation measures not separately measured
        _head("1.41", "a",
              "maintenance of environmental mitigation measures in accordance with GS and PS "
              "Section 25",
              ps="GS · PS Section 25", cites="25"),
        _head("1.41", "b",
              "maintenance of those environmental mitigation measures in accordance with PS "
              "Section 1 which are not separately measured under any other items of work",
              ps="PS Section 1"),
        _head("1.41", "c",
              "maintenance of equipment, facilities and instruments and equivalent replacement of "
              "equipment, facilities and instruments when the original equipment, facilities and "
              "instruments are unserviceable"),
        _head("1.41", "d", "replenishment of consumables"),
        _head("1.41", "e", "operatives"),
        _head("1.41", "f", "power supply"),
        _head("1.41", "g", "cleaning"),
        _head("1.41", "h",
              "operate the waste management facilities according to PS Section 1",
              ps="PS Section 1"),
    ],
    "1.42": [  # removal of environmental mitigation measures not separately measured
        _head("1.42", "a",
              "removal of environmental mitigation measures in accordance with GS and PS "
              "Section 25",
              ps="GS · PS Section 25", cites="25"),
        _head("1.42", "b",
              "removal of those environmental mitigation measures in accordance with PS Section 1 "
              "which are not separately measured under any other items of work",
              ps="PS Section 1"),
        _head("1.42", "c",
              "dismantling all equipment, facilities and instruments for environmental mitigation "
              "measures"),
        _head("1.42", "d", "removing all equipment, facilities and instruments off Site"),
        _head("1.42", "e", "reinstatement of the Site"),
        _head("1.42", "f", "remove all waste management facilities"),
    ],
    # -----------------------------------------------------------------------
    # ENVIRONMENTAL MONITORING MEASURES — provision / maintenance / removal
    # -----------------------------------------------------------------------
    # ⚠ TRANSCRIBED BUT NOT ATTACHED TO ANY BILL ITEM. The Bill 1 mapping's `smm1.45` rule matches
    # an item titled "…noise… mitigation…" and names this range — but these three clauses are
    # environmental MONITORING, and mitigation is ¶1.40–1.42. Which the BQ item really is cannot be
    # settled from this document, so the text sits here, read and available, and is not hung on a
    # rule whose title contradicts it. See `MAPPING_UNVERIFIED`.
    "1.45": [  # provision of environmental monitoring measures not separately measured
        _head("1.45", "a",
              "engagement of Environmental Officer to provide advice and service on the "
              "environmental monitoring measures"),
        _head("1.45", "b",
              "provision of environmental monitoring measures in accordance with GS and PS "
              "Section 25",
              ps="GS · PS Section 25", cites="25"),
        _head("1.45", "c",
              "provision of those environmental monitoring measures in accordance with PS "
              "Section 1 which are not separately measured under any other items of work",
              ps="PS Section 1"),
        _head("1.45", "d", "provision of access to monitoring and control stations"),
        _head("1.45", "e", "complying with the requirements on environmental monitoring"),
        _head("1.45", "f", "maintaining the service of Environmental Officer"),
        _head("1.45", "g", "work boats including operatives"),
        _head("1.45", "h",
              "provision and setting up of equipment, facilities and instruments, attendants and "
              "technicians"),
        _head("1.45", "i", "setting out and marking sampling locations"),
        _head("1.45", "j",
              "carrying out monitoring works at designated monitoring and control stations"),
        _head("1.45", "k",
              "calibration of all equipment including sampling, testing and monitoring equipment"),
        _head("1.45", "l", "provision of training to personnel for operation of the equipment"),
        _head("1.45", "m", "all sampling and testing in an accepted laboratory"),
        _head("1.45", "n", "taking readings, measurements and recording"),
        _head("1.45", "o", "reporting of monitoring data, including submission of reports"),
        _head("1.45", "p",
              "identifying any environmental deficiency, proposing rectification measures, "
              "rectification of such deficiency as accepted and including additional environmental "
              "monitoring works"),
        _head("1.45", "q", "arranging and attending environmental site inspections"),
        _head("1.45", "r", "overtime work outside normal working hours"),
        _head("1.45", "s", "attending meetings, District Council meetings etc"),
    ],
    "1.46": [  # maintenance of environmental monitoring measures not separately measured
        _head("1.46", "a",
              "maintenance of environmental monitoring measures in accordance with GS and PS "
              "Section 25",
              ps="GS · PS Section 25", cites="25"),
        _head("1.46", "b",
              "maintenance of those environmental monitoring measures in accordance with PS "
              "Section 1 which are not separately measured under any other items of work",
              ps="PS Section 1"),
        _head("1.46", "c", "maintenance of access to monitoring and control stations"),
        _head("1.46", "d",
              "maintenance of equipment, facilities and instruments and equivalent replacement of "
              "equipment, facilities and instruments when the original equipment, facilities and "
              "instruments are unserviceable"),
        _head("1.46", "e", "replenishment of consumables"),
        _head("1.46", "f", "operatives"),
        _head("1.46", "g", "power supply"),
        _head("1.46", "h", "cleaning"),
        _head("1.46", "i",
              "operate the waste monitoring and recording measures according to PS Section 1",
              ps="PS Section 1"),
    ],
    "1.47": [  # removal of environmental monitoring measures not separately measured
        _head("1.47", "a",
              "removal of environmental monitoring measures in accordance with GS and PS "
              "Section 25",
              ps="GS · PS Section 25", cites="25"),
        _head("1.47", "b",
              "removal of those environmental and waste monitoring measures in accordance with PS "
              "Section 1 which are not separately measured under any other items of work",
              ps="PS Section 1"),
        _head("1.47", "c",
              "dismantling all equipment, facilities and instruments for environmental monitoring "
              "measures"),
        _head("1.47", "d", "removing all equipment, facilities and instruments off Site"),
        _head("1.47", "e", "reinstatement of the Site"),
    ],
    # -----------------------------------------------------------------------
    # TRIP TICKET SYSTEM — the plan (¶1.66) and its implementation (¶1.67)
    # -----------------------------------------------------------------------
    "1.66": [  # complete site management plan for trip ticket system
        _head("1.66", "a",
              "prepare the site management plan for trip ticket system to the acceptance of the "
              "Project Manager"),
        _head("1.66", "b",
              "distribute or inform all relevant parties details of the site management plan for "
              "trip ticket system"),
        _head("1.66", "c",
              "inform truck drivers engaged in the disposal of C&D materials the requirements "
              "under the trip ticket system. Implementation of Site Management Plan for Trip "
              "Ticket System 1.67 The item for implementation of site management plan for trip "
              "ticket system shall, in accordance with General Preambles paragraph 2, include "
              "for : Item coverage",
              bleed="Implementation of Site Management Plan for Trip Ticket System 1.67 The item "
                    "for implementation of site management plan for trip ticket system shall, in "
                    "accordance with General Preambles paragraph 2, include for : Item coverage"),
    ],
    "1.67": [  # implementation of site management plan for trip ticket system
        _head("1.67", "a",
              "review, update and revise the site management plan for trip ticket system taking "
              "into account the comments made by the Project Manager or any other parties"),
        _head("1.67", "b",
              "assign staff and provide/operate/maintain/remove video recording system and other "
              "necessary facilities / equipment for overseeing and implementation of site "
              "management plan for trip ticket system"),
        _head("1.67", "c",
              "implement measures to ensure that trucks carrying C&D materials from the Site "
              "proceed to the disposal grounds designated in the contract or directed or accepted "
              "by the Project Manager to his acceptance"),
        _head("1.67", "d",
              "devise and implement appropriate measures to ensure that the sorted recyclable "
              "materials, which are sorted on the Site for the purpose of recycling such "
              "materials, are delivered to a proper recycling outlet for processing"),
        _head("1.67", "e", "compile, submit and maintain disposal records"),
        _head("1.67", "f",
              "investigate and report on incidents of improper disposal and non-compliance with "
              "the trip ticket system"),
        _head("1.67", "g",
              "monitor performance of trip ticket system and implement improvement measures"),
        _head("1.67", "h",
              "implement additional measures to control disposal of C&D materials to alternative "
              "disposal ground which the Project Manager has accepted"),
        _head("1.67", "i",
              "distribute revisions of the site management plan for trip ticket system to all "
              "relevant parties including the truck drivers engaged in delivery of C&D materials "
              "for disposal"),
        _head("1.67", "j",
              "other requirements for implementation of the trip ticket system as stipulated in "
              "Particular Specification clauses for Trip Ticket System. AIR POLLUTION ABATEMENT",
              bleed="AIR POLLUTION ABATEMENT"),
    ],
    # -----------------------------------------------------------------------
    # AIR POLLUTION ABATEMENT — dust covering (¶1.76) and smoke screens (¶1.77)
    # -----------------------------------------------------------------------
    "1.76": [
        _head("1.76", "a",
              "provision, maintenance and removal of the means from time to time to ensure that "
              "dusty materials are properly contained or covered by tarpaulin or other accepted "
              "means to the acceptance of the Project Manager or Supervisor"),
        _head("1.76", "b",
              "provision, maintenance and removal of appropriate air pollution abatement measures "
              "for dusty construction activities carried out in the close proximity to the public "
              "to the acceptance of the Project Manager or Supervisor"),
        _head("1.76", "c",
              "proper handling/disposal of the covering, screening materials and the like for "
              "reuse or recycling if they are no longer necessary"),
        _head("1.76", "d",
              "reinstatement of the Site. Provision, maintenance and removal of screens or "
              "enclosures for smoky activities 1.77 The item for provision, maintenance and "
              "removal of screens or enclosures for smoky activities shall, in accordance with "
              "General Preambles paragraph 2, include for : Item coverage",
              bleed="Provision, maintenance and removal of screens or enclosures for smoky "
                    "activities 1.77 The item for provision, maintenance and removal of screens or "
                    "enclosures for smoky activities shall, in accordance with General Preambles "
                    "paragraph 2, include for : Item coverage"),
    ],
    "1.77": [  # provision, maintenance and removal of screens or enclosures for SMOKY activities
        _head("1.77", "a",
              "submission of the construction details of the smoke screens or enclosures to be "
              "provided on the Site to the Project Manager for acceptance"),
        # "accpetance" is the pack's own spelling, in ¶1.77(b) and again in ¶1.85(b). Left as
        # printed — see PUBLISHER_ANOMALIES.
        _head("1.77", "b",
              "fixing of the screens or enclosures securely and safely to the accpetance of the "
              "Project Manager or Supervisor"),
        _head("1.77", "c", "maintenance of the screens or enclosures after erection till removal"),
        _head("1.77", "d",
              "removal of the screens or enclosures and reinstatement of the Site. 1.78 NOT USED "
              "NOISE POLLUTION ABATEMENT",
              bleed="1.78 NOT USED NOISE POLLUTION ABATEMENT"),
    ],
    # -----------------------------------------------------------------------
    # NOISE POLLUTION ABATEMENT — acoustic screens (¶1.85), other practices (¶1.86)
    # -----------------------------------------------------------------------
    "1.85": [  # provision, maintenance and removal of ACOUSTIC screens or enclosures
        _head("1.85", "a",
              "submission of the construction details of the acoustic screens or enclosures to be "
              "provided on the Site to the Project Manager for acceptance, if the design of such "
              "acoustic screens or enclosures has not been adopted for the contract previously"),
        _head("1.85", "b",
              "fixing of the acoustic screens or enclosures securely and safely to the accpetance "
              "of the Project Manager or Supervisor"),
        _head("1.85", "c",
              "removal of the acoustic screens or enclosures and reinstatement of the Site after "
              "removal"),
        _head("1.85", "d",
              "proper maintenance of the acoustic screens or enclosures after erection till "
              "removal. Adoption of other noise abatement practices 1.86 The item for adoption of "
              "other noise abatement practices shall, in accordance with General Preambles "
              "paragraph 2, include for : Item coverage",
              bleed="Adoption of other noise abatement practices 1.86 The item for adoption of "
                    "other noise abatement practices shall, in accordance with General Preambles "
                    "paragraph 2, include for : Item coverage"),
    ],
    "1.86": [  # adoption of other noise abatement practices — no BQ item mapped, see UNMAPPED
        _head("1.86", "a",
              "provision, maintenance and removal of all noise abatement practices in accordance "
              "with the requirements specified in GS & PS Clause 25.12 to the acceptance of the "
              "Project Manager or Supervisor. WASTEWATER POLLUTION ABATEMENT",
              ps="GS · PS 25.12", cites="25.12", bleed="WASTEWATER POLLUTION ABATEMENT"),
    ],
    # -----------------------------------------------------------------------
    # WASTEWATER POLLUTION ABATEMENT · WASTE MANAGEMENT — no BQ item mapped
    # -----------------------------------------------------------------------
    "1.91": [  # provision, maintenance and removal of wastewater collection system
        _head("1.91", "a",
              "design of the wastewater collection system and submission of the design to the "
              "Project Manager for acceptance"),
        _head("1.91", "b",
              "provide all necessary dykes, ditches, pipes and fittings of sufficient capacity, "
              "and extent for collecting surface run-off and wastewater from all locations of the "
              "Site to appropriate treatment facilities, including any accepted modification to "
              "the works"),
        _head("1.91", "c",
              "modification or improvement of the layout system to suit the change of the Site "
              "conditions and works progress, or if the Project Manager does not accept its "
              "performance"),
        _head("1.91", "d", "make all necessary alterations to the works to suit the system"),
        _head("1.91", "e",
              "removal of the system and reinstatement of the Site. WASTE MANAGEMENT",
              bleed="WASTE MANAGEMENT"),
    ],
    "1.96": [  # arrange and conduct on-site sorting of C&D materials
        _head("1.96", "a",
              "submission of a detailed work plan for on-site sorting of C&D materials to the "
              "Project Manager"),
        _head("1.96", "b",
              "sorting non-inert portions of C&D materials from inert C&D materials, and further "
              "sorting of reusable or recyclable materials such as plastic, paper, timber, etc. "
              "from the non-inert portions"),
        _head("1.96", "c",
              "separation of hard rock and broken concrete from the inert portion of C&D materials "
              "and delivery to a designated location as instructed by the Project Manager"),
        # The source stops at "sub-clause" with no reference following it. Kept as it breaks.
        _head("1.96", "d",
              "arrangement of recycling contractors to collect the sorted reusable or recyclable "
              "materials as mentioned in sub-clause",
              truncated="names a sub-clause and the reference did not extract"),
        _head("1.96", "e",
              "proper handling and storage of chemical wastes for collection and disposal of by "
              "specialist contractors"),
        _head("1.96", "f",
              "thorough sorting of demolition waste for recovering broken concrete, reinforcement "
              "bars, mechanical and electrical fittings, hardware etc., and delivery to proper "
              "recycling outlets. MONITORING THE USE OF ULTRA LOW SULPHUR DIESEL",
              bleed="MONITORING THE USE OF ULTRA LOW SULPHUR DIESEL"),
    ],
    # -----------------------------------------------------------------------
    # ULTRA LOW SULPHUR DIESEL · SURVEY OF THE SITE
    # -----------------------------------------------------------------------
    "1.100": [  # arrange and conduct testing of fuel sample by laboratory
        _head("1.100", "a", "preparation of the sample including the security measures"),
        _head("1.100", "b",
              "arrangement and delivery of the fuel sample to the laboratory as agreed by the "
              "Project Manager"),
        _head("1.100", "c", "all the testing fees charged by the laboratory"),
        _head("1.100", "d", "delivery charges"),
        _head("1.100", "e",
              "arrangement to have a certified copy of the test report delivered to the Project "
              "Manager. SURVEY OF THE SITE",
              bleed="SURVEY OF THE SITE"),
    ],
    "1.104": [  # survey of the Site
        _head("1.104", "a",
              "complying with all the requirements and restrictions when carrying out the survey "
              "works"),
        _head("1.104", "b",
              "co-ordinating and liaison with all relevant authorities and the owners of the "
              "existing roads, buildings and structures for carrying out survey works"),
        _head("1.104", "c", "employment of an approval surveyor for carrying out survey works"),
        _head("1.104", "d",
              "obtaining permission from relevant authorities and owners to carry out the survey "
              "works"),
        _head("1.104", "e",
              "setting up Survey Stations, taking readings, measurements and observations, and "
              "recording and supplying drawings and survey report to the Project Manager"),
        _head("1.104", "f", "extension of insurance cover for working outside the Site"),
        _head("1.104", "g", "record photographs, negatives and approved albums"),
        _head("1.104", "h",
              "carrying out condition survey as required in PS Clause 1.26",
              ps="PS 1.26", cites="1.26"),
        _head("1.104", "i",
              "submitting the proposal of monitoring of adjacent roads, buildings structure, "
              "service etc. to the Project Manager for consent prior to the commencement of nearby "
              "construction works; and"),
        _head("1.104", "j",
              "complying with all the requirements as specified in PS Clause 1.47A and 1.26. CORE "
              "AND SAMPLE STORE FOR THE PROJECT MANAGER",
              ps="PS 1.47A, 1.26", cites="1.47A",
              bleed="CORE AND SAMPLE STORE FOR THE PROJECT MANAGER"),
    ],
    # -----------------------------------------------------------------------
    # CORE AND SAMPLE STORE — erection (¶1.109), servicing (¶1.110), handover (¶1.111)
    # -----------------------------------------------------------------------
    "1.109": [
        _head("1.109", "a",
              "erection of core and sample store for the Project Manager at a location to be "
              "instructed by the Project Manager"),
        _head("1.109", "b", "excavation, levelling and preparation"),
        _head("1.109", "c", "foundations, base and hardstanding"),
        _head("1.109", "d",
              "store facilities including movable inspection bench, metal rack with shelves, "
              "dismountable trestle table and their fixtures"),
        _head("1.109", "e", "equipment and facilities"),
        _head("1.109", "f", "water, power and lighting services"),
        _head("1.109", "g",
              "vehicle access, parking areas and footways including surface drainage system and "
              "connections to public drainage system"),
        _head("1.109", "h", "facilities for weatherproofing"),
        _head("1.109", "i",
              "complying with all the requirements as specified in PS Clause 1.49B. servicing of "
              "core and sample store for the Project Manager 1.110 The items for servicing of core "
              "and sample store for the Project Manager shall, in accordance with General "
              "Preambles paragraph 2, include for : Item coverage",
              ps="PS 1.49B", cites="1.49B",
              bleed="servicing of core and sample store for the Project Manager 1.110 The items "
                    "for servicing of core and sample store for the Project Manager shall, in "
                    "accordance with General Preambles paragraph 2, include for : Item coverage"),
    ],
    "1.110": [
        _head("1.110", "a",
              "charges for water, power and lighting services and for continuous occupation and "
              "use of the areas for core and sample store"),
        _head("1.110", "b",
              "maintenance of core boxes and store facilities, vehicle access, parking space, hard "
              "standings and footways"),
        _head("1.110", "c",
              "equivalent replacement of the store facilities and its fixtures when they are "
              "unserviceable"),
        _head("1.110", "d", "moving core boxes and samples whenever required by the Project Manager"),
        _head("1.110", "e", "cleaning"),
        _head("1.110", "f", "moving and re-establishing store"),
        _head("1.110", "g",
              "complying with all the requirements stipulated in PS Clause 1.49B. Handing over "
              "core and sample store to the Client 1.111 The item for handing over core and sample "
              "store to the Client shall, in accordance with General Preambles paragraph 2, "
              "include for : Item coverage",
              ps="PS 1.49B", cites="1.49B",
              bleed="Handing over core and sample store to the Client 1.111 The item for handing "
                    "over core and sample store to the Client shall, in accordance with General "
                    "Preambles paragraph 2, include for : Item coverage"),
    ],
    "1.111": [
        _head("1.111", "a",
              "receiving back store facilities and disposal of cores and samples not required by "
              "the Client"),
        _head("1.111", "b",
              "checking and repairing the core and sample store including equipment and facilities "
              "to proper working order"),
        _head("1.111", "c",
              "delivery of core and sample store to a location designated by the Project Manager"),
        _head("1.111", "d",
              "complying with all the requirements as specified in PS Clause 1.49B. 24-HOUR "
              "TELEPHONE LINE TO RECEIVE ENQUIRIES",
              ps="PS 1.49B", cites="1.49B",
              bleed="24-HOUR TELEPHONE LINE TO RECEIVE ENQUIRIES"),
    ],
    # -----------------------------------------------------------------------
    # ENVIRONMENTAL MANAGEMENT — no BQ item mapped, see UNMAPPED
    # -----------------------------------------------------------------------
    "1.112": [
        _head("1.112", "a",
              "development, reviewing, updating and revising the Environmental Management Plan "
              "taking into account the comments made on the Environmental Management Plan by the "
              "Project Manager and any other parties"),
        _head("1.112", "b",
              "providing the actual quantities of C&D materials generated for the month by "
              "completing the monthly summary Waste Table, and a forecast of the quantities"),
        _head("1.112", "c",
              "updating of the summary table for work processes or activities requiring the use of "
              "timbers for Temporary Works construction"),
        _head("1.112", "d",
              "reviewing the adequacy of resources and facilities for on-site sorting of C&D "
              "materials"),
        _head("1.112", "e",
              "reviewing the adequacy of the nuisance abatement measures based on measurements "
              "taken on the various pollution parameters and public complaints"),
        _head("1.112", "f",
              "submission of the qualifications and experience of the proposed Environmental "
              "Officer to the Project Manager for acceptance"),
        _head("1.112", "g",
              "ensuring the fulfilment of the duties by the Assigned Person in accordance with PS "
              "Clause 25.35 to the satisfaction of the Project Manager or the Supervisor",
              ps="PS 25.35", cites="25.35"),
        _head("1.112", "h",
              "maintenance of the environmental records in accordance with PS Clause 25.36 (17)",
              ps="PS 25.36(17)", cites="25.36"),
        _head("1.112", "i",
              "attendance of the Site Environmental Management Committee meetings and complete the "
              "agenda of the meeting for the month"),
        _head("1.112", "j",
              "ranging inspection of the Site by members of the Site Environmental Management "
              "Committee before the meeting for the month"),
        _head("1.112", "k",
              "providing necessary assistance for the proper functioning of the Site Environmental "
              "Management Committee"),
        _head("1.112", "l", "establishment of the Site Environmental Committee"),
        _head("1.112", "m",
              "arranging and giving adequate notice to relevant parties of the Site Environmental "
              "Committee meeting to be held for the month"),
        _head("1.112", "n",
              "attendance of the Site Environmental Committee meetings and completion and "
              "distribution of minutes of meetings"),
        _head("1.112", "o",
              "arranging, giving adequate notice to relevant parties of and attending the weekly "
              "environmental walk"),
        _head("1.112", "p",
              "using a comprehensive checklist during the walk to identify any deficiencies noted "
              "in the environmental provisions, recording the deficiencies in the summary table, "
              "and rectifying such deficiencies subsequently within the agreed time"),
        _head("1.112", "q",
              "preparation of reports on environmental walks and environmental inspections "
              "conducted"),
        _head("1.112", "r",
              "implementation and upkeeping of all measures stipulated in the Particular "
              "Specification on environmental management and the EMP, and maintain the "
              "effectiveness of all such provisions for the duration of the contract"),
        # The source stops at the colon; the list of inspections did not extract. Kept as it breaks.
        _head("1.112", "s",
              "conducting environmental inspections including, but without limitation to, the "
              "followings:",
              truncated="introduces a list and the list did not extract"),
        _head("1.112", "t",
              "implementation of the decisions and recommendations made by the Site Environmental "
              "Management Committee on matters relating to environmental nuisance and waste "
              "management; and"),
        _head("1.112", "u",
              "conducting environmental training in accordance with PS Clause 25.35 (4). DIGITAL "
              "WORKS SUPERVISION SYSTEM (DWSS)",
              ps="PS 25.35(4)", cites="25.35",
              bleed="DIGITAL WORKS SUPERVISION SYSTEM (DWSS)"),
    ],
    # -----------------------------------------------------------------------
    # 24-HOUR TELEPHONE LINE — provision (¶1.116) and operation (¶1.117)
    # -----------------------------------------------------------------------
    "1.116": [
        _head("1.116", "a",
              "provision of equipment, accessories and telephone hotline for enquires and "
              "complaints service as specified in PS Clause 1.48(9)",
              ps="PS 1.48(9)", cites="1.48"),
        _head("1.116", "b",
              "removal of all equipment and accessories when no longer required. Operation and "
              "maintenance of 24-hour telephone line to receive enquiries 1.117 The items for "
              "operation and maintenance of 24-hour telephone line to receive enquiries shall, in "
              "accordance with General Preambles paragraph 2, include for : Item coverage",
              bleed="Operation and maintenance of 24-hour telephone line to receive enquiries "
                    "1.117 The items for operation and maintenance of 24-hour telephone line to "
                    "receive enquiries shall, in accordance with General Preambles paragraph 2, "
                    "include for : Item coverage"),
    ],
    "1.117": [
        _head("1.117", "a", "operatives and personnel"),
        _head("1.117", "b", "power supply"),
        _head("1.117", "c", "charges for equipment, accessories and telephone line"),
        _head("1.117", "d",
              "maintenance of equipment and accessories and equivalent replacement when the "
              "originals are damaged or unserviceable"),
        _head("1.117", "e",
              "preparing and submitting record to the Project Manager of each telephone call "
              "received and action being taken"),
        _head("1.117", "f",
              "provision and servicing of the accommodation of the information centre"),
        _head("1.117", "g",
              "complying with all the requirements as specified in PS Clauses 1.48(9). "
              "ENVIRONMENTAL MANAGEMENT",
              ps="PS 1.48(9)", cites="1.48", bleed="ENVIRONMENTAL MANAGEMENT"),
    ],
    # -----------------------------------------------------------------------
    # DIGITAL WORKS SUPERVISION SYSTEM — no BQ item mapped, see UNMAPPED
    # -----------------------------------------------------------------------
    "1.133": [
        # (a) is a cross-reference to another SMM clause, not to the specification, so there is
        # nothing for the index to resolve.
        _head("1.133", "a", "all as described in paragraph 1.28", ps="SMM S01 ¶1.28"),
        _head("1.133", "b",
              "Compliance with the requirements as specified in PS Clause 1.171 and PS Appendix "
              "1.50 and 1.50A for digital works supervision system (DWSS)",
              ps="PS 1.171 · PS Appendix 1.50, 1.50A", cites="1.171"),
        _head("1.133", "c",
              "providing replacement units of at least the same functional requirements where "
              "digital works supervision system (DWSS) is stolen or lost. SMART SITE SAFETY SYSTEM "
              "Note 1.134 Rates appearing in this section of the Method of",
              bleed="SMART SITE SAFETY SYSTEM Note 1.134 Rates appearing in this section of the "
                    "Method of"),
    ],
    # -----------------------------------------------------------------------
    # SMART SITE SAFETY SYSTEM — plan, review, network, components
    # -----------------------------------------------------------------------
    "1.140": [  # complete Implementation Plan for SSSS
        _head("1.140", "a",
              "prepare and develop the Implementation Plan for SSSS taking into account the "
              "comments made on the Implementation Plan for SSSS by the Project Manager and any "
              "other parties including but not limited to members of Site Safety Management "
              "Committee"),
        _head("1.140", "b",
              "all efforts, costs, expenses, loss or profit provided, incurred or allowed by the "
              "Contractor for striving to achieve the performance required by this item. Review, "
              "update and implement Implementation Plan for Smart Site Safety System 1.141 The "
              "item for review, update and implement Implementation Plan for Smart Site Safety "
              "System shall, in accordance with General Preambles paragraph 2, include for : Item "
              "coverage",
              bleed="Review, update and implement Implementation Plan for Smart Site Safety System "
                    "1.141 The item for review, update and implement Implementation Plan for Smart "
                    "Site Safety System shall, in accordance with General Preambles paragraph 2, "
                    "include for : Item coverage"),
    ],
    "1.141": [  # review, update and implement Implementation Plan for SSSS
        _head("1.141", "a",
              "review, update and revise the Implementation Plan for SSSS taking into account the "
              "comments made on the Implementation Plan for SSSS by the Project Manager and any "
              "other parties including but not limited to members of Site Safety Management "
              "Committee"),
        _head("1.141", "b",
              "implementation of the decisions and recommendations made by the Site Safety "
              "Management Committee on matters relating to implementation of SSSS"),
        _head("1.141", "c",
              "all efforts, costs, expenses, loss or profit provided, incurred or allowed by the "
              "Contractor for striving to achieve the performance required by this item. SITE "
              "COMMUNICATION NETWORK",
              bleed="SITE COMMUNICATION NETWORK"),
    ],
    "1.146": [  # provide site communication network
        _head("1.146", "a",
              "provide site telecommunication network systems which shall support mobile "
              "communication, fulfilling uptime requirements specified, with adequate data "
              "transmission speed, capacity, coverage, connectivity, stability and cybersecurity "
              "to ensure uninterrupted, reliable and effective real-time data transmission, "
              "including any video / audio signals, from any automation / remote sensing devices "
              "to their targeted operators / receivers / monitors / data storage devices for "
              "efficient implementation of the proposed SSSS components as required by the "
              "contract"),
        _head("1.146", "b",
              "all necessary measures and installations for ensuring the accessibility and "
              "compatibility among multiple telecommunication network systems with the "
              "corresponding SSSS components as required by the contract"),
        _head("1.146", "c",
              "provide all necessary power supply and associated infrastructures for the site "
              "telecommunication network systems"),
        _head("1.146", "d",
              "all efforts, costs, expenses, loss or profit provided, incurred or allowed by the "
              "Contractor for striving to achieve the performance required by this item. "
              "COMPONENTS OF SMART SITE SAFETY SYSTEM",
              bleed="COMPONENTS OF SMART SITE SAFETY SYSTEM"),
    ],
    "1.151": [  # components of Smart Site Safety System
        _head("1.151", "a",
              "provide all necessary submissions, plant, materials, installation, infrastructures, "
              "hardware, software, power supply, personnel, training, effort and take all "
              "necessary precautions and security measures to ensure continuous operation of all "
              "components of SSSS as required by the contract and for compliance of all "
              "requirements related to SSSS as required by the contract"),
        _head("1.151", "b",
              "replacement of worn out, defective or broken down parts, hardware and software of "
              "all components of SSSS as required by the contract"),
        _head("1.151", "c",
              "review and implement all necessary audits, security controls and measures to "
              "protect the confidentiality, integrity and availability of all data and information "
              "obtained, stored, processed or transmitted for the implementation and delivery of "
              "SSSS for compliance of all requirements related to SSSS as required by the "
              "contract"),
        _head("1.151", "d",
              "prepare report on implementation of SSSS components to Project Manager for "
              "discussion in the Site Safety Management Committee meetings as required by the "
              "contract"),
        _head("1.151", "e",
              "implement all necessary measures to ensure the operation and collection of data of "
              "SSSS and its components complying with the Personal Data (Privacy) Ordinance "
              "(Cap. 486). SAFETY TRAINING WITH VIRTUAL REALITY TECHNOLOGY",
              bleed="SAFETY TRAINING WITH VIRTUAL REALITY TECHNOLOGY"),
    ],
    # -----------------------------------------------------------------------
    # SAFETY TRAINING WITH VIRTUAL REALITY TECHNOLOGY — no BQ item mapped
    # -----------------------------------------------------------------------
    "1.156": [
        _head("1.156", "a",
              "provide safety training with Virtual Reality technology to workers engaging in the "
              "high risk activities specified in PS Clause 1.170",
              ps="PS 1.170", cites="1.170"),
        _head("1.156", "b", "the necessary training of personnel to conduct such talks"),
        # The source stops at "complying with" — what was to be complied with did not extract.
        _head("1.156", "c",
              "the necessary facilities, personnel and demonstration equipment for complying with",
              truncated="names what is to be complied with and the reference did not extract"),
        _head("1.156", "d",
              "preparation and submission of training programme and records, submission of "
              "certified monthly statements to the Project Manager"),
        _head("1.156", "e",
              "all necessary administration to arrange workers to participate in safety training "
              "with Virtual Reality technology"),
    ],
}


# ---------------------------------------------------------------------------
# What the pack prints that is NOT a coverage head
# ---------------------------------------------------------------------------
#: Sub-heads and clauses the pack prints "NOT USED". Recorded, never turned into heads: a checklist
#: line an estimator must tick to reach "all covered" is an obligation, and the pack says there is
#: none here. `¶1.14(o)` is counted as PRESENT when deriving the base-SMM gaps below, because it is
#: printed — its letter is spoken for, so it is not a hole where a base sub-head could sit.
NOT_USED: list[dict] = [
    {"clause": "1.14", "letter": "o", "printed": "NOT USED"},
    {"clause": "1.78", "letter": "", "printed": "NOT USED"},
]

#: The two "clauses" that came out of the PDF as the tail of a Delete-and-substitute instruction
#: whose substituted text did not extract. A head invented from either would be pure fabrication.
FRAGMENTS: list[dict] = [
    {"clause": "1.17", "extracted": "(i) and substitute : Unit 1.17",
     "reading": "the tail of a 'Delete sub-paragraph (i) and substitute …' amendment; the "
                "substituted text did not extract"},
    {"clause": "1.19", "extracted": "(i) and (ii) and substitute : Unit 1.19",
     "reading": "the tail of a 'Delete sub-paragraphs (i) and (ii) and substitute …' amendment; "
                "the substituted text did not extract"},
]

#: ¶1.14(z) arrived as one bullet carrying four sub-heads. Each of (aa)–(ac) is printed with its own
#: reference in the source, so they are split out.
#:
#: THE HEAD COUNT CLOSES ON THE SOURCE'S OWN, which is the check worth having. 264 printed bullets,
#: minus the one printed "NOT USED" and the two that are only fragments, plus the three this split
#: recovers, is 264 heads again. A transcription whose arithmetic does not close is one where
#: something was dropped quietly, so the sum is asserted rather than admired.
RUN_ON_SPLIT: list[dict] = [
    {"clause": "1.14", "printed_as": "z",
     "split_into": ["z", "aa", "ab", "ac"],
     "why": "the source bullet reads '… provision of temporary street lighting 1.14(aa) all costs "
            "and charges for providing fire fighting operations requirements; 1.14(ab) …; "
            "1.14(ac) …'. Each carries its own printed reference, so each is a sub-head."},
]

#: Anomalies that belong to the PACK, not to the reading of it. Left exactly as printed — tidying
#: them would make this file stop matching the document it claims to transcribe.
PUBLISHER_ANOMALIES: list[dict] = [
    {"where": "¶1.77(b), ¶1.85(b)", "what": "'accpetance' for 'acceptance', twice",
     "action": "left as printed"},
    {"where": "¶1.06", "what": "TWO sub-heads are lettered (k)", "action": "see SECOND_K"},
]

#: The second ¶1.06(k). The source names it ("office assistants…") and does not give its words, so
#: it is a KNOWN gap with a known letter — and known-but-unwritten is exactly the state this package
#: exists to keep visible rather than round off.
SECOND_K: dict = {
    "clause": "1.06", "letter": "k",
    "transcribed": "additional insurance cover for working outside the Site",
    "missing": "the pack prints a SECOND sub-head lettered (k), beginning 'office assistants…'. "
               "Its full text was not transcribed and is not invented here.",
}


# ---------------------------------------------------------------------------
# The gap the pack cannot close, derived from the letters rather than asserted
# ---------------------------------------------------------------------------
def _ordinal(letter: str) -> int:
    """``a`` → 1 … ``z`` → 26, ``aa`` → 27. Bijective base-26, which is how clauses letter."""
    value = 0
    for char in letter:
        value = value * 26 + (ord(char) - 96)
    return value


def _letter(value: int) -> str:
    """The inverse of :func:`_ordinal`."""
    out = ""
    while value > 0:
        value, remainder = divmod(value - 1, 26)
        out = chr(97 + remainder) + out
    return out


def _interior_gaps(letters: set[str]) -> list[str]:
    """The letters missing BETWEEN the ones the pack prints.

    INTERIOR ONLY, and the restraint is the point. ¶1.06 printing (c), (f), (h)–(p), (w) proves the
    pack has no (a), (b), (d), (e), (g) or (q)–(v) — a clause does not skip a letter, so those
    sub-heads are in the base SMM 1992. But a clause running (a)–(e) with no holes proves NOTHING
    about whether the base carries an (f): the pack simply stops. Claiming otherwise would turn a
    real deduction into a guess, so the tail is left to `PARTIAL_BY_CONSTRUCTION`, which says the
    honest thing about every list here.
    """
    if not letters:
        return []
    present = {_ordinal(letter) for letter in letters}
    return [_letter(n) for n in range(1, max(present)) if n not in present]


def _printed_letters(clause: str) -> set[str]:
    """Every letter the pack prints under one clause, heads and NOT-USED markers alike."""
    return ({head.key.rsplit(".", 1)[-1] for head in CLAUSES.get(clause, [])}
            | {row["letter"] for row in NOT_USED
               if row["clause"] == clause and row["letter"]})


#: Per clause, the sub-heads that are real, binding and NOT in this pack — proved by the lettering.
#: Ten of the 42 clauses have such holes; the rest are printed contiguously from (a), which says
#: nothing either way about what follows their last letter.
BASE_SMM_GAPS: dict[str, list[str]] = {
    clause: gaps for clause in CLAUSES
    if (gaps := _interior_gaps(_printed_letters(clause)))
}

def heads_for_clauses(*clauses: str) -> list[CoverageHead]:
    """The heads of one or more clauses, in the order the pack prints them.

    A Bill 1 item is often governed by a RANGE — the core and sample store is erected under ¶1.109,
    serviced under ¶1.110 and handed back under ¶1.111, and the BQ bills it as one item. Raises on
    an unknown clause rather than returning an empty list, because a typo that silently produces "no
    coverage" is the failure this whole package is built against.
    """
    out: list[CoverageHead] = []
    for clause in clauses:
        if clause not in CLAUSES:
            raise KeyError(f"SMM S01 ¶{clause} is not transcribed — check the reference, and see "
                           f"FRAGMENTS for the two that could not be")
        out.extend(CLAUSES[clause])
    return out
