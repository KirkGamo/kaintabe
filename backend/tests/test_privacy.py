"""R3d: public feed is approximate; exact details only via /api/map for the right Telegram user."""
import httpx
import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app
from app.services import repo
from tests.conftest import insert_donation

client = TestClient(app)
DONOR_TG, PERSON_TG, STRANGER_TG = -120001, -120002, -120003
GRID = 0.0045


def on_grid_center(v: float) -> bool:
    cells = v / GRID - 0.5
    return abs(cells - round(cells)) < 1e-6


# --- public_listings mirror (rolled back) --------------------------------------------

def test_public_mirror_is_approximate_and_follows_changes(conn):
    d = insert_donation(conn, lat=10.72278, lng=122.54766, food_type="Mirror test")
    pub = conn.execute("select * from public_listings where id = %s", (d,)).fetchone()
    assert pub["food_type"] == "Mirror test" and pub["status"] == "posted"
    assert on_grid_center(pub["lat"]) and on_grid_center(pub["lng"])
    assert (pub["lat"], pub["lng"]) != (10.72278, 122.54766)
    assert abs(pub["lat"] - 10.72278) <= GRID / 2 and abs(pub["lng"] - 122.54766) <= GRID / 2
    assert not {"donor_name", "photo_url", "donor_id", "quantity"} & set(pub)  # nothing identifying

    conn.execute("update donations set status = 'withdrawn', search_radius_m = 4000 where id = %s", (d,))
    pub = conn.execute("select status, search_radius_m from public_listings where id = %s", (d,)).fetchone()
    assert (pub["status"], pub["search_radius_m"]) == ("withdrawn", 4000)

    conn.execute("delete from donations where id = %s", (d,))
    assert conn.execute("select 1 from public_listings where id = %s", (d,)).fetchone() is None


# --- /api/map roles -------------------------------------------------------------------

@pytest.fixture
def world(api_orgs):
    """A donor (Telegram DONOR_TG) with one listing near Jaro and one near City Proper,
    and an individual (PERSON_TG) who claimed a third listing near Jaro."""
    ids, headers = api_orgs
    donor = repo.create_donor(DONOR_TG, "Privacy Test Donor", "household", 10.7250, 122.5575)
    with db.connect() as conn:
        near = insert_donation(conn, donor_id=donor["id"], donor_name=donor["name"], food_type="Near Jaro",
                               lat=10.7250, lng=122.5575, radius_m=2000)
        far = insert_donation(conn, donor_id=donor["id"], donor_name=donor["name"], food_type="Near City Proper",
                              lat=10.6970, lng=122.5650, radius_m=2000)
        flash = insert_donation(conn, food_type="Flash claimed", lat=10.7255, lng=122.5580, radius_m=8000,
                                status="escalated")
    person = repo.upsert_individual(PERSON_TG, "Neighbor", 10.7260, 122.5585, "api_test_bot")
    repo.claim_donation(str(flash), str(person["id"]))
    yield ids, headers, {"near": near, "far": far, "flash": flash}
    with db.connect() as conn:
        conn.execute("delete from claims where donation_id = any(%s::uuid[])", ([str(near), str(far), str(flash)],))
        conn.execute("delete from donations where id = any(%s::uuid[])", ([str(near), str(far), str(flash)],))
        conn.execute("delete from recipients where telegram_chat_id = %s", (PERSON_TG,))
        conn.execute("delete from donors where telegram_chat_id = %s", (DONOR_TG,))


def view(headers):
    res = client.get("/api/map", headers=headers)
    assert res.status_code == 200, res.text
    return res.json()


def ids_of(rows):
    return {r["id"] for r in rows}


def test_org_sees_exact_details_only_within_its_reach(world):
    _, headers, L = world
    v = view(headers("jaro"))
    assert v["org"]["name"] == "API Org jaro" and v["donor"] is None and v["individual"] is None
    got = ids_of(v["in_range"])
    assert str(L["near"]) in got and str(L["far"]) not in got
    near = next(r for r in v["in_range"] if r["id"] == str(L["near"]))
    assert near["donor_name"] == "Privacy Test Donor" and near["lat"] == 10.7250  # exact, for pickup
    assert v["my_listings"] == []


def test_donor_sees_only_their_own_listings(world):
    _, headers, L = world
    v = view(headers(tg_id=DONOR_TG))
    assert v["donor"]["name"] == "Privacy Test Donor" and v["org"] is None
    assert ids_of(v["my_listings"]) == {str(L["near"]), str(L["far"])}
    assert v["in_range"] == [] and v["my_pickups"] == []


def test_individual_sees_only_their_claimed_offer(world):
    _, headers, L = world
    v = view(headers(tg_id=PERSON_TG))
    assert v["individual"] is not None and v["org"] is None and v["donor"] is None
    assert ids_of(v["my_pickups"]) == {str(L["flash"])} and v["my_pickups"][0]["claim_id"]
    assert v["in_range"] == [] and v["my_listings"] == []


