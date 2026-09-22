"""
Tests for the unseen-defect generator and the detection grader.

Two things are under test and they fail for different reasons:

  * the GENERATOR must plant what it claims, exactly once per record, on an
    otherwise clean substrate. A generator that plants two defects on one
    record produces a detection that cannot be attributed, which is worse than
    no measurement at all -- it looks like evidence.

  * the GRADER must not score a detection as a silent pass. It did, twice,
    during development: once because the engine reports a continuity break
    against a derived entity id, and once because the record also carried its
    own `clean` resolution and the first lookup won. Both are regression-tested
    here, because both failures flatter the instrument rather than the engine,
    and a measurement that understates the engine is still a broken
    measurement.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from adversarial_data import (  # noqa: E402
    UNSEEN_LABELS, AdversarialGenerator, UnseenPlan, zero_plan,
)
from evaluate import (  # noqa: E402
    DetectionOutcome, grade_detection, load_unseen_truth,
)


@pytest.fixture(scope="module")
def batch(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("unseen")
    gen = AdversarialGenerator(seed=7, n_orders=300, n_days=30,
                               plan=zero_plan())
    gen.run()
    gen.write(out)
    return out


# --------------------------------------------------------------------------
# Generator
# --------------------------------------------------------------------------

class TestAdversarialGenerator:

    def test_plants_every_class_it_declares(self, batch):
        """
        A class silently failing to place would look like a class the engine
        handles perfectly, because an unplanted defect is never a silent pass.
        """
        planted = load_unseen_truth(batch)
        classes = set(planted.values())
        assert classes == UNSEEN_LABELS, (
            f"missing: {UNSEEN_LABELS - classes}; "
            f"unexpected: {classes - UNSEEN_LABELS}")

    def test_counts_match_the_plan(self, batch):
        from collections import Counter
        counts = Counter(load_unseen_truth(batch).values())
        plan = UnseenPlan()
        # split_settlement marks BOTH halves of the split payout, so its
        # record count is twice the number of settlements split.
        assert counts["split_settlement"] == plan.split_settlement * 2
        for field in ("payout_reversal", "duplicate_bank_row",
                      "currency_mismatch", "amount_transposition",
                      "unreversed_refund_fee", "balance_inconsistency",
                      "dangling_settlement_ref", "net_arithmetic_control"):
            assert counts[field] == getattr(plan, field), field

    def test_no_settlement_carries_two_unseen_defects(self):
        """
        The confound guard. Without it, `_dangle_settlement_refs` shrank a
        settlement that `_duplicate_bank_rows` had already duplicated, so the
        duplicate no longer tied and was 'detected' -- by the wrong defect.
        Two of three duplicates were scored as detections that the duplicate
        had nothing to do with.
        """
        gen = AdversarialGenerator(seed=7, n_orders=300, n_days=30,
                                   plan=zero_plan())
        gen.run()
        # split_settlement legitimately marks BOTH halves against the same
        # settlement, so it is excluded rather than counted as a collision.
        targets = [t.expected_match_target for t in gen.truth
                   if t.entity_id in gen._unseen_ids
                   and t.expected_classification != "split_settlement"
                   and t.expected_match_target.startswith("setl_")
                   and not t.expected_match_target.startswith("setl_9")]
        assert len(targets) == len(set(targets)), \
            f"a settlement was used by two defects: {targets}"

    def test_substrate_is_clean_by_default(self, batch):
        """
        Every non-clean record must be one of ours. A base defect leaking in
        would be graded as an unseen class it is not, or inflate the clean
        baseline the engine is measured against.
        """
        import csv
        with (batch / "ground_truth.csv").open(encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        for r in rows:
            cls = r["expected_classification"]
            outside = r["outside_taxonomy"] == "yes"
            # `refund` is emitted for orders carrying an unreversed refund fee:
            # the order really is refunded, and that classification is correct.
            # The defect belongs to the refund row, not to the order.
            # `messy_narration` is a property of the base narration templates,
            # not a planted defect -- it is present on any batch. `refund` is
            # the correct order-level label for an order whose refund row
            # carries the unreversed fee.
            assert cls in ("clean", "messy_narration", "refund") or outside, \
                f"{r['entity_id']} is {cls}, neither clean nor an unseen defect"

    def test_balances_tie_except_where_deliberately_broken(self, batch):
        """
        Every structural mutation resizes the statement. If the balance column
        were left stale, the continuity check would fire on rows carrying no
        defect and every number downstream would be wrong.
        """
        import csv
        with (batch / "bank.csv").open(encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        planted = load_unseen_truth(batch)
        broken = {k for k, v in planted.items() if v == "balance_inconsistency"}

        gen = AdversarialGenerator(seed=7, n_orders=300, n_days=30,
                                   plan=zero_plan())
        balance = gen.opening_balance_paise
        offenders = []
        for r in rows:
            movement = (int(r["credit_paise"] or 0)
                        - int(r["debit_paise"] or 0))
            balance += movement
            if int(r["balance_paise"]) != balance:
                offenders.append(r["bank_txn_id"])
                # Deliberately NOT resyncing to the stated balance. Resyncing
                # adopts the corrupt figure, so the next row disagrees too and
                # one planted defect reports as two. The true running total is
                # carried forward instead, and only genuinely wrong rows fail.
        assert set(offenders) == broken, \
            f"balance breaks at {offenders}, expected exactly {broken}"

    def test_refund_rows_stay_internally_consistent(self, batch):
        """
        The unreversed fee must NOT break `gross - fee - gst == net`. If it
        did, the engine would catch it via an existing arithmetic check and the
        defect would no longer be unseen -- it would be `net_arithmetic_error`
        wearing a different name.
        """
        import csv
        with (batch / "gateway.csv").open(encoding="utf-8-sig") as f:
            refunds = [r for r in csv.DictReader(f)
                       if r["txn_type"] == "refund"]
        assert refunds, "no refund rows were planted"
        for r in refunds:
            gross = int(r["gross_amount_paise"])
            fee = int(r["fee_paise"])
            gst = int(r["gst_on_fee_paise"])
            assert gross - fee - gst == int(r["net_amount_paise"])
            assert fee > 0, "the defect is the presence of a fee"


# --------------------------------------------------------------------------
# Grader
# --------------------------------------------------------------------------

class TestDetectionGrader:

    def test_ordinary_dataset_has_no_unseen_records(self):
        """
        Datasets written by the base generator carry no `outside_taxonomy`
        column. The grader must treat that as zero unseen records rather than
        raising, so existing datasets keep working untouched.
        """
        ref = Path(__file__).resolve().parent.parent / "datasets" / "01-reference"
        assert load_unseen_truth(ref) == {}

    def test_positive_control_is_detected(self, batch):
        """
        `amount_transposition` is compared directly by the engine (ledger
        amount vs gateway gross), so it MUST be detected. If this ever reports
        a silent pass, the harness is broken, not the engine -- and every other
        number in the report is then suspect.
        """
        outcomes, _ = grade_detection(batch)
        control = [o for o in outcomes if o.planted == "amount_transposition"]
        assert control, "the control class was not planted"
        assert all(o.state == "detected" for o in control), \
            [(o.entity_id, o.state) for o in control]

    def test_a_derived_entity_id_still_counts_as_detection(self, batch):
        """
        Regression. A continuity break is emitted against `GAP_BEFORE_<row>`,
        not against the row. Scoring by the row's id alone reported two real
        detections as silent passes -- an instrument that understates the
        engine is still a broken instrument.
        """
        outcomes, _ = grade_detection(batch)
        bal = [o for o in outcomes if o.planted == "balance_inconsistency"]
        assert bal
        assert all(o.state == "detected" for o in bal), \
            [(o.entity_id, o.state, o.emitted) for o in bal]

    def test_a_clean_resolution_does_not_mask_a_flag_elsewhere(self, batch):
        """
        Regression. The perturbed bank row carries BOTH its own `clean`
        resolution and a gap flagged against the derived id. Taking the first
        lookup found `clean` and scored a silent pass. Any non-clean signal
        about the record wins.
        """
        outcomes, _ = grade_detection(batch)
        bal = [o for o in outcomes if o.planted == "balance_inconsistency"]
        assert all(o.emitted == "missing_bank_row" for o in bal), \
            [o.emitted for o in bal]

    def test_absent_and_clean_are_reported_separately(self, batch, monkeypatch):
        """
        Two different failures. `clean` means the engine examined the record
        and passed it; `absent` means it never emitted anything about the
        record at all. The second is the one the resolution-driven grader in
        `grade()` is structurally blind to, which is why this grader walks
        truth instead.

        The real engine no longer produces either state on this batch, so the
        grader is exercised against a deliberately blinded engine that
        reproduces the two historical failures: currency read as clean, and a
        refund row never examined.
        """
        import evaluate
        from matcher import Engine

        class Blinded(Engine):
            def run(self):
                out = []
                for r in super().run():
                    if r.classification == "unreversed_refund_fee":
                        continue
                    if r.classification == "currency_mismatch":
                        r.classification, r.resolved = "clean", True
                    out.append(r)
                self.resolutions = out
                return out

        monkeypatch.setattr(evaluate, "Engine", Blinded)
        outcomes, summary = grade_detection(batch)
        states = {o.planted: o.state for o in outcomes}
        assert states["currency_mismatch"] == "silent_clean"
        assert states["unreversed_refund_fee"] == "silent_absent"
        assert summary["silent"] == sum(
            1 for o in outcomes if o.state != "detected")
        assert set(summary["blind_spot_classes"]) == {
            "currency_mismatch", "unreversed_refund_fee"}

    def test_detection_rate_is_consistent_with_the_outcomes(self, batch):
        outcomes, summary = grade_detection(batch)
        assert summary["total"] == len(outcomes)
        assert summary["detected"] == sum(
            1 for o in outcomes if o.state == "detected")
        assert summary["detection_rate"] == pytest.approx(
            summary["detected"] / summary["total"])

    # The detection state of EVERY declared class is pinned, not only the
    # silent ones. A partial pin let `duplicate_bank_row` sit as an
    # undocumented blind spot: it was silent, no test named it, so nothing
    # flagged it. `SILENT` classes are the finding; `DETECTED` classes must
    # stay caught -- a regression that flips one silently degrades the engine.
    # Every class that was once a blind spot is now caught. `SILENT` is kept,
    # empty, as the place a new finding goes: a class added to the generator
    # that the engine misses belongs here until it is fixed, and pinning it
    # keeps the finding visible rather than letting it sit undocumented the
    # way duplicate_bank_row once did.
    SILENT: set[str] = set()
    DETECTED = {"amount_transposition", "net_arithmetic_control",
                "balance_inconsistency", "payout_reversal", "split_settlement",
                "currency_mismatch", "duplicate_bank_row",
                "dangling_settlement_ref", "unreversed_refund_fee"}
    # Classes the engine now names exactly, rather than merely flags. The two
    # positive controls and the balance break are caught under the labels the
    # engine already had, which is correct for them.
    NAMED = {"payout_reversal", "split_settlement", "currency_mismatch",
             "duplicate_bank_row", "dangling_settlement_ref",
             "unreversed_refund_fee"}

    def test_every_declared_class_has_a_pinned_state(self):
        """
        Guards the map itself. If a class is added to the generator without
        deciding whether it is a blind spot or a caught defect, this fails --
        so a new defect can never slip in unpinned the way duplicate_bank_row
        did.
        """
        assert self.SILENT | self.DETECTED == UNSEEN_LABELS, (
            "a declared class is missing from the state map; classify it as "
            "SILENT (a blind spot) or DETECTED before merging")
        assert not self.SILENT & self.DETECTED

    def test_blind_spot_classes_stay_silent(self, batch):
        """
        Pins any known blind spots. Empty since the four found by this harness
        (currency, duplicate bank credit, dangling settlement reference, refund
        fee) were closed; see NOTES.md for how each was fixed.
        """
        _, summary = grade_detection(batch)
        for cls in self.SILENT:
            assert summary["by_class"][cls].get("detected", 0) == 0, (
                f"{cls} is now detected -- if deliberate, move it to DETECTED "
                f"and update the blind-spot list in README/ARCHITECTURE")

    def test_caught_classes_stay_detected(self, batch):
        """
        A change that lets a caught class slip back to silent is a regression,
        and the two controls slipping to silent means the grader itself broke.
        """
        _, summary = grade_detection(batch)
        assert summary["blind_spot_classes"] == []
        for cls in self.DETECTED:
            c = summary["by_class"][cls]
            assert c.get("silent_clean", 0) == 0 and c.get("silent_absent", 0) == 0, (
                f"{cls} now has silent records: {c}")

    def test_formerly_blind_classes_are_named_exactly(self, batch):
        """
        Detection is the floor; the analyst also needs the right name. A
        duplicate bank credit reported as `orphan_bank_credit` would be caught
        and still send someone looking for the wrong thing.
        """
        outcomes, _ = grade_detection(batch)
        for o in outcomes:
            if o.planted in self.NAMED:
                assert o.emitted == o.planted, (o.entity_id, o.planted, o.emitted)

    def test_txn_level_positive_control_is_detected(self, batch):
        """
        The control that isolates the txn-level findings. `net_arithmetic_control`
        breaks gross - fee - gst == net, which the engine reports against the
        TXN id. If the grader could not read txn-level emissions, this and the
        two real txn blind spots would all read silent for the same reason --
        so this passing is what proves `dangling_settlement_ref` and
        `unreversed_refund_fee` are engine blind spots, not grader deafness.
        """
        outcomes, _ = grade_detection(batch)
        ctrl = [o for o in outcomes if o.planted == "net_arithmetic_control"]
        assert ctrl, "the txn-level control was not planted"
        assert all(o.state == "detected" for o in ctrl), \
            [(o.entity_id, o.state) for o in ctrl]
        assert all(o.emitted == "net_arithmetic_error" for o in ctrl), \
            [o.emitted for o in ctrl]
