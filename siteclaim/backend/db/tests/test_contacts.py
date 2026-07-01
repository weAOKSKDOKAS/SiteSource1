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
