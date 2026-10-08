"""
Ask the reconciled batch questions in plain English, answered through SQL.

ask.py answers from a fixed menu of aggregate queries. This module is the open
version: the model writes the SQL itself, so a merchant can ask something the
menu never anticipated ("which UPI orders over 5,000 were refunded within two
days?") without anyone adding a tool first.

That is a much larger grant of power than nine named lookups, so the design is
about what the model is NOT allowed to do with it. Each limit is enforced in
code. None of them is requested in the prompt, because a rule in a prompt is a
request, and ask.py's own notes record the day the model broke one.

  * Read-only. The database is in memory and every statement runs under a
    SQLite authorizer that allows SELECT and reads and denies everything else:
    writes, DDL, PRAGMA, ATTACH, transactions. `PRAGMA query_only` is also on,
    as a second, independent barrier.
  * Functions are an allowlist. random() would make an answer unrepeatable,
    and zeroblob() / printf() can be used to exhaust memory, so a function
    runs only if it is on the list. SQLite's own limits on statement length,
    string length and expression depth are tightened as well.
  * Bounded work. A progress handler aborts a statement that runs too long, and
    at most MAX_ROWS rows come back, with truncation reported rather than
    hidden.
  * One statement per call, and the model gets at most MAX_STEPS calls. Running
    out escalates instead of guessing.
  * Grounding check. Every number in the final answer must appear in a query
    result (or in the question). This is the post-check ARCHITECTURE.md lists
    as unbuilt for ask.py. The model is also never asked to convert units: each
    `*_paise` column in a result arrives with a matching `*_inr` column holding
    the formatted amount, which it quotes as it is.

What the grounding check does and does not prove. It proves a figure in the
answer came out of the data. It does not prove the SQL computed the right thing:
a query that joins on the wrong key returns real numbers that answer a different
question, and the answer will pass. That gap is the reason every answer carries
the exact SQL that produced it, so a person can read the query and not just
trust the English. See NOTES.md for the same lesson learned the hard way.

Run:
    python src/sql_ask.py --data data "how much did I pay in fees on UPI?"
    python src/sql_ask.py --data data --sql "SELECT COUNT(*) AS n FROM orders"
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from core import paise_to_rupees_str  # noqa: E402
from llm import Provider, get_provider  # noqa: E402
from matcher import Engine, load  # noqa: E402

MAX_STEPS = 6
MAX_ROWS = 100
MAX_SQL_CHARS = 4000
VM_STEP_BUDGET = 3_000_000       # SQLite virtual-machine instructions per query

# The only functions a query may call. Everything else is denied, including
# every function that is non-deterministic or can allocate without bound.
ALLOWED_FUNCTIONS = frozenset({
    # aggregates
    "count", "sum", "total", "avg", "min", "max", "group_concat",
    # scalar
    "abs", "round", "coalesce", "ifnull", "nullif", "iif", "typeof",
    "length", "lower", "upper", "trim", "ltrim", "rtrim", "substr", "substring",
    "replace", "instr", "like", "glob", "printf", "format",
    # dates, which are stored as ISO text
    "date", "time", "datetime", "julianday", "strftime",
})

# A query may name only the tables the batch was loaded into.
TABLES = ("orders", "gateway_txns", "settlements", "bank_rows", "resolutions")


# --------------------------------------------------------------------------
# The database
# --------------------------------------------------------------------------

_DDL = {
    "orders": """CREATE TABLE orders (
        order_id TEXT PRIMARY KEY, order_amount_paise INTEGER, currency TEXT,
        order_datetime TEXT, customer_id TEXT, order_status TEXT,
        payment_method TEXT)""",
    "gateway_txns": """CREATE TABLE gateway_txns (
        txn_id TEXT PRIMARY KEY, txn_type TEXT, order_ref TEXT,
        gross_amount_paise INTEGER, fee_paise INTEGER, gst_on_fee_paise INTEGER,
        net_amount_paise INTEGER, txn_datetime TEXT, settlement_id TEXT,
        payment_method TEXT, status TEXT)""",
    "settlements": """CREATE TABLE settlements (
        settlement_id TEXT PRIMARY KEY, capture_date TEXT, payout_date TEXT,
        total_paise INTEGER, utr TEXT)""",
    "bank_rows": """CREATE TABLE bank_rows (
        bank_txn_id TEXT PRIMARY KEY, value_date TEXT, description TEXT,
        credit_paise INTEGER, debit_paise INTEGER, balance_paise INTEGER,
        utr TEXT)""",
    "resolutions": """CREATE TABLE resolutions (
        entity_id TEXT, entity_type TEXT, classification TEXT, tier INTEGER,
        matched_to TEXT, detail TEXT, resolved INTEGER)""",
}


def _iso(v: Any) -> Any:
    return v.isoformat() if hasattr(v, "isoformat") else v


def build_database(orders, txns, settlements, bank, resolutions) -> sqlite3.Connection:
    """
    Load a reconciled batch into an in-memory database and lock it.

    Population happens first and is the only time the connection can write;
    the guards are installed afterwards, so nothing a query says can alter what
    was loaded.
    """
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    for ddl in _DDL.values():
        conn.execute(ddl)

    conn.executemany("INSERT INTO orders VALUES (?,?,?,?,?,?,?)", [
        (o.order_id, o.order_amount_paise, o.currency, _iso(o.order_datetime),
         o.customer_id, o.order_status, o.payment_method) for o in orders])
    conn.executemany("INSERT INTO gateway_txns VALUES (?,?,?,?,?,?,?,?,?,?,?)", [
        (t.txn_id, t.txn_type, t.order_ref, t.gross_amount_paise, t.fee_paise,
         t.gst_on_fee_paise, t.net_amount_paise, _iso(t.txn_datetime),
         t.settlement_id, t.payment_method, t.status) for t in txns])
    conn.executemany("INSERT INTO settlements VALUES (?,?,?,?,?)", [
        (s.settlement_id, _iso(s.capture_date), _iso(s.payout_date),
         s.total_paise, s.utr) for s in settlements])
    conn.executemany("INSERT INTO bank_rows VALUES (?,?,?,?,?,?,?)", [
        (b.bank_txn_id, _iso(b.value_date), b.description, b.credit_paise,
         b.debit_paise, b.balance_paise, b.utr) for b in bank])
    conn.executemany("INSERT INTO resolutions VALUES (?,?,?,?,?,?,?)", [
        (r.entity_id, r.entity_type, r.classification, r.tier, r.matched_to,
         r.detail, 1 if r.resolved else 0) for r in resolutions])
    conn.commit()
    _lock(conn)
    return conn


def _authorizer(action, arg1, arg2, dbname, source):
    if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_RECURSIVE):
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_READ:
        # arg1 is the table. SQLite's own bookkeeping (sqlite_master and its
        # relatives) is off limits: the schema comes from describe_schema(),
        # and a query has no reason to read the engine's internals. Other
        # names are allowed rather than listed, because a recursive CTE reads
        # its own name and cannot be told apart from a table here. Nothing
        # else exists in this database to read, and a runaway recursion is
        # stopped by the work budget in run_query.
        return (sqlite3.SQLITE_DENY if str(arg1).lower().startswith("sqlite_")
                else sqlite3.SQLITE_OK)
    if action == sqlite3.SQLITE_FUNCTION:
        return (sqlite3.SQLITE_OK if str(arg2).lower() in ALLOWED_FUNCTIONS
                else sqlite3.SQLITE_DENY)
    return sqlite3.SQLITE_DENY


def _lock(conn: sqlite3.Connection) -> None:
    if not hasattr(conn, "setlimit"):
        # Connection.setlimit arrived in Python 3.11. Without it a query can
        # double a string in a recursive CTE until memory runs out, and the
        # work budget does not notice because few steps are involved. Refusing
        # to run is safer than running without the limit.
        raise RuntimeError("sql_ask needs Python 3.11 or newer "
                           "(sqlite3.Connection.setlimit)")
    conn.execute("PRAGMA query_only = ON")
    conn.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, MAX_SQL_CHARS)
    conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 100_000)
    conn.setlimit(sqlite3.SQLITE_LIMIT_EXPR_DEPTH, 60)
    conn.setlimit(sqlite3.SQLITE_LIMIT_COMPOUND_SELECT, 8)
    conn.setlimit(sqlite3.SQLITE_LIMIT_FUNCTION_ARG, 8)
    conn.setlimit(sqlite3.SQLITE_LIMIT_LIKE_PATTERN_LENGTH, 100)
    conn.set_authorizer(_authorizer)


def build_from_dir(datadir: str | Path) -> sqlite3.Connection:
    orders, txns, settlements, bank = load(Path(datadir))
    resolutions = Engine(orders, txns, settlements, bank).run()
    return build_database(orders, txns, settlements, bank, resolutions)


# --------------------------------------------------------------------------
# Schema, generated from the database itself so it cannot drift from it
# --------------------------------------------------------------------------

def describe_schema(conn: sqlite3.Connection) -> str:
    """
    The schema as text: columns, types, row counts, and the values of every
    low-cardinality text column.

    Listing the real values is deliberate. A model that guesses that a refund
    is stored as 'Refund' writes a query that returns nothing and then reports,
    confidently, that there were no refunds.
    """
    lines = ["Tables (amounts are integer paise; 100 paise = 1 INR; dates are ISO text):"]
    for table in TABLES:
        n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        cols = _columns(conn, table)
        lines.append(f"\n{table}  ({n} rows)")
        for name, ctype in cols:
            note = ""
            if ctype == "TEXT":
                vals = [r[0] for r in conn.execute(
                    f"SELECT DISTINCT {name} FROM {table} WHERE {name} IS NOT NULL "
                    f"LIMIT 9")]
                if 0 < len(vals) <= 8:
                    note = "  values: " + ", ".join(repr(v) for v in sorted(vals))
            lines.append(f"  {name} {ctype}{note}")
    return "\n".join(lines)


_COLUMNS: dict[str, list[tuple[str, str]]] = {}


def _columns(conn, table):
    # PRAGMA is denied by the authorizer, so column lists come from the DDL we
    # wrote above rather than from the database.
    if table not in _COLUMNS:
        body = _DDL[table].split("(", 1)[1].rsplit(")", 1)[0]
        cols = []
        for part in body.split(","):
            bits = part.split()
            if bits:
                cols.append((bits[0], bits[1]))
        _COLUMNS[table] = cols
    return _COLUMNS[table]


# --------------------------------------------------------------------------
# Running a query
# --------------------------------------------------------------------------

@dataclass
class QueryResult:
    ok: bool
    sql: str
    error: str = ""
    columns: list[str] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    row_count: int = 0
    truncated: bool = False

    def payload(self) -> dict[str, Any]:
        """What the model sees."""
        if not self.ok:
            return {"ok": False, "error": self.error}
        return {"ok": True, "columns": self.columns, "rows": self.rows,
                "row_count": self.row_count, "truncated": self.truncated}


_LEAD = re.compile(r"^\s*(?:--[^\n]*\n\s*|/\*.*?\*/\s*)*(select|with)\b",
                   re.IGNORECASE | re.DOTALL)


def run_query(conn: sqlite3.Connection, sql: str) -> QueryResult:
    """
    Run one read-only statement. Never raises: a rejected or failing query is a
    result the model can read and correct, not a crash.
    """
    sql = (sql or "").strip().rstrip(";").strip()
    if not sql:
        return QueryResult(False, sql, error="empty query")
    if len(sql) > MAX_SQL_CHARS:
        return QueryResult(False, sql, error=f"query longer than {MAX_SQL_CHARS} characters")
    if not _LEAD.match(sql):
        return QueryResult(False, sql, error="only SELECT queries are allowed")

    budget = {"ticks": 0}

    def tick() -> int:
        budget["ticks"] += 1
        return 1 if budget["ticks"] * 1000 > VM_STEP_BUDGET else 0

    conn.set_progress_handler(tick, 1000)
    try:
        cur = conn.execute(sql)
        names = [d[0] for d in cur.description or []]
        raw = cur.fetchmany(MAX_ROWS + 1)
    except sqlite3.Error as exc:
        msg = str(exc)
        if "interrupted" in msg:
            msg = "query used too much work and was stopped; simplify it"
        elif "not authorized" in msg:
            msg = f"not allowed: {msg}"
        return QueryResult(False, sql, error=msg)
    finally:
        conn.set_progress_handler(None, 0)

    truncated = len(raw) > MAX_ROWS
    raw = raw[:MAX_ROWS]
    columns, rows = _with_inr(names, raw)
    return QueryResult(True, sql, columns=columns, rows=rows,
                       row_count=len(rows), truncated=truncated)


def _with_inr(names: list[str], raw: list[tuple]) -> tuple[list[str], list[dict]]:
    """
    Add a formatted `<name>_inr` beside every `<name>_paise` integer column.

    The model is never asked to divide by 100. An unlabelled "1770.20" was once
    rendered as dollars, and an unconverted 177020 invites the opposite error,
    so the conversion is done here, once, in code, with the unit attached.
    """
    columns: list[str] = []
    for n in names:
        columns.append(n)
        if n.endswith("_paise"):
            columns.append(n[:-len("_paise")] + "_inr")

    rows = []
    for tup in raw:
        row: dict[str, Any] = {}
        for n, v in zip(names, tup, strict=True):
            row[n] = v
            if n.endswith("_paise"):
                inr = n[:-len("_paise")] + "_inr"
                row[inr] = (f"INR {paise_to_rupees_str(int(v))}"
                            if isinstance(v, int) and not isinstance(v, bool) else None)
        rows.append(row)
    return columns, rows


# --------------------------------------------------------------------------
# Grounding check
# --------------------------------------------------------------------------

_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def numbers_in(text: str) -> list[Decimal]:
    out = []
    for tok in _NUM.findall(text or ""):
        tok = tok.rstrip(",").replace(",", "")
        try:
            out.append(Decimal(tok))
        except InvalidOperation:
            continue
    return out


def grounded_values(question: str, results: list[QueryResult]) -> set[Decimal]:
    """
    Every number the answer is allowed to contain: the numbers in the
    question (echoing the user's own figure is not a claim), every number in
    every successful result cell, and each result's row count.

    Numbers inside strings count, so dates ('2026-08-21'), identifiers
    ('setl_0003') and formatted amounts ('INR 1770.20') all ground their digits.
    """
    allowed = set(numbers_in(question))
    for r in results:
        if not r.ok:
            continue
        allowed.add(Decimal(r.row_count))
        for row in r.rows:
            for v in row.values():
                if v is not None:
                    allowed.update(numbers_in(str(v)))
    return allowed


def ungrounded_numbers(answer: str, question: str,
                       results: list[QueryResult]) -> list[str]:
    allowed = grounded_values(question, results)
    seen: list[str] = []
    for tok in _NUM.findall(answer or ""):
        clean = tok.rstrip(",").replace(",", "")
        try:
            if Decimal(clean) not in allowed and tok.rstrip(",") not in seen:
                seen.append(tok.rstrip(","))
        except InvalidOperation:
            continue
    return seen


# --------------------------------------------------------------------------
# The agent
# --------------------------------------------------------------------------

SQL_TOOL_SCHEMA = [{
    "name": "run_sql",
    "description": "Run one read-only SQLite SELECT against the batch and get "
                   "the rows back. Do all counting, summing and arithmetic in "
                   "the SQL.",
    "input_schema": {"type": "object", "properties": {
        "query": {"type": "string"}}, "required": ["query"]},
}]

SYSTEM_PROMPT = """You answer questions about one reconciled payments batch \
(merchant ledger, payment-gateway report, settlements, bank statement) by \
writing SQL.

{schema}

How to work:
  * Use run_sql. You have at most {max_steps} calls. One SELECT per call.
  * Do every count, sum, difference and rate inside the SQL. Never calculate \
in your head and never combine two result figures yourself: if you need a \
total of two things, write a query that returns the total.
  * Every `*_paise` column in a result comes with a `*_inr` column holding the \
formatted amount. Quote the `_inr` value exactly as given.
  * Look at the values listed above before filtering. Use them exactly.
  * If a query returns nothing or an error, say what happened and try a \
corrected query. If the data cannot answer the question, say so plainly.

When you have what you need, answer in two or three plain sentences using only \
figures that appeared in a result. A figure that did not come from a query \
result will be flagged to the reader."""


@dataclass
class Answer:
    question: str
    answer: str = ""
    queries: list[QueryResult] = field(default_factory=list)
    terminated: str = ""      # answered | step_limit | model_error | unavailable
    model_calls: int = 0
    ungrounded: list[str] = field(default_factory=list)

    @property
    def grounded(self) -> bool:
        return self.terminated == "answered" and not self.ungrounded


class SQLAsker:
    def __init__(self, conn: sqlite3.Connection, provider: Provider | None = None,
                 max_steps: int = MAX_STEPS):
        self.conn = conn
        self.provider = provider or get_provider()
        self.available = self.provider.available
        self.max_steps = max_steps
        self.system = SYSTEM_PROMPT.format(schema=describe_schema(conn),
                                           max_steps=max_steps)

    def ask(self, question: str) -> Answer:
        out = Answer(question=question)
        if not self.available:
            out.terminated = "unavailable"
            out.answer = (f"not run: "
                          f"{getattr(self.provider, 'reason', 'no provider')}")
            return out

        messages: list[dict] = [{"role": "user", "content": question}]
        for _ in range(self.max_steps):
            resp = self.provider.complete(self.system, messages,
                                          tools=SQL_TOOL_SCHEMA, max_tokens=1024)
            out.model_calls += 1

            if not resp.ok:
                out.terminated = "model_error"
                out.answer = f"aborted: {resp.error[:120]}"
                return out

            if not resp.wants_tools:
                out.answer = resp.text.strip()
                out.terminated = "answered"
                out.ungrounded = ungrounded_numbers(out.answer, question, out.queries)
                return out

            messages.append(self.provider.assistant_turn(resp))
            replies = []
            for use in resp.tool_calls:
                if use.name != "run_sql":
                    payload = {"ok": False, "error": f"tool '{use.name}' is not available"}
                else:
                    qr = run_query(self.conn, str(use.arguments.get("query", "")))
                    out.queries.append(qr)
                    payload = qr.payload()
                replies.append((use.id, payload))
            messages.append(self.provider.tool_results_turn(replies))

        out.terminated = "step_limit"
        out.answer = (f"No answer: the investigation did not conclude within "
                      f"{self.max_steps} queries.")
        return out


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _print_result(qr: QueryResult) -> None:
    if not qr.ok:
        print(f"  rejected: {qr.error}")
        return
    print(f"  {qr.row_count} row(s){' (truncated)' if qr.truncated else ''}")
    for row in qr.rows[:10]:
        print("   ", json.dumps(row, default=str))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("question", nargs="?", default="")
    ap.add_argument("--data", default="data")
    ap.add_argument("--provider", default="")
    ap.add_argument("--sql", default="",
                    help="run one query directly through the same guard, "
                         "with no model")
    args = ap.parse_args()

    conn = build_from_dir(args.data)

    if args.sql:
        _print_result(run_query(conn, args.sql))
        return
    if not args.question:
        print(describe_schema(conn))
        return

    ans = SQLAsker(conn, provider=get_provider(args.provider or None)).ask(args.question)
    print(ans.answer)
    print()
    for i, q in enumerate(ans.queries, 1):
        print(f"[{i}] {q.sql}")
        _print_result(q)
    if ans.ungrounded:
        print("\nWARNING: these figures appear in the answer but in no query "
              f"result: {', '.join(ans.ungrounded)}")
    print(f"\n({ans.terminated}, {ans.model_calls} model call(s))")


if __name__ == "__main__":
    main()
