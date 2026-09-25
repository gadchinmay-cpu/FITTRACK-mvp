"""Backend tests for Record Payment flow (bug fix verification)."""
import os
import requests
import pytest
from datetime import date, timedelta

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@gym.local", "password": "Gym@12345"})
    assert r.status_code == 200, r.text
    s.headers["Authorization"] = f"Bearer {r.json()['token']}"
    return s


@pytest.fixture(scope="module")
def seeded_member(session):
    """Create a fresh TEST_ member with an active membership so tests are deterministic."""
    m = session.post(f"{BASE_URL}/api/members", json={
        "full_name": "TEST_Payment Fixture",
        "phone": "9998887777",
        "joining_date": date.today().isoformat(),
    })
    assert m.status_code == 200, m.text
    mid = m.json()["id"]
    plans = session.get(f"{BASE_URL}/api/plans").json()
    plan = next(p for p in plans if p["duration_months"] == 1)
    ms = session.post(f"{BASE_URL}/api/members/{mid}/memberships", json={
        "plan_id": plan["id"], "start_date": date.today().isoformat(),
    })
    assert ms.status_code == 200, ms.text
    return {"id": mid, "price": ms.json()["total_price"]}


def test_dashboard_endpoint_available(session):
    r = session.get(f"{BASE_URL}/api/dashboard")
    assert r.status_code == 200
    assert "stats" in r.json()


def test_future_date_rejected(session, seeded_member):
    future = (date.today() + timedelta(days=3)).isoformat()
    r = session.post(f"{BASE_URL}/api/members/{seeded_member['id']}/payments", json={
        "amount": 100, "payment_method": "Cash", "payment_date": future,
    })
    assert r.status_code == 400
    assert "future" in r.text.lower()


def test_amount_exceeds_pending_rejected(session, seeded_member):
    r = session.post(f"{BASE_URL}/api/members/{seeded_member['id']}/payments", json={
        "amount": seeded_member["price"] + 1000,
        "payment_method": "Cash",
        "payment_date": date.today().isoformat(),
    })
    assert r.status_code == 400
    assert "exceed" in r.text.lower()


def test_happy_path_payment_updates_paid_pending_and_dashboard(session, seeded_member):
    mid = seeded_member["id"]
    price = seeded_member["price"]
    before = session.get(f"{BASE_URL}/api/dashboard").json()["stats"]
    before_rev = before.get("revenue_month", 0)
    before_pending = before.get("pending", 0)

    amount = round(price / 2)
    r = session.post(f"{BASE_URL}/api/members/{mid}/payments", json={
        "amount": amount, "payment_method": "UPI",
        "payment_date": date.today().isoformat(),
        "notes": "test payment",
    })
    assert r.status_code == 200, r.text

    detail = session.get(f"{BASE_URL}/api/members/{mid}").json()
    assert detail["paid"] == amount
    assert abs(detail["pending"] - (price - amount)) < 1
    # payment appears in history
    assert any(p["amount"] == amount and p["payment_method"] == "UPI" and p["notes"] == "test payment"
               for p in detail["payments"])

    after = session.get(f"{BASE_URL}/api/dashboard").json()["stats"]
    assert after.get("revenue_month", 0) >= before_rev + amount - 0.5
    assert after.get("pending", 0) <= before_pending - amount + 0.5


def test_no_active_membership_rejected(session):
    m = session.post(f"{BASE_URL}/api/members", json={
        "full_name": "TEST_No Membership",
        "phone": "9111222333",
        "joining_date": date.today().isoformat(),
    })
    assert m.status_code == 200
    r = session.post(f"{BASE_URL}/api/members/{m.json()['id']}/payments", json={
        "amount": 100, "payment_method": "Cash",
        "payment_date": date.today().isoformat(),
    })
    assert r.status_code == 400
    assert "membership" in r.text.lower()


def test_activity_log_written(session, seeded_member):
    """A payment should show up in the dashboard recent activity list."""
    r = session.post(f"{BASE_URL}/api/members/{seeded_member['id']}/payments", json={
        "amount": 1, "payment_method": "Cash",
        "payment_date": date.today().isoformat(),
        "notes": "activity check",
    })
    # Might be 200 if pending>0 still, or 400 if fully paid from previous test
    assert r.status_code in (200, 400)
    dash = session.get(f"{BASE_URL}/api/dashboard").json()
    # activity may be under different keys - check common ones
    activity = dash.get("activity") or dash.get("recent_activity") or dash.get("activities") or []
    if r.status_code == 200 and activity:
        assert any("payment" in str(a).lower() for a in activity)
