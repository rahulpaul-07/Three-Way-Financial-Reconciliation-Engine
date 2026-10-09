"""
Tests for the SQL question-answering layer.

Letting a model write SQL is a far bigger grant of power than a menu of named
lookups, so the tests are organised around what it must not be able to do:

  * change or escape the database       (TestReadOnly)
  * run away with time or memory        (TestBounds)
  * report a figure the data did not produce   (TestGrounding)

None of them involves a model. The agent loop is driven by a scripted provider
that plays a model, including one that invents a number.
"""

from __future__ import annotations

import sys
import time
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from core import paise_to_rupees_str  # noqa: E402
from llm import LLMResponse, Provider, ToolCall  # noqa: E402
from sql_ask import (  # noqa: E402
    MAX_ROWS,
    TABLES,
    QueryResult,
    SQLAsker,
    build_from_dir,
    describe_schema,
    find_numbers,
    numbers_in,
    run_query,
    ungrounded_numbers,
)


@pytest.fixture()
def conn():
    return build_from_dir(ROOT / "data")


def counts(conn):
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES}


# --------------------------------------------------------------------------
# Read-only
# --------------------------------------------------------------------------

ATTACKS = [
    "DROP TABLE orders",
    "DELETE FROM orders",
    "UPDATE orders SET order_amount_paise = 0",
    "INSERT INTO orders SELECT * FROM orders",
    "CREATE TABLE x AS SELECT * FROM orders",
    "ALTER TABLE orders ADD COLUMN y TEXT",
    "SELECT * FROM orders; DELETE FROM orders",
    "WITH x AS (SELECT 1) DELETE FROM orders",
    "WITH x AS (SELECT 1) UPDATE orders SET order_status = 'paid'",
    "PRAGMA query_only = OFF",
    "PRAGMA writable_schema = ON",
    "ATTACH DATABASE '/tmp/escape.db' AS x",
    "VACUUM",
    "REPLACE INTO orders VALUES ('a',1,'INR','d','c','paid','upi')",
    "SELECT load_extension('anything')",
    "SELECT * FROM sqlite_master",
    "SELECT * FROM sqlite_schema",
    "SELECT name FROM pragma_table_info('orders')",
    "BEGIN; DELETE FROM orders; COMMIT",
    "   \n  drop table orders",
    "/* a comment first */ DELETE FROM orders",
]


