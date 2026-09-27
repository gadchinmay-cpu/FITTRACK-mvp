"""Backend tests for the new POST /api/members/{id}/renew endpoint."""
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
def plans(session):
    r = session.get(f"{BASE_URL}/api/plans")
    assert r.status_code == 200
    return r.json()


def _create_member(session, name_suffix, with_expired_plan=False, with_pending=False, plan=None):
    m = session.post(f"{BASE_URL}/api/members", json={
        "full_name": f"TEST_Renew_{name_suffix}",
        "phone": "9" + str(abs(hash(name_suffix)))[:9],
        "joining_date": date.today().isoformat(),
    })
    assert m.status_code == 200, m.text
    mid = m.json()["id"]
    if with_expired_plan and plan:
        # Add membership then force expiry using sqlite direct not possible; simulate by
        # adding a plan and updating start=very old date via memberships endpoint isn't supported.
        # We'll insert via /memberships (starts today) then manually shift via reports? Not possible.
        # Instead use the seeded logic - add a new membership starting long ago via /memberships
        # (endpoint only accepts start_date and derives expiry). So set start well in past.
        past = (date.today() - timedelta(days=400)).isoformat()
        ms = session.post(f"{BASE_URL}/api/members/{mid}/memberships", json={
            "plan_id": plan["id"], "start_date": past,
        })
        assert ms.status_code == 200, ms.text
        if with_pending:
            # Pending exists by default (no payment made yet) since total_price>0 and paid=0
            pass
    return mid


def test_renew_case2_expired_no_pending(session, plans):
    """Case 2: expired member, no pending - fresh renewal only."""
    plan = next(p for p in plans if p["duration_months"] == 1)
    mid = _create_member(session, "case2", with_expired_plan=True, plan=plan)
    # Settle existing pending first so it's zero
    detail = session.get(f"{BASE_URL}/api/members/{mid}").json()
    if detail["pending"] > 0:
        # Pay it off via /payments to zero
        session.post(f"{BASE_URL}/api/members/{mid}/payments", json={
            "amount": detail["pending"], "payment_method": "Cash",
            "payment_date": date.today().isoformat(),
        })
    detail = session.get(f"{BASE_URL}/api/members/{mid}").json()
    assert detail["status"] == "EXPIRED"
    assert detail["pending"] == 0

    new_plan = next(p for p in plans if p["duration_months"] == 3)
    r = session.post(f"{BASE_URL}/api/members/{mid}/renew", json={
        "plan_id": new_plan["id"],
        "start_date": date.today().isoformat(),
    })
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "ACTIVE"
    assert data["plan_id"] == new_plan["id"]
    assert data["total_price"] == new_plan["price"]
    assert data["paid"] == 0
    assert data["pending"] == new_plan["price"]


def test_renew_case3_expired_with_pending_and_initial_payment(session, plans):
    """Case 3: expired + pending + initial payment (combined settle & renew)."""
    plan = next(p for p in plans if p["duration_months"] == 1)
    mid = _create_member(session, "case3", with_expired_plan=True, with_pending=True, plan=plan)
    detail = session.get(f"{BASE_URL}/api/members/{mid}").json()
    assert detail["pending"] > 0

    pending_before = detail["pending"]
    new_plan = next(p for p in plans if p["duration_months"] == 3)
    payload = {
        "plan_id": new_plan["id"],
        "start_date": date.today().isoformat(),
        "pending_settlement": {
            "amount": pending_before,
            "payment_method": "UPI",
            "payment_date": date.today().isoformat(),
            "notes": "settling before renew"
        },
        "initial_payment": {
            "amount": 1000,
            "payment_method": "Cash",
            "payment_date": date.today().isoformat(),
            "notes": "deposit"
        }
    }
    r = session.post(f"{BASE_URL}/api/members/{mid}/renew", json=payload)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "ACTIVE"
    assert data["plan_id"] == new_plan["id"]
    # detail-paid reflects only NEW membership
    assert data["paid"] == 1000
    assert data["pending"] == new_plan["price"] - 1000

    detail = session.get(f"{BASE_URL}/api/members/{mid}").json()
    # payment history contains both settlement and initial payment
    notes = [p.get("notes") for p in detail["payments"]]
    assert "settling before renew" in notes
    assert "deposit" in notes


