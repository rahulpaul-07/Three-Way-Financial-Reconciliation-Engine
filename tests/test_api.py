"""
Tests for the JSON API the dashboard calls, and for the analysis payload it
returns.

The payload is checked for the properties the dashboard relies on rather than
for exact figures (those are covered by the reconciliation tests): the money
flow must conserve, every entity the engine examined must appear exactly once,
and figures derived here must agree with the evaluator they are built on.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

pytest.importorskip("fastapi", reason="web layer is optional")
from fastapi.testclient import TestClient  # noqa: E402

import app as app_module  # noqa: E402
from analysis import analyse, taxonomy_payload  # noqa: E402
from evaluate import grade  # noqa: E402

REF = ROOT / "datasets" / "01-reference"


@pytest.fixture(scope="module")
def client():
    return TestClient(app_module.app)


@pytest.fixture(scope="module")
def payload():
    return analyse(REF)


def _files(d: Path, names=("ledger", "gateway", "bank", "settlements")):
    return {n: (f"{n}.csv", (d / f"{n}.csv").read_bytes(), "text/csv")
            for n in names}


class TestAnalysisPayload:

    def test_every_entity_appears_once(self, payload):
        ids = [r["entity_id"] for r in payload["resolutions"]]
        assert len(ids) == len(set(ids)) == payload["summary"]["entities"]

    def test_figures_agree_with_the_evaluator(self, payload):
        _, summ = grade(REF)
        assert payload["summary"]["resolved"] == summ["resolved"]
        assert payload["grading"]["accuracy"] == summ["accuracy"]

    def test_money_flow_conserves_at_every_node(self, payload):
        flow = payload["money_flow"]
        inflow, outflow = defaultdict(int), defaultdict(int)
        for link in flow["links"]:
            assert link["value"] > 0
            outflow[link["source"]] += link["value"]
            inflow[link["target"]] += link["value"]
        for node in inflow:
            if node in outflow:
                assert inflow[node] == outflow[node], flow["nodes"][node]

    def test_money_stays_in_integer_paise(self, payload):
        for r in payload["resolutions"]:
            assert isinstance(r["amount_paise"], int)
        for link in payload["money_flow"]["links"]:
            assert isinstance(link["value"], int)

    def test_every_emitted_class_has_a_severity(self, payload):
        known = {c["label"] for c in taxonomy_payload()["classes"]}
        for r in payload["resolutions"]:
            assert r["classification"] in known
            assert r["severity"] in {"ok", "expected", "review", "break"}

    def test_unseen_batch_reports_detection(self):
        p = analyse(ROOT / "datasets" / "08-unseen", include_records=False)
        assert p["detection"]["silent"] == 0
        assert p["records"] is None

    def test_ordinary_batch_reports_no_detection(self, payload):
        assert payload["detection"] is None


class TestApi:

    def test_datasets_are_listed(self, client):
        names = {d["name"] for d in client.get("/api/v1/datasets").json()}
        assert "01-reference" in names and "07-malformed" not in names

    def test_a_bundled_dataset_reconciles(self, client):
        r = client.post("/api/v1/datasets/01-reference")
        assert r.status_code == 200
        assert r.json()["grading"]["accuracy"] == 1.0

    def test_an_unknown_dataset_is_refused(self, client):
        assert client.post("/api/v1/datasets/nope").status_code == 404

    def test_sample_parameters_are_bounded(self, client):
        assert client.post("/api/v1/sample",
                           json={"orders": 10_000_000}).status_code == 400
        assert client.post("/api/v1/sample",
                           json={"seed": "x"}).status_code == 400

    def test_sample_generates(self, client):
        r = client.post("/api/v1/sample", json={"seed": 5, "orders": 60})
        assert r.status_code == 200
        assert r.json()["sources"]["orders"] == 60

    def test_upload_reconciles(self, client):
        r = client.post("/api/v1/reconcile", files=_files(REF))
        assert r.status_code == 200
        assert r.json()["source"] == "Your upload"

    def test_malformed_upload_names_the_column(self, client):
        d = ROOT / "datasets" / "07-malformed"
        r = client.post("/api/v1/reconcile",
                        files=_files(d, ("ledger", "gateway", "bank")))
        assert r.status_code == 400 and "order_id" in r.json()["detail"]

    def test_oversized_upload_is_refused(self, client, monkeypatch):
        monkeypatch.setattr(app_module, "MAX_BYTES", 1024)
        r = client.post("/api/v1/reconcile", files=_files(REF))
        assert r.status_code == 413

    def test_taxonomy_is_served(self, client):
        classes = client.get("/api/v1/taxonomy").json()["classes"]
        assert any(c["label"] == "duplicate_bank_row" for c in classes)

    def test_security_headers_are_set(self, client):
        h = client.get("/api/v1/health").headers
        assert h["x-content-type-options"] == "nosniff"
        assert h["x-frame-options"] == "DENY"
        assert h["cache-control"] == "no-store"

    def test_cors_allows_the_pages_site_only(self, client):
        ok = client.options("/api/v1/sample", headers={
            "Origin": "https://rahulpaul-07.github.io",
            "Access-Control-Request-Method": "POST"})
        assert ok.headers["access-control-allow-origin"] == \
            "https://rahulpaul-07.github.io"
        bad = client.options("/api/v1/sample", headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST"})
        assert "access-control-allow-origin" not in bad.headers

    def test_unknown_api_path_is_json_404(self, client):
        r = client.get("/api/v1/nothing-here")
        assert r.status_code == 404

    def test_static_files_cannot_escape_the_build(self, client, tmp_path,
                                                  monkeypatch):
        (tmp_path / "index.html").write_text("<title>Three-way payment "
                                             "reconciliation</title>")
        monkeypatch.setattr(app_module, "WEB_DIST", tmp_path)
        assert client.get("/").status_code == 200
        assert client.get("/some/client/route").status_code == 200
        r = client.get("/../src/app.py")
        assert "SlidingWindowLimiter" not in r.text


class TestLimits:

    def test_a_visitor_key_does_not_spend_the_operator_budget(self,
                                                              monkeypatch):
        """
        The page tells visitors to supply their own key to bypass the limit.
        Before the limiter was split, the global check ran first and refused
        them anyway.
        """
        op = app_module.SlidingWindowLimiter(1)
        monkeypatch.setattr(app_module, "operator_limiter", op)
        monkeypatch.setattr(app_module, "visitor_limiter",
                            app_module.SlidingWindowLimiter(5))

        class Req:
            headers = {}
            client = type("C", (), {"host": "1.2.3.4"})()

        assert not app_module._model_rate_limited(Req(), None)
        assert app_module._model_rate_limited(Req(), None)
        assert not app_module._model_rate_limited(Req(), "sk-visitor")

    def test_a_spoofed_forwarded_header_does_not_change_the_client(self):
        class Req:
            headers = {"x-forwarded-for": "9.9.9.9"}
            client = type("C", (), {"host": "1.2.3.4"})()
        assert app_module._client_id(Req()) == "1.2.3.4"

    def test_limiter_window_expires(self, monkeypatch):
        lim = app_module.SlidingWindowLimiter(1, window_s=10)
        now = [1000.0]
        monkeypatch.setattr(app_module.time, "time", lambda: now[0])
        assert not lim.hit("a")
        assert lim.hit("a")
        assert not lim.hit("b"), "buckets are independent"
        now[0] += 11
        assert not lim.hit("a")

    def test_a_visitor_key_never_touches_the_environment(self, monkeypatch):
        import os
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        seen = []
        real_setitem = os.environ.__class__.__setitem__

        def spy(self, k, v):
            seen.append(k)
            return real_setitem(self, k, v)

        monkeypatch.setattr(os.environ.__class__, "__setitem__", spy)
        app_module._provider_for("sk-ant-not-a-real-key")
        assert "ANTHROPIC_API_KEY" not in seen
