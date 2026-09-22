"""
The classification taxonomy, in one place.

Every label the engine can emit is defined here with what it means, which
entity it is reported against, and whether it represents money that is
genuinely missing or unaccounted for. The agent's allowed values, the report's
"real breaks" grouping and the web API's metadata all read this table, so a
new class cannot be added to the engine and forgotten by one of them -- which
is how the agent's list and the report's grouping had drifted to two
different hand-maintained sets.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ClassInfo:
    label: str
    level: str            # order | txn | bank_row | settlement | statement_gap
    severity: str         # ok | expected | review | break
    summary: str

    @property
    def real_break(self) -> bool:
        """Money genuinely missing or unaccounted for, not merely explained."""
        return self.severity == "break"


_TABLE = [
    ClassInfo("clean", "any", "ok",
              "every source agrees and the amounts tie exactly"),
    ClassInfo("rounding_noise", "order", "ok",
              "fee differs by at most two paise, within rounding tolerance"),
    ClassInfo("refund", "order", "expected",
              "fully refunded; net settlement contribution is negative"),
    ClassInfo("partial_refund", "order", "expected",
              "part of the order was refunded"),
    ClassInfo("chargeback", "order", "expected",
              "sale reversed in a later settlement period, with a penalty"),
    ClassInfo("unsettled", "order", "expected",
              "captured but not yet paid out; correctly unmatched"),
    ClassInfo("failed_payment", "order", "expected",
              "attempt failed; no settlement will ever exist"),
    ClassInfo("split_settlement", "bank_row", "expected",
              "one settlement paid in several instalments that sum exactly"),
    ClassInfo("duplicate", "order", "review",
              "several captures for one order"),
    ClassInfo("fee_mismatch", "order", "review",
              "fee differs from the method's rule by more than tolerance"),
    ClassInfo("ambiguous_match", "bank_row", "review",
              "several settlements fit equally well; escalated, not guessed"),
    ClassInfo("missing_payment", "order", "break",
              "order in the ledger with no gateway record"),
    ClassInfo("amount_mismatch", "order", "break",
              "ledger and gateway (or bank and settlement) amounts differ"),
    ClassInfo("method_mismatch", "order", "break",
              "ledger and gateway disagree on the payment method"),
    ClassInfo("currency_mismatch", "order", "break",
              "order recorded in a currency other than the settlement currency"),
    ClassInfo("net_arithmetic_error", "txn", "break",
              "gross - fee - gst does not equal net on the gateway row"),
    ClassInfo("dangling_settlement_ref", "txn", "break",
              "gateway row names a settlement the report does not contain"),
    ClassInfo("unreversed_refund_fee", "txn", "break",
              "a refund was charged a fee that the rule table does not allow"),
    ClassInfo("settlement_total_mismatch", "settlement", "break",
              "member transactions do not sum to the settlement total"),
    ClassInfo("settlement_not_in_bank", "settlement", "break",
              "settlement reported but no statement line pays it"),
    ClassInfo("orphan_bank_credit", "bank_row", "break",
              "statement line that corresponds to no settlement"),
    ClassInfo("duplicate_bank_row", "bank_row", "break",
              "second credit for a settlement an earlier line already paid"),
    ClassInfo("payout_reversal", "bank_row", "break",
              "debit returning a payout the books still show as settled"),
    ClassInfo("missing_bank_row", "statement_gap", "break",
              "running balance jumps: a statement line is absent"),
]

TAXONOMY: dict[str, ClassInfo] = {c.label: c for c in _TABLE}

REAL_BREAKS = frozenset(c.label for c in _TABLE if c.real_break)

# What the resolution agent may answer. `clean` is excluded -- the agent only
# sees records the tiers could not resolve -- and `unexplained` is the honest
# answer when the evidence does not support any class.
AGENT_CLASSIFICATIONS = [c.label for c in _TABLE if c.label != "clean"] + ["unexplained"]


def describe(label: str) -> ClassInfo:
    return TAXONOMY.get(label) or ClassInfo(label, "any", "review",
                                            "unrecognised classification")