class TestReadOnly:

    @pytest.mark.parametrize("sql", ATTACKS)
    def test_attack_is_rejected_and_changes_nothing(self, conn, sql):
        before = counts(conn)
        res = run_query(conn, sql)
        assert not res.ok, sql
        assert counts(conn) == before
        # and the database is still usable afterwards
        assert run_query(conn, "SELECT COUNT(*) AS n FROM orders").ok

    def test_query_only_holds_even_without_the_authorizer(self, conn):
        """
        Two independent barriers, so each must be shown to work alone. With the
        authorizer removed, SQLite's own read-only mode still refuses a write.
        """
        conn.set_authorizer(None)
        before = counts(conn)
        with pytest.raises(Exception, match="readonly|read-only"):
            conn.execute("DELETE FROM orders")
        assert counts(conn) == before

    def test_the_authorizer_holds_even_without_query_only(self):
        # query_only is denied by the authorizer, so turn it off the only way
        # a test can: rebuild a connection without it.
        from sql_ask import _authorizer
        raw = build_from_dir(ROOT / "data")
        raw.set_authorizer(None)
        raw.execute("PRAGMA query_only = OFF")
        raw.set_authorizer(_authorizer)
        before = counts(raw)
        for sql in ("DELETE FROM orders", "DROP TABLE orders"):
            with pytest.raises(Exception, match="not authorized"):
                raw.execute(sql)
        assert counts(raw) == before

    def test_the_lock_cannot_be_lifted_from_inside(self, conn):
        """query_only must survive an attempt to switch it off."""
        run_query(conn, "PRAGMA query_only = OFF")
        with pytest.raises(Exception, match="readonly|read-only|not authorized"):
            conn.execute("DELETE FROM orders")

    @pytest.mark.parametrize("fn", ["random()", "randomblob(8)", "zeroblob(10)",
                                    "load_extension('x')", "sqlite_version()",
                                    "changes()", "last_insert_rowid()"])
    def test_functions_off_the_allowlist_are_denied(self, conn, fn):
        res = run_query(conn, f"SELECT {fn} AS v")
        assert not res.ok, fn

    def test_allowed_queries_still_work(self, conn):
        for sql in [
            "SELECT COUNT(*) AS n FROM orders",
            "SELECT payment_method, SUM(fee_paise) AS fees_paise FROM gateway_txns "
            "GROUP BY payment_method",
            "SELECT strftime('%Y-%m', order_datetime) AS month, COUNT(*) AS n "
            "FROM orders GROUP BY 1",
            "WITH t AS (SELECT payment_method m, COUNT(*) n FROM orders GROUP BY 1) "
            "SELECT * FROM t ORDER BY n DESC",
            "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c WHERE x<5) "
            "SELECT COUNT(*) AS n FROM c",
            "SELECT o.order_id FROM orders o JOIN gateway_txns t "
            "ON t.order_ref = o.order_id LIMIT 3",
        ]:
            res = run_query(conn, sql)
            assert res.ok, f"{sql}: {res.error}"

    def test_a_trailing_semicolon_is_tolerated(self, conn):
        assert run_query(conn, "SELECT COUNT(*) AS n FROM orders;").ok

    def test_empty_and_non_select_input(self, conn):
        assert not run_query(conn, "").ok
        assert not run_query(conn, None).ok
        assert not run_query(conn, "EXPLAIN SELECT 1").ok


# --------------------------------------------------------------------------
# Bounds
# --------------------------------------------------------------------------

class TestBounds:

    def test_runaway_recursion_is_stopped(self, conn):
        t0 = time.perf_counter()
        res = run_query(conn, "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL "
                              "SELECT x+1 FROM c) SELECT COUNT(*) AS n FROM c")
        assert not res.ok and "too much work" in res.error
        assert time.perf_counter() - t0 < 10

    def test_a_cross_join_blowup_is_stopped(self, conn):
        t0 = time.perf_counter()
        res = run_query(conn, "SELECT COUNT(*) AS n FROM orders a, orders b, "
                              "orders c, gateway_txns d, gateway_txns e, gateway_txns f")
        assert not res.ok and "too much work" in res.error
        assert time.perf_counter() - t0 < 10

    def test_rows_are_capped_and_truncation_is_reported(self, conn):
        res = run_query(conn, "SELECT a.order_id FROM orders a, orders b")
        assert res.ok
        assert res.row_count == MAX_ROWS and res.truncated

    def test_a_small_result_is_not_marked_truncated(self, conn):
        res = run_query(conn, "SELECT order_id FROM orders LIMIT 5")
        assert res.row_count == 5 and not res.truncated

    def test_oversized_statement_is_refused(self, conn):
        res = run_query(conn, "SELECT 1 WHERE 1=1 " + "AND 1=1 " * 2000)
        assert not res.ok

    def test_string_doubling_cannot_exhaust_memory(self, conn):
        """A recursive CTE that doubles a string takes few steps, so the work
        budget never fires; SQLite's length limit is what stops it."""
        res = run_query(conn, "WITH RECURSIVE c(s) AS (SELECT 'a' UNION ALL "
                              "SELECT s || s FROM c) SELECT length(s) AS n FROM c")
        assert not res.ok and "too big" in res.error

    def test_the_length_limit_is_tightened_not_left_at_the_default(self, conn):
        """
        SQLite's default string limit is a billion bytes, so the doubling query
        above fails eventually even with no limit set, but only after allocating
        about a gigabyte. The test that matters is that the tight limit is the
        one in force, and that a modest string over it is refused.
        """
        import sqlite3
        assert conn.getlimit(sqlite3.SQLITE_LIMIT_LENGTH) == 100_000
        res = run_query(conn, "SELECT length(printf('%.*c', 200000, 'a')) AS n")
        assert not res.ok or res.rows[0]["n"] is None

    def test_huge_string_allocation_does_not_succeed(self, conn):
        res = run_query(conn, "SELECT printf('%.*c', 1000000000, 'a') AS s")
        assert not res.ok or res.rows[0]["s"] is None


