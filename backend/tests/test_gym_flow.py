import os
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://fittrack-mvp-12.preview.emergentagent.com").rstrip("/")


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    login = s.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@gym.local", "password": "Gym@12345"})
    assert login.status_code == 200, login.text
    s.headers["Authorization"] = f"Bearer {login.json()['token']}"
    return s


def test_auth_protection_and_subject(session):
    assert requests.get(f"{BASE_URL}/api/dashboard").status_code == 401
    me = session.get(f"{BASE_URL}/api/auth/me")
    assert me.status_code == 200 and me.json()["sub"] == "1"
    dashboard = session.get(f"{BASE_URL}/api/dashboard")
    assert dashboard.status_code == 200 and dashboard.json()["stats"]["total_members"] >= 15


def test_member_membership_multiple_payments_and_overpayment(session):
    member = session.post(f"{BASE_URL}/api/members", json={"full_name": "TEST Flow Member", "phone": "9912345678", "joining_date": "2026-03-10"})
    assert member.status_code == 200, member.text
    m = member.json(); member_id = m["id"]
    plans = session.get(f"{BASE_URL}/api/plans"); assert plans.status_code == 200
    plan = next(p for p in plans.json() if p["duration_months"] == 3)
    membership = session.post(f"{BASE_URL}/api/members/{member_id}/memberships", json={"plan_id": plan["id"], "start_date": "2026-03-10"})
    assert membership.status_code == 200 and membership.json()["expiry_date"] == "2026-06-09"
    price = membership.json()["total_price"]
    for amount in (1000, price - 1000):
        payment = session.post(f"{BASE_URL}/api/members/{member_id}/payments", json={"amount": amount, "payment_date": "2026-03-10", "payment_method": "Cash"})
        assert payment.status_code == 200, payment.text
    detail = session.get(f"{BASE_URL}/api/members/{member_id}").json()
    assert detail["paid"] == price and detail["pending"] == 0
    over = session.post(f"{BASE_URL}/api/{'members'}/{member_id}/payments", json={"amount": 1, "payment_date": "2026-03-10", "payment_method": "Cash"})
    assert over.status_code == 400


def test_search_filters_reports(session):
    search = session.get(f"{BASE_URL}/api/members", params={"q": "TEST Flow Member"})
    assert search.status_code == 200 and any(m["full_name"] == "TEST Flow Member" for m in search.json())
    for filter_value in ("7", "30", "expired"):
        response = session.get(f"{BASE_URL}/api/expiring", params={"filter": filter_value})
        assert response.status_code == 200 and isinstance(response.json(), list)
    reports = session.get(f"{BASE_URL}/api/reports")
    assert reports.status_code == 200 and "total_revenue" in reports.json() and isinstance(reports.json()["payments"], list)