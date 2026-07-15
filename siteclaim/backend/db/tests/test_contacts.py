"""The subcontractor address book (Phase A) — contacts keyed by firm + trade."""

from db import store


def test_contact_for_resolves_a_seeded_firm(conn):
    contact = store.contact_for(conn, "F-EL-02", "electrical")
    assert contact is not None
    assert contact.firm_id == "F-EL-02"
    assert contact.email.endswith(".example")  # illustrative, fabricated (honest)


def test_contact_for_unknown_firm_or_trade_is_none(conn):
    assert store.contact_for(conn, "F-EL-02", "fire_services") is None  # firm doesn't do that trade
    assert store.contact_for(conn, "NOPE-00", "electrical") is None


def test_all_contacts_lists_every_seeded_entry(conn):
    contacts = store.all_contacts(conn)
    assert contacts
    assert all(c.email for c in contacts)  # a contact with no email is never seeded
    # keyed by (firm_id, trade): no duplicate key
    keys = [(c.firm_id, c.trade) for c in contacts]
    assert len(keys) == len(set(keys))


# -- recipient resolution: contacts override, else the register enquiry_email -----------------
def _register_firm_without_contact(conn):
    """A firm that carries a register ``enquiry_email`` but no address-book row — the common case
    the recipient fix rescues (previously reported 'no contact email')."""
    return conn.execute(
        "SELECT f.firm_id, f.enquiry_email FROM firms f "
        "LEFT JOIN contacts c ON c.firm_id = f.firm_id "
        "WHERE f.enquiry_email != '' AND c.firm_id IS NULL LIMIT 1"
    ).fetchone()


def test_firm_enquiry_email_reads_the_register_address(conn):
    row = _register_firm_without_contact(conn)
    assert row is not None  # the register carries enquiry addresses
    assert store.firm_enquiry_email(conn, row["firm_id"]) == row["enquiry_email"]
    assert store.firm_enquiry_email(conn, "NOPE-00") is None  # unknown firm -> none


def test_recipient_email_falls_back_to_the_register_enquiry_email(conn):
    # THE BUG'S FIX: a firm with only firms.enquiry_email (no contacts row) still resolves.
    row = _register_firm_without_contact(conn)
    assert store.contact_for(conn, row["firm_id"], "general") is None
    assert store.recipient_email(conn, row["firm_id"], "general") == row["enquiry_email"]


def test_recipient_email_prefers_a_contact_override_over_enquiry_email(conn):
    # F-EL-02 carries an address-book contact; it wins over any register address.
    assert store.recipient_email(conn, "F-EL-02", "electrical") == store.contact_for(conn, "F-EL-02", "electrical").email


def test_recipient_email_is_none_when_neither_source_has_an_address(conn):
    assert store.recipient_email(conn, "NOPE-00", "electrical") is None  # reported by the caller, never a silent To


def test_upsert_contact_sets_then_overrides_and_wins_the_recipient_chain(tmp_path):
    from db import seed

    path = tmp_path / "contacts.db"
    seed.build_database(path)  # a dedicated DB — never mutate the shared session seed
    conn = store.get_connection(path)
    try:
        row = _register_firm_without_contact(conn)
        fid = row["firm_id"]
        assert store.recipient_email(conn, fid, "general") == row["enquiry_email"]  # register first

        saved = store.upsert_contact(conn, fid, "general", "desk@override.example", "Buying Desk")
        assert saved.email == "desk@override.example" and saved.contact_name == "Buying Desk"
        assert store.recipient_email(conn, fid, "general") == "desk@override.example"  # override now wins

        store.upsert_contact(conn, fid, "general", "desk2@override.example")  # update in place, no dup key
        assert store.recipient_email(conn, fid, "general") == "desk2@override.example"
        assert len([c for c in store.all_contacts(conn) if c.firm_id == fid and c.trade == "general"]) == 1
    finally:
        conn.close()
