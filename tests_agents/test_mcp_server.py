"""
Tests for the MCP server.

The server holds no model, so nothing here needs a network or an API key. A
real MCP client is connected to the server in memory, which exercises the actual
protocol path (schema generation, argument validation, result conversion)
rather than calling the Python functions and hoping the wiring matches.

What is under test is the claim in the module docstring: the MCP surface is the
in-process agent's tool registry and nothing else, and it behaves the same way.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from mcp import Client  # noqa: E402

from matcher import load  # noqa: E402
from mcp_server import EXTRA_TOOLS, build_server  # noqa: E402
from tools import TOOL_SCHEMA, InvestigationTools, build_dispatch  # noqa: E402


@pytest.fixture(scope="module")
def server():
    return build_server(ROOT / "data")


@pytest.fixture(scope="module")
def batch():
    return load(ROOT / "data")


def run(server, fn):
    """Run `fn(client)` against the server over an in-memory connection."""
    async def go():
        async with Client(server) as client:
            return await fn(client)
    return asyncio.run(go())


class TestSurface:

    def test_exposes_the_agents_registry_and_two_lookups_only(self, server):
        listed = run(server, lambda c: c.list_tools())
        names = {t.name for t in listed.tools}
        assert names == {t["name"] for t in TOOL_SCHEMA} | set(EXTRA_TOOLS)

    def test_descriptions_are_the_agents_descriptions(self, server):
        listed = run(server, lambda c: c.list_tools())
        got = {t.name: t.description for t in listed.tools}
        for t in TOOL_SCHEMA:
            assert got[t["name"]] == t["description"]

    def test_input_schemas_match_the_agents_schemas(self, server):
        """Same parameter names and same required set, tool by tool."""
        listed = run(server, lambda c: c.list_tools())
        got = {t.name: t.input_schema for t in listed.tools}
        for t in TOOL_SCHEMA:
            want, have = t["input_schema"], got[t["name"]]
            assert set(have["properties"]) == set(want["properties"]), t["name"]
            assert set(have.get("required", [])) == set(want["required"]), t["name"]

    def test_every_tool_is_marked_read_only(self, server):
        listed = run(server, lambda c: c.list_tools())
        for t in listed.tools:
            assert t.annotations is not None, t.name
            assert t.annotations.read_only_hint is True, t.name
            assert t.annotations.destructive_hint is False, t.name

    def test_registry_is_closed(self, server):
        """A client cannot reach anything outside the registry."""
        for name in ("execute_sql", "delete_all_records", "run_shell"):
            res = run(server, lambda c, n=name: c.call_tool(n, {"x": 1}))
            assert res.is_error, name


class TestBehaviour:

    def test_each_tool_returns_what_the_in_process_tool_returns(self, server, batch):
        """
        One representative call per tool, compared with calling the tool
        directly. If the wrapper ever altered a result, this is where it would
        show.
        """
        orders, txns, settlements, bank = batch
        direct = build_dispatch(InvestigationTools(orders, txns, settlements, bank))
        s = settlements[0]
        cases = {
            "get_order": {"order_id": orders[0].order_id},
            "find_related_transactions": {"order_id": txns[0].order_ref},
            "search_settlements_by_amount": {"amount_paise": s.total_paise},
            "search_transactions_by_amount": {
                "amount_paise": txns[0].gross_amount_paise, "tolerance_paise": 100},
            "find_subset_summing_to": {
                "target_paise": s.total_paise, "on_date": str(s.capture_date)},
            "check_balance_continuity": {"bank_txn_id": bank[3].bank_txn_id},
            "check_fee_against_rule": {"txn_id": txns[0].txn_id},
            "check_settlement_composition": {"settlement_id": s.settlement_id},
            "check_payout_window": {"settlement_id": s.settlement_id,
                                    "observed_date": str(s.payout_date)},
        }
        assert set(cases) == set(direct), "a tool has no comparison case"

        for name, args in cases.items():
            want = direct[name](**args)
            got = run(server, lambda c, n=name, a=args: c.call_tool(n, a))
            assert not got.is_error, name
            data = got.structured_content
            assert data["ok"] == want.ok, name
            assert data["summary"] == want.summary, name
            assert data["evidence"] == want.evidence, name

    def test_a_miss_is_a_result_not_an_error(self, server):
        """"No such order" is information the investigator needs, so it comes
        back as ok=false with a summary rather than as a protocol error."""
        res = run(server, lambda c: c.call_tool("get_order", {"order_id": "NOPE"}))
        assert not res.is_error
        assert res.structured_content["ok"] is False

    def test_missing_arguments_are_rejected_at_the_boundary(self, server):
        res = run(server, lambda c: c.call_tool("get_order", {}))
        assert res.is_error

    def test_call_log_does_not_grow_in_a_long_running_server(self):
        """The in-process agent keeps a per-investigation log; a server that
        stays up must not accumulate one for ever."""
        server = build_server(ROOT / "data")

        async def many(c):
            for _ in range(20):
                await c.call_tool("get_order", {"order_id": "NOPE"})
        run(server, many)
        assert server.investigation_tools.calls == []


class TestLookups:

    def test_list_exceptions_matches_the_engine_and_hides_its_verdict(self, server):
        res = run(server, lambda c: c.call_tool("list_exceptions", {"limit": 100}))
        data = res.structured_content
        assert data["total"] == len(data["exceptions"]) > 0
        for row in data["exceptions"]:
            assert set(row) == {"entity_id", "entity_type", "detail"}

    def test_list_exceptions_limit_is_clamped(self, server):
        res = run(server, lambda c: c.call_tool("list_exceptions", {"limit": 0}))
        assert len(res.structured_content["exceptions"]) == 1

    def test_record_facts_only_for_unresolved_records(self, server):
        first = run(server, lambda c: c.call_tool("list_exceptions", {"limit": 1}))
        eid = first.structured_content["exceptions"][0]["entity_id"]
        ok = run(server, lambda c: c.call_tool("get_record_facts", {"entity_id": eid}))
        assert ok.structured_content["ok"] and ok.structured_content["facts"]

        miss = run(server, lambda c: c.call_tool(
            "get_record_facts", {"entity_id": "NOT-A-RECORD"}))
        assert miss.structured_content["ok"] is False


class TestTransport:

    def test_serves_over_a_real_stdio_subprocess(self):
        """The way Claude Desktop launches it: a child process speaking the
        protocol on stdout. Catches the failure the in-memory tests cannot, a
        stray print corrupting the channel."""
        from mcp import StdioServerParameters

        params = StdioServerParameters(
            command=sys.executable,
            args=[str(ROOT / "src" / "mcp_server.py"), "--data", str(ROOT / "data")])

        async def go():
            async with Client(params) as c:
                tools = await c.list_tools()
                res = await c.call_tool("check_balance_continuity",
                                        {"bank_txn_id": "NOPE"})
                return tools, res

        tools, res = asyncio.run(asyncio.wait_for(go(), timeout=60))
        assert len(tools.tools) == len(TOOL_SCHEMA) + len(EXTRA_TOOLS)
        assert res.structured_content["ok"] is False


class TestSQL:

    def test_schema_tool_lists_the_real_tables_and_values(self, server):
        res = run(server, lambda c: c.call_tool("describe_schema", {}))
        assert not res.is_error
        text = res.content[0].text
        assert "gateway_txns" in text and "'chargeback'" in text

    def test_run_sql_answers_a_question_the_nine_tools_cannot(self, server):
        res = run(server, lambda c: c.call_tool("run_sql", {
            "query": "SELECT payment_method, SUM(fee_paise + gst_on_fee_paise) "
                     "AS fees_paise FROM gateway_txns WHERE txn_type = 'payment' "
                     "GROUP BY payment_method"}))
        data = res.structured_content
        assert data["ok"] and data["row_count"] == len(data["rows"]) > 0
        assert all(r["fees_inr"].startswith("INR ") for r in data["rows"])

    @pytest.mark.parametrize("sql", [
        "DELETE FROM orders",
        "DROP TABLE orders",
        "SELECT * FROM orders; DELETE FROM orders",
        "PRAGMA query_only = OFF",
        "SELECT * FROM sqlite_master",
    ])
    def test_write_attempts_over_the_protocol_are_refused_and_change_nothing(
            self, sql):
        server = build_server(ROOT / "data")
        db = server.database
        before = db.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        res = run(server, lambda c: c.call_tool("run_sql", {"query": sql}))
        assert res.structured_content["ok"] is False
        assert db.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == before

    def test_runaway_query_is_stopped_over_the_protocol(self, server):
        res = run(server, lambda c: c.call_tool("run_sql", {
            "query": "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c) "
                     "SELECT COUNT(*) AS n FROM c"}))
        assert res.structured_content["ok"] is False
        assert "too much work" in res.structured_content["error"]
