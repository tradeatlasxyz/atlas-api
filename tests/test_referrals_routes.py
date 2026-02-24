from fastapi.testclient import TestClient

from api.main import app
import api.routes.admin as admin_routes
import api.routes.referrals as referrals_routes


VALID_ADDRESS = "0x1234567890abcdef1234567890abcdef12345678"
VALID_VAULT = "0xabcdefabcdefabcdefabcdefabcdefabcdefabcd"


def test_referral_summary_invalid_address() -> None:
    client = TestClient(app)
    response = client.get("/api/referrals/not-an-address")
    assert response.status_code == 422


def test_referral_summary_normalizes_address(monkeypatch) -> None:
    captured = {}

    async def fake_summary(_db, address: str):
        captured["address"] = address
        return {
            "address": address,
            "referral_codes": [],
            "referred_users": 0,
            "referred_deposits": 0,
            "referred_volume_wei": "0",
            "total_claimed_wei": "0",
            "latest_attributions": [],
            "latest_claims": [],
        }

    monkeypatch.setattr(referrals_routes, "get_referral_summary", fake_summary)

    client = TestClient(app)
    mixed_case_address = VALID_ADDRESS[:2] + VALID_ADDRESS[2:].upper()
    response = client.get(f"/api/referrals/{mixed_case_address}")
    assert response.status_code == 200
    data = response.json()
    assert data["address"] == VALID_ADDRESS
    assert data["referredDeposits"] == 0
    assert captured["address"] == VALID_ADDRESS


def test_referral_stats_empty_state(monkeypatch) -> None:
    async def fake_stats(_db):
        return {
            "referred_deposits": 0,
            "unique_referrers": 0,
            "unique_referred_users": 0,
            "referred_volume_wei": "0",
            "claimed_rewards_wei": "0",
        }

    monkeypatch.setattr(referrals_routes, "get_referral_stats", fake_stats)

    client = TestClient(app)
    response = client.get("/api/referrals/stats")
    assert response.status_code == 200
    assert response.json()["referredDeposits"] == 0


def test_referral_vault_allocation_shape(monkeypatch) -> None:
    async def fake_allocation(_db, vault_address: str):
        return {
            "vault_address": vault_address,
            "total_volume_wei": "1000",
            "allocations": [
                {
                    "referrer_address": VALID_ADDRESS,
                    "referred_volume_wei": "1000",
                    "referred_deposits": 2,
                    "allocation_bps": 10000,
                    "allocation_share": 1.0,
                }
            ],
        }

    monkeypatch.setattr(referrals_routes, "get_vault_allocation", fake_allocation)

    client = TestClient(app)
    response = client.get(f"/api/referrals/vault/{VALID_VAULT}/allocation")
    assert response.status_code == 200
    data = response.json()
    assert data["vaultAddress"] == VALID_VAULT
    assert data["allocations"][0]["allocationBps"] == 10000


def test_referral_vault_invalid_address() -> None:
    client = TestClient(app)
    response = client.get("/api/referrals/vault/not-a-vault")
    assert response.status_code == 422


def test_admin_referral_suspicious_scan(monkeypatch) -> None:
    async def fake_scan(_db):
        return [
            {
                "issue_type": "self_referral",
                "severity": "high",
                "description": "Self referral detected",
                "metadata": {"count": 2},
            }
        ]

    monkeypatch.setattr(admin_routes, "scan_suspicious_patterns", fake_scan)

    client = TestClient(app)
    response = client.get("/admin/referrals/suspicious")
    assert response.status_code == 200
    data = response.json()
    assert data[0]["issueType"] == "self_referral"


def test_admin_referral_review_create(monkeypatch) -> None:
    async def fake_create(_db, **kwargs):
        return {
            "id": 1,
            "status": "open",
            "issue_type": kwargs["issue_type"],
            "referrer_address": kwargs["referrer_address"],
            "reason": kwargs["reason"],
            "notes": kwargs.get("notes"),
        }

    monkeypatch.setattr(admin_routes, "create_abuse_review", fake_create)

    client = TestClient(app)
    response = client.post(
        "/admin/referrals/suspicious-review",
        json={
            "referrerAddress": VALID_ADDRESS,
            "issueType": "self_referral",
            "reason": "manual review",
            "notes": "flagged by scanner",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["issueType"] == "self_referral"
    assert data["referrerAddress"] == VALID_ADDRESS