# --------------------------------------------------------------------------
# Units
# --------------------------------------------------------------------------

class TestMoney:

    def test_every_paise_column_gets_a_formatted_inr_column(self, conn):
        res = run_query(conn, "SELECT settlement_id, total_paise FROM settlements "
                              "ORDER BY settlement_id LIMIT 3")
        assert res.columns == ["settlement_id", "total_paise", "total_inr"]
        for row in res.rows:
            assert row["total_inr"] == f"INR {paise_to_rupees_str(row['total_paise'])}"

    def test_aggregates_aliased_as_paise_are_converted_too(self, conn):
        res = run_query(conn, "SELECT SUM(net_amount_paise) AS net_paise FROM gateway_txns")
        assert res.rows[0]["net_inr"].startswith("INR ")

    def test_null_amounts_stay_null(self, conn):
        res = run_query(conn, "SELECT debit_paise FROM bank_rows WHERE debit_paise IS NULL LIMIT 1")
        assert res.rows[0]["debit_inr"] is None

    def test_negative_amounts_convert(self, conn):
        res = run_query(conn, "SELECT -12345 AS delta_paise")
        assert res.rows[0]["delta_inr"] == f"INR {paise_to_rupees_str(-12345)}"


# --------------------------------------------------------------------------
# Grounding
# --------------------------------------------------------------------------

def result(*rows, sql="SELECT ..."):
    return QueryResult(True, sql, columns=list(rows[0]) if rows else [],
                       rows=list(rows), row_count=len(rows))


class TestNumbers:

    @pytest.mark.parametrize("text,expected", [
        ("INR 1,770.20", ["1770.20"]),
        ("1,00,440.00 rupees", ["100440.00"]),
        ("on 2026-08-21", ["2026", "08", "21"]),
        ("5, 6 and 7", ["5", "6", "7"]),
        ("setl_0003", ["0003"]),
        ("no figures here", []),
    ])
    def test_extraction(self, text, expected):
        assert numbers_in(text) == [Decimal(x) for x in expected]


class TestNumberWords:
    """Numbers written as words are numbers: the scorer and the grounding check
    both read them through the same function."""

    @pytest.mark.parametrize("text,expected", [
        ("Three credits", [3]),
        ("Six orders", [6]),
        ("seven refunds", [7]),
        ("zero exceptions", [0]),
        ("twenty", [20]),
        ("NINETEEN items", [19]),
        ("seventeen and seven", [17, 7]),
        ("ninety fees", [90]),
        ("twenty-one orders", [21]),
        ("Thirty five payments", [35]),
        ("twenty three", [23]),
        ("two hundred orders", [200]),
        ("five thousand", [5000]),
        ("3 orders and four refunds", [3, 4]),
        ("INR 1,770.20 across four orders", [Decimal("1770.20"), 4]),
    ])
    def test_number_words_are_read(self, text, expected):
        assert numbers_in(text) == [Decimal(x) for x in expected]

    @pytest.mark.parametrize("text", [
        "someone", "often", "bone", "none", "weight", "ones", "tone", "stone age",
        "the one with the gap", "No one paid", "this one", "which one", "one of them",
        "the first one", "a one-off fee", "every one of them",
    ])
    def test_words_that_only_contain_or_resemble_a_number_are_not(self, text):
        assert numbers_in(text) == []

    def test_one_is_a_number_when_it_counts_something(self):
        assert numbers_in("Only one order is open") == [Decimal(1)]
        assert numbers_in("One refund") == [Decimal(1)]

    def test_words_can_be_switched_off(self):
        assert numbers_in("seven of 9", words=False) == [Decimal(9)]

    def test_find_numbers_keeps_the_text_as_written(self):
        assert find_numbers("Seven refunds, 12 orders, twenty-one fees") == [
            ("Seven", Decimal(7)), ("12", Decimal(12)), ("twenty-one", Decimal(21))]