def test_renew_inactive_plan_rejected(session, plans):
    mid = _create_member(session, "badplan")
    r = session.post(f"{BASE_URL}/api/members/{mid}/renew", json={
        "plan_id": 99999, "start_date": date.today().isoformat(),
    })
    assert r.status_code == 400
    assert "plan" in r.text.lower()


def test_renew_expiry_before_start_rejected(session, plans):
    plan = plans[0]
    mid = _create_member(session, "badexpiry")
    r = session.post(f"{BASE_URL}/api/members/{mid}/renew", json={
        "plan_id": plan["id"],
        "start_date": date.today().isoformat(),
        "expiry_date": (date.today() - timedelta(days=5)).isoformat(),
    })
    assert r.status_code == 400
    assert "expiry" in r.text.lower()


def test_renew_settlement_exceeds_pending(session, plans):
    plan = next(p for p in plans if p["duration_months"] == 1)
    mid = _create_member(session, "over_settle", with_expired_plan=True, with_pending=True, plan=plan)
    detail = session.get(f"{BASE_URL}/api/members/{mid}").json()
    new_plan = next(p for p in plans if p["duration_months"] == 3)
    r = session.post(f"{BASE_URL}/api/members/{mid}/renew", json={
        "plan_id": new_plan["id"], "start_date": date.today().isoformat(),
        "pending_settlement": {
            "amount": detail["pending"] + 5000,
            "payment_method": "Cash",
            "payment_date": date.today().isoformat(),
        }
    })
    assert r.status_code == 400
    assert "exceed" in r.text.lower() or "pending" in r.text.lower()


def test_renew_future_settlement_date_rejected(session, plans):
    plan = next(p for p in plans if p["duration_months"] == 1)
    mid = _create_member(session, "future_settle", with_expired_plan=True, with_pending=True, plan=plan)
    new_plan = next(p for p in plans if p["duration_months"] == 3)
    r = session.post(f"{BASE_URL}/api/members/{mid}/renew", json={
        "plan_id": new_plan["id"], "start_date": date.today().isoformat(),
        "pending_settlement": {
            "amount": 100,
            "payment_method": "Cash",
            "payment_date": (date.today() + timedelta(days=3)).isoformat(),
        }
    })
    assert r.status_code == 400
    assert "future" in r.text.lower()


def test_renew_initial_payment_exceeds_fee(session, plans):
    plan = next(p for p in plans if p["duration_months"] == 1)
    mid = _create_member(session, "over_initial")
    r = session.post(f"{BASE_URL}/api/members/{mid}/renew", json={
        "plan_id": plan["id"], "start_date": date.today().isoformat(),
        "total_price": 1000,
        "initial_payment": {
            "amount": 2000,
            "payment_method": "Cash",
            "payment_date": date.today().isoformat(),
        }
    })
    assert r.status_code == 400
    assert "exceed" in r.text.lower()


def test_renew_settlement_without_current_membership(session, plans):
    """Should fail if member has no existing membership but tries pending_settlement."""
    plan = plans[0]
    mid = _create_member(session, "no_current")
    r = session.post(f"{BASE_URL}/api/members/{mid}/renew", json={
        "plan_id": plan["id"], "start_date": date.today().isoformat(),
        "pending_settlement": {
            "amount": 100, "payment_method": "Cash",
            "payment_date": date.today().isoformat(),
        }
    })
    assert r.status_code == 400
    assert "current" in r.text.lower() or "membership" in r.text.lower()


def test_renew_writes_activity_log(session, plans):
    plan = next(p for p in plans if p["duration_months"] == 1)
    mid = _create_member(session, "activitylog")
    new_plan = next(p for p in plans if p["duration_months"] == 3)
    r = session.post(f"{BASE_URL}/api/members/{mid}/renew", json={
        "plan_id": new_plan["id"], "start_date": date.today().isoformat(),
    })
    assert r.status_code == 200
    dash = session.get(f"{BASE_URL}/api/dashboard").json()
    activities = dash.get("activities", [])
    assert any(a.get("action") == "renewed" for a in activities)
