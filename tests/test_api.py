"""API contract tests over the baked database (run after `python -m app.build_db`)."""
import pytest
from fastapi.testclient import TestClient

from app.api import app, limiter


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/api/health").json()
    assert r["status"] == "ok"
    assert r["weeks"] == 12
    assert r["materials"] > 0


def test_headline_shape(client):
    r = client.get("/api/headline").json()
    assert len(r["weeks"]) == 12
    assert r["weeks"][-1]["cw"] == r["latest"]
    assert all(88 <= w["rate"] <= 96 for w in r["weeks"])
    f = r["forecast"]
    for key in ["central", "lo", "hi", "mean", "std", "autocorr", "memoryless", "curExposure"]:
        assert key in f
    assert f["lo"] < f["central"] < f["hi"]


def test_forecast_story(client):
    r = client.get("/api/forecast").json()
    assert r["leadingSignal"]["lift"] > 1
    cells = {(c["failing"], c["short"]): c["p"] for c in r["riskModel"]}
    assert cells[(0, 0)] < cells[(0, 1)] < cells[(1, 0)] < cells[(1, 1)]
    assert len(r["hardSearch"]) == 3
    assert len(r["horizonReach"]) == 4
    assert 0 < r["recoverable"]["pct"] <= 1
    assert r["volume"]["heldout"]["actual"] > 0


def test_register_default(client):
    r = client.get("/api/register").json()
    assert r["count"] >= r["returned"] > 0
    assert r["returned"] <= 400
    row = r["rows"][0]
    for key in ["product", "plant", "supplier", "category", "unconf", "riskProb",
                "expectedUnits", "recoverable", "structural", "confidence", "lever"]:
        assert key in row


def test_register_filters(client):
    rec = client.get("/api/register?recoverable=true").json()
    assert all(row["recoverable"] for row in rec["rows"])
    plant = client.get("/api/register?plant=D01").json()
    assert all(row["plant"] == "D01" for row in plant["rows"])
    prob = client.get("/api/register?min_prob=0.5").json()
    assert all(row["riskProb"] >= 0.5 for row in prob["rows"])


def test_register_limit_edge(client):
    r = client.get("/api/register?limit=0").json()
    assert r["returned"] == 0 and r["rows"] == []
    r = client.get("/api/register?limit=-5").json()
    assert r["returned"] == 0


def test_worklist(client):
    r = client.get("/api/worklist?n=10").json()
    assert len(r["rows"]) == 10
    assert all(row["recoverable"] for row in r["rows"])
    eu = [row["expectedUnits"] for row in r["rows"]]
    assert eu == sorted(eu, reverse=True)


def test_root_cause(client):
    r = client.get("/api/root_cause").json()
    assert len(r["rows"]) > 0
    u = [row["unconf"] for row in r["rows"]]
    assert u == sorted(u, reverse=True)


def test_unknown_week_falls_back_to_latest(client):
    latest = client.get("/api/health").json()["latestWeek"]
    r = client.get("/api/root_cause?week=2024-W52").json()
    assert r["week"] == latest and len(r["rows"]) > 0 and "note" in r
    b = client.get("/api/breakdown?week=nonsense").json()
    assert b["week"] == latest and "note" in b


def test_breakdown(client):
    r = client.get("/api/breakdown").json()
    for dim in ["byPlant", "byBusinessField", "bySupplier", "byCategory"]:
        assert dim in r and len(r[dim]) > 0
    assert all("delta" in row and "trend" in row for row in r["byPlant"])


def test_ask_keyless_503(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = client.post("/api/ask", json={"question": "hi"})
    assert r.status_code == 503


def test_ask_rate_limited_429(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-never-used")
    monkeypatch.setattr(limiter, "per_hour", 0)
    r = client.post("/api/ask", json={"question": "hi"})
    assert r.status_code == 429
    body = r.json()
    assert body["scope"] == "ip" and body["retryAfter"] >= 0


def test_ask_validation(client):
    assert client.post("/api/ask", json={"question": ""}).status_code == 422
    assert client.post("/api/ask", json={"question": "x" * 500}).status_code == 422


def test_api_index(client):
    r = client.get("/api").json()
    assert any("/api/forecast" in e for e in r["endpoints"])


def test_limiter_global_budget():
    from app.ratelimit import AskLimiter
    lim = AskLimiter()
    lim.day_cost = lim.daily_budget + 1
    ok, scope, retry = lim.check("1.2.3.4")
    assert not ok and scope == "global" and retry > 0


def test_limiter_ip_window():
    from app.ratelimit import AskLimiter
    lim = AskLimiter()
    for _ in range(lim.per_hour):
        ok, _, _ = lim.check("9.9.9.9")   # check() reserves the slot
        assert ok
    ok, scope, _ = lim.check("9.9.9.9")
    assert not ok and scope == "ip"
    ok, _, _ = lim.check("8.8.8.8")
    assert ok


def test_limiter_reserves_on_check():
    # a failed downstream call must still consume the slot
    from app.ratelimit import AskLimiter
    lim = AskLimiter()
    before = lim.day_requests
    lim.check("7.7.7.7")
    assert lim.day_requests == before + 1


def test_client_ip_uses_last_forwarded_hop():
    from app.ratelimit import client_ip

    class Req:
        headers = {"x-forwarded-for": "6.6.6.6, 10.0.0.1"}
        client = None
    assert client_ip(Req()) == "10.0.0.1"