class TestGrounding:

    def test_a_figure_from_a_result_is_grounded(self):
        r = result({"fees_paise": 138050, "fees_inr": "INR 1380.50"})
        assert ungrounded_numbers("Card fees were INR 1380.50.", "q", [r]) == []

    def test_equal_values_match_regardless_of_formatting(self):
        r = result({"fees_inr": "INR 1380.50"})
        assert ungrounded_numbers("About 1,380.5 in fees", "q", [r]) == []

    def test_an_invented_figure_is_flagged(self):
        r = result({"fees_inr": "INR 1380.50"})
        assert ungrounded_numbers("Fees were INR 9999.00", "q", [r]) == ["9999.00"]

    def test_a_sum_the_model_did_itself_is_flagged(self):
        """
        The documented failure in ask.py: two correct tool results, added by
        the model into a figure no query returned. Correct arithmetic is
        exactly what the check has to catch, because it reads as grounded.
        """
        a = result({"v_inr": "INR 1380.50"})
        b = result({"v_inr": "INR 105.62"})
        assert ungrounded_numbers("Together that is INR 1486.12", "q", [a, b]) == ["1486.12"]

    def test_the_users_own_figures_are_not_claims(self):
        r = result({"n": 4})
        assert ungrounded_numbers("Of orders over 5000, 4 were refunded.",
                                  "how many orders over 5000 were refunded?", [r]) == []

    def test_row_count_grounds_a_count_of_rows(self):
        r = result({"id": "a"}, {"id": "b"}, {"id": "c"})
        assert ungrounded_numbers("There are 3 of them.", "q", [r]) == []

    def test_dates_and_identifiers_ground_their_digits(self):
        r = result({"settlement_id": "setl_0003", "payout_date": "2026-08-14"})
        assert ungrounded_numbers("setl_0003 paid out on 14 August 2026", "q", [r]) == []

    def test_a_failed_query_grounds_nothing(self):
        bad = QueryResult(False, "SELECT", error="no such table: 777")
        assert ungrounded_numbers("It was 777.", "q", [bad]) == ["777"]

    def test_a_number_word_is_checked_like_a_digit(self):
        r = result({"n": 5})
        assert ungrounded_numbers("Seven refunds.", "q", [r]) == ["Seven"]
        assert ungrounded_numbers("Five refunds.", "q", [r]) == []

    def test_a_number_word_in_the_question_is_the_users_own_figure(self):
        assert ungrounded_numbers("Yes, seven.", "Are there seven refunds?", []) == []

    def test_a_number_word_inside_a_result_cell_grounds_nothing(self):
        r = result({"note": "seven days late"})
        assert ungrounded_numbers("Seven refunds.", "q", [r]) == ["Seven"]

    def test_a_pronoun_one_is_not_a_figure(self):
        assert ungrounded_numbers("It is the one with the gap.", "q", []) == []

    def test_a_spelled_total_that_no_query_returned_is_ungrounded(self):
        r = result({"n": 3}, {"n": 4})
        assert ungrounded_numbers("Seven in total.", "q", [r]) == ["Seven"]

    def test_no_queries_means_every_figure_is_ungrounded(self):
        assert ungrounded_numbers("Fees were 1380.50", "q", []) == ["1380.50"]

    def test_an_answer_with_no_figures_is_fine(self):
        assert ungrounded_numbers("The data does not contain that.", "q", []) == []


# --------------------------------------------------------------------------
# The agent loop
# --------------------------------------------------------------------------

