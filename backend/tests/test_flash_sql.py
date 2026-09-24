"""claim_flash_offers(): who gets offered what, exactly once (rolled back)."""
from tests.conftest import insert_donation

BOT = "test_bot"


def individual(conn, lat, lng, chat=-880001, via=BOT, active=True, radius=3000):
    return conn.execute(
        "insert into recipients (name, type, lat, lng, service_radius_m, telegram_chat_id, via_bot, active) "
        "values ('Test Person', 'individual', %s, %s, %s, %s, %s, %s) returning id",
        (lat, lng, radius, chat, via, active),
    ).fetchone()["id"]


MINE: set = set()  # listings created by the current test (the shared DB also holds real ones)


def escalated(conn, lat=10.7250, lng=122.5575, **kw):
    d = insert_donation(conn, lat=lat, lng=lng, radius_m=8000, status="escalated", **kw)
    MINE.add(d)
    return d


def offers(conn, bot=BOT):
    rows = conn.execute("select * from claim_flash_offers(%s)", (bot,)).fetchall()
    return [r for r in rows if r["donation_id"] in MINE]


def test_nearby_individual_gets_offer_once(conn):
    near = individual(conn, 10.7300, 122.5600)  # ~600 m away
    d = escalated(conn)
    first = offers(conn)
    assert [(o["donation_id"], o["recipient_id"]) for o in first] == [(d, near)]
    assert first[0]["chat_id"] == -880001 and first[0]["distance_m"] < 1000
    assert offers(conn) == []  # second run: already offered
    count = conn.execute("select flash_offer_count from donations where id = %s", (d,)).fetchone()
    assert count["flash_offer_count"] == 1


def test_out_of_personal_range_not_offered(conn):
    individual(conn, 10.6965, 122.5645, radius=3000)  # City Proper, ~3.3 km away
    escalated(conn)
    assert offers(conn) == []


def test_only_escalated_listings(conn):
    individual(conn, 10.7300, 122.5600)
    MINE.add(insert_donation(conn, lat=10.7250, lng=122.5575, radius_m=8000))  # still 'posted'
    assert offers(conn) == []


def test_inactive_and_other_bot_skipped(conn):
    individual(conn, 10.7300, 122.5600, chat=-880002, active=False)
    individual(conn, 10.7300, 122.5600, chat=-880003, via="other_bot")
    escalated(conn)
    assert offers(conn) == []
    assert len(offers(conn, bot="other_bot")) == 1  # that bot's worker does send it


def test_expired_escalated_not_offered(conn):
    individual(conn, 10.7300, 122.5600)
    escalated(conn, expires_at_sql="now() - interval '1 minute'")
    assert offers(conn) == []


def test_counts_multiple_people(conn):
    individual(conn, 10.7300, 122.5600, chat=-880004)
    individual(conn, 10.7200, 122.5550, chat=-880005)
    d = escalated(conn)
    assert len(offers(conn)) == 2
    assert conn.execute("select flash_offer_count from donations where id = %s", (d,)).fetchone()["flash_offer_count"] == 2


def test_not_offered_own_food(conn):
    """Someone who is both a donor and on the flash list never gets their own listing."""
    donor = conn.execute(
        "insert into donors (name, type, lat, lng, telegram_chat_id) values ('Self', 'household', 10.73, 122.56, -880009) "
        "returning id"
    ).fetchone()["id"]
    individual(conn, 10.7300, 122.5600, chat=-880009)
    other = individual(conn, 10.7300, 122.5600, chat=-880010)
    escalated(conn, donor_id=donor, donor_name="Self")
    assert [o["recipient_id"] for o in offers(conn)] == [other]