def test_stranger_sees_nothing_exact_and_browser_is_refused(world):
    _, headers, _ = world
    v = view(headers(tg_id=STRANGER_TG))
    assert (v["org"], v["donor"], v["individual"]) == (None, None, None)
    assert v["in_range"] == v["my_pickups"] == v["my_listings"] == []
    assert client.get("/api/map").status_code == 401


# --- take down from the web --------------------------------------------------------------


def test_donor_sees_who_claimed_but_an_individual_only_approximately(world):
    """A kitchen's spot is public; an individual's (usually their home) is only a ~500 m cell,
    and the donor sees how many neighbors are nearby, never where they are."""
    ids, headers, L = world
    person = repo.get_individual(PERSON_TG, "api_test_bot")
    repo.claim_donation(str(L["near"]), str(person["id"]))
    repo.claim_donation(str(L["far"]), ids["cityproper"])
    v = view(headers(tg_id=DONOR_TG))
    rows = {r["id"]: r for r in v["my_listings"]}

    by_person = rows[str(L["near"])]
    assert by_person["claimer_type"] == "individual" and by_person["claimer_name"] == "Neighbor"
    assert on_grid_center(by_person["claimer_lat"]) and on_grid_center(by_person["claimer_lng"])
    assert (by_person["claimer_lat"], by_person["claimer_lng"]) != (person["lat"], person["lng"])
    assert 0 < by_person["claimer_distance_m"] < 500

    by_org = rows[str(L["far"])]
    assert by_org["claimer_type"] == "partner_org" and (by_org["claimer_lat"], by_org["claimer_lng"]) == (10.6965, 122.5645)

    assert v["donor"]["neighbors_nearby"] >= 1  # PERSON_TG lives ~150 m away


def test_individual_view_includes_their_pickup_range(world):
    _, headers, _ = world
    assert view(headers(tg_id=PERSON_TG))["individual"]["radius_m"] == 3000

def test_donor_can_take_down_own_unclaimed_listing(world):
    _, headers, L = world
    res = client.post(f"/api/listings/{L['far']}/withdraw", headers=headers(tg_id=DONOR_TG))
    assert res.status_code == 200 and res.json()["status"] == "withdrawn"
    assert client.post(f"/api/listings/{L['near']}/withdraw", headers=headers("jaro")).status_code == 403  # not a donor
    assert client.post(f"/api/listings/{L['flash']}/withdraw", headers=headers(tg_id=DONOR_TG)).status_code == 409  # not theirs / claimed
    assert client.post(f"/api/listings/{L['near']}/withdraw").status_code == 401


# --- what the browser's public key can read ----------------------------------------------

def _lockdown_applied() -> bool:
    with db.connect() as conn:
        return conn.execute("select 1 from schema_migrations where name = '018_privacy_lockdown.sql'").fetchone() is not None


def test_public_key_reads_approximate_feed(frontend_env):
    base = frontend_env["VITE_SUPABASE_URL"].rstrip("/") + "/rest/v1"
    key = frontend_env["VITE_SUPABASE_ANON_KEY"]
    h = {"apikey": key, "Authorization": f"Bearer {key}"}
    with db.connect() as conn:  # a listing of our own (the live database may be empty)
        d = insert_donation(conn, food_type="Public feed test", lat=10.72278, lng=122.54766)
    try:
        rows = httpx.get(f"{base}/public_listings?select=*&id=eq.{d}", headers=h).json()
        assert len(rows) == 1 and on_grid_center(rows[0]["lat"]) and on_grid_center(rows[0]["lng"])
        assert "donor_name" not in rows[0] and "photo_url" not in rows[0]
        assert httpx.post(f"{base}/rpc/nearby_donations", headers=h,
                          json={"p_recipient_id": rows[0]["id"]}).status_code in (401, 403, 404)
    finally:
        with db.connect() as conn:
            conn.execute("delete from donations where id = %s", (d,))


@pytest.mark.skipif(not _lockdown_applied(), reason="018 lockdown is applied at deploy time")
def test_public_key_cannot_read_exact_data(frontend_env):
    base = frontend_env["VITE_SUPABASE_URL"].rstrip("/") + "/rest/v1"
    key = frontend_env["VITE_SUPABASE_ANON_KEY"]
    h = {"apikey": key, "Authorization": f"Bearer {key}"}
    assert httpx.get(f"{base}/donations?select=id,lat,lng,donor_name&limit=5", headers=h).json() == []
    assert httpx.get(f"{base}/claims?select=id&limit=5", headers=h).json() == []
    types = {r["type"] for r in httpx.get(f"{base}/recipients?select=type", headers=h).json()}
    assert types <= {"partner_org"}  # individuals' homes never public