class Scripted(Provider):
    name = "scripted"
    available = True

    def __init__(self, script):
        self.script = list(script)
        self.seen_system = None

    def complete(self, system, messages, tools=None, max_tokens=1024, model=None):
        self.seen_system = system
        return self.script.pop(0)

    @staticmethod
    def assistant_turn(resp):
        return {"role": "assistant", "content": resp.text}

    @staticmethod
    def tool_results_turn(results):
        return {"role": "user", "content": results}


def sql(q, id_="1", name="run_sql"):
    return LLMResponse(tool_calls=[ToolCall(id=id_, name=name, arguments={"query": q})])


def says(text):
    return LLMResponse(text=text)


FEES = ("SELECT SUM(fee_paise + gst_on_fee_paise) AS fees_paise FROM gateway_txns "
        "WHERE payment_method = 'card' AND txn_type = 'payment'")


class TestAsker:

    def expected_card_fees(self, conn):
        return run_query(conn, FEES).rows[0]["fees_inr"]

    def test_a_grounded_answer(self, conn):
        want = self.expected_card_fees(conn)
        script = [sql(FEES), says(f"Card fees were {want}.")]
        ans = SQLAsker(conn, Scripted(script)).ask("card fees?")
        assert ans.terminated == "answered" and ans.grounded
        assert ans.queries[0].sql == FEES, "the answer must carry the SQL that produced it"

    def test_an_invented_figure_is_flagged_not_hidden(self, conn):
        script = [sql(FEES), says("Card fees were INR 424242.42.")]
        ans = SQLAsker(conn, Scripted(script)).ask("card fees?")
        assert ans.terminated == "answered"
        assert not ans.grounded
        assert "424242.42" in ans.ungrounded

    def test_an_answer_with_no_query_cannot_be_grounded(self, conn):
        ans = SQLAsker(conn, Scripted([says("Card fees were 1380.50.")])).ask("card fees?")
        assert not ans.grounded and ans.ungrounded == ["1380.50"]

    def test_a_rejected_query_is_fed_back_and_the_model_can_recover(self, conn):
        want = self.expected_card_fees(conn)
        ans = SQLAsker(conn, Scripted([
            sql("DELETE FROM orders"), sql(FEES, id_="2"),
            says(f"Card fees were {want}.")])).ask("card fees?")
        assert [q.ok for q in ans.queries] == [False, True]
        assert ans.grounded
        assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] > 0

    def test_only_run_sql_exists(self, conn):
        ans = SQLAsker(conn, Scripted([sql("SELECT 1", name="shell"),
                                       says("Done.")])).ask("q")
        assert ans.queries == [] and ans.terminated == "answered"

    def test_step_limit_gives_up_instead_of_guessing(self, conn):
        script = [sql("SELECT COUNT(*) AS n FROM orders", id_=str(i)) for i in range(10)]
        provider = Scripted(script)
        ans = SQLAsker(conn, provider, max_steps=3).ask("q")
        assert ans.terminated == "step_limit"
        assert len(provider.script) == 7, "called the model past the budget"
        assert not ans.grounded

    def test_model_error_is_reported(self, conn):
        ans = SQLAsker(conn, Scripted([LLMResponse(error="503")])).ask("q")
        assert ans.terminated == "model_error" and not ans.grounded

    def test_no_provider_means_no_answer_and_says_so(self, conn):
        class Off(Scripted):
            available = False
            reason = "no key"
        ans = SQLAsker(conn, Off([])).ask("q")
        assert ans.terminated == "unavailable" and "no key" in ans.answer


class TestSchema:

    def test_row_counts_match_the_data(self, conn):
        text = describe_schema(conn)
        for table, n in counts(conn).items():
            assert f"{table}  ({n} rows)" in text

    def test_real_values_are_listed_so_the_model_does_not_guess(self, conn):
        text = describe_schema(conn)
        for value in ("'chargeback'", "'refund'", "'upi'", "'captured'"):
            assert value in text

    def test_prompt_embeds_the_generated_schema(self, conn):
        provider = Scripted([says("hello")])
        SQLAsker(conn, provider).ask("q")
        assert "gateway_txns" in provider.seen_system
        assert "'chargeback'" in provider.seen_system
