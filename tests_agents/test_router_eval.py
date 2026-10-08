"""
Tests for the router evaluation set (data/router_eval.jsonl).

The set is fixed before the router exists, so its shape and its answer key are
checked here: a request with the wrong route, a gold query that drifts from the
stored answer, or an investigator request naming a record that is not an
exception would each make a later score meaningless.

No model and no network are involved.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import router_eval_gold as gold  # noqa: E402

from sql_ask import build_from_dir, run_query  # noqa: E402


@pytest.fixture(scope="module")
def items():
    return gold.load_eval()


@pytest.fixture(scope="module")
def exceptions():
    return gold.unresolved_classifications()


def by_route(items, route):
    return [i for i in items if i["route"] == route]


class TestShape:

    def test_thirty_requests_with_sequential_unique_ids(self, items):
        assert [i["id"] for i in items] == [f"R{n:02d}" for n in range(1, 31)]

    def test_ten_per_route_and_no_other_route(self, items):
        assert Counter(i["route"] for i in items) == {r: 10 for r in gold.ROUTES}

    def test_four_boundary_cases_each_with_a_recorded_reason(self, items):
        boundary = [i for i in items if i["boundary"]]
        assert len(boundary) == 4
        assert all(len(i["why"]) > 60 for i in boundary)

    def test_every_request_has_text_and_a_reason(self, items):
        assert all(i["request"].strip() and i["why"].strip() for i in items)

    def test_every_request_has_exactly_one_correct_route(self, items):
        # list_exceptions does not return the matcher's classification, so a
        # compound request cannot be answered by the investigator alone and
        # R30 stays human-only. If that ever changes, this is the test to
        # revisit, together with the eval set.
        assert not any("accepted_routes" in i for i in items)
        assert next(i for i in items if i["id"] == "R30")["route"] == "human"
        assert next(i for i in items if i["id"] == "R29")["route"] == "human"

    def test_human_requests_carry_no_answer_key(self, items):
        for i in by_route(items, "human"):
            assert not {"expected", "gold_sql", "entity_id"} & i.keys()


class TestInvestigatorRequests:

    def test_each_names_a_real_unresolved_record(self, items, exceptions):
        for i in by_route(items, "investigator"):
            assert i["entity_id"] in exceptions, i["id"]
            assert i["matcher_classification"] == exceptions[i["entity_id"]]

    def test_the_id_is_in_the_request_except_in_the_one_that_omits_it(self, items):
        for i in by_route(items, "investigator"):
            named = i["entity_id"] in i["request"]
            assert named == (i["category"] != "investigator_no_id"), i["id"]

    def test_end_to_end_agreement_can_be_scored_against_the_matcher(self, items):
        # The second metric compares the investigator's verdict with the
        # matcher's label, so every investigator item must carry a label the
        # agent can actually output.
        from taxonomy import AGENT_CLASSIFICATIONS
        for i in by_route(items, "investigator"):
            assert i["matcher_classification"] in AGENT_CLASSIFICATIONS, i["id"]

    def test_requests_that_hint_at_the_answer_are_marked(self, items):
        hinted = {i["id"] for i in by_route(items, "investigator")
                  if i["hint_in_request"]}
        assert hinted == {"R01", "R02", "R03", "R04", "R05", "R09"}

    def test_only_investigator_items_carry_a_hint_flag(self, items):
        for i in items:
            assert ("hint_in_request" in i) == (i["route"] == "investigator"), i["id"]

    def test_each_record_is_used_once(self, items):
        ids = [i["entity_id"] for i in by_route(items, "investigator")]
        assert len(ids) == len(set(ids))


class TestDataRequests:

    def test_gold_queries_are_selects_the_real_guard_accepts(self, items):
        conn = build_from_dir(ROOT / "data")
        for i in by_route(items, "data"):
            result = run_query(conn, i["gold_sql"])
            assert result.ok, (i["id"], result.error)

    def test_every_data_request_has_a_non_empty_answer(self, items):
        for i in by_route(items, "data"):
            exp = i["expected"]
            assert exp["numbers"] or exp["strings"], i["id"]

    def test_stored_answers_equal_a_fresh_computation(self, items):
        fresh = gold.recompute(items)
        assert [i for i, f in zip(items, fresh, strict=True) if i != f] == []

    def test_a_tampered_answer_is_detected(self, items):
        tampered = dict(next(i for i in items if i["id"] == "R15"))
        tampered["expected"] = {"numbers": ["4"], "strings": []}
        assert gold.recompute([tampered])[0] != tampered

    def test_negative_money_is_stored_as_a_magnitude(self, items):
        # The chargeback gross is negative in the data; the grounding check
        # reads no signs, so the key must not carry one.
        r14 = next(i for i in items if i["id"] == "R14")
        assert "1951.49" in r14["expected"]["numbers"]
        assert not any(n.startswith("-") for n in r14["expected"]["numbers"])
