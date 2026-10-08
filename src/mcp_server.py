"""
MCP server over the investigation tools.

Any MCP client (Claude Desktop, an IDE, another agent framework) can connect
and run the same investigation the built-in resolution agent runs, using the
same nine deterministic tools:

    python src/mcp_server.py --data data                      # stdio
    python src/mcp_server.py --data data --transport streamable-http

Two decisions worth knowing before reading the code.

The tool list is not written out a second time. It is built from TOOL_SCHEMA
and build_dispatch() in tools.py, the same registry the in-process agent uses,
so the two surfaces cannot drift: add a tool there and it appears here, and a
test fails if the names or descriptions ever differ.

The server is read-only by construction. Every tool computes from a batch that
was loaded once at start-up and never written back, and each tool is marked
readOnlyHint so a client can run them without asking for approval. Four extra
tools are provided so a client has somewhere to start (list_exceptions,
get_record_facts) and can ask questions the nine tools were not written for
(describe_schema, run_sql). All four come from deterministic code, not a model.
run_sql accepts a SELECT and nothing else, under the guards documented in
sql_ask.py: an authorizer, a function allowlist, a work budget and a row cap,
with money returned alongside a formatted INR column so no client has to divide
by 100. The
server itself contains no model call and needs no API key. Whatever is on the
other end of the connection supplies the strategy; these tools supply the
truth, exactly as in agent.py.

Nothing in this module may write to stdout: under the stdio transport stdout is
the protocol channel, and a stray print corrupts it.
"""

from __future__ import annotations

import argparse
import inspect
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mcp.server.mcpserver import MCPServer  # noqa: E402
from mcp.types import ToolAnnotations  # noqa: E402

from investigate import facts_for  # noqa: E402
from matcher import Engine, load  # noqa: E402
from sql_ask import build_database, describe_schema, run_query  # noqa: E402
from tools import TOOL_SCHEMA, InvestigationTools, build_dispatch  # noqa: E402

SERVER_NAME = "recon-investigation"

EXTRA_TOOLS = ("list_exceptions", "get_record_facts", "describe_schema", "run_sql")

_READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                             idempotentHint=True, openWorldHint=False)


def _wrap(tools: InvestigationTools, fn):
    """
    Adapt a tool method to MCP.

    The SDK derives the input schema from the signature, so the wrapper
    carries the original parameters (resolved to real types, because tools.py
    uses postponed annotations) and declares a dict return. It must not use
    functools.wraps: that sets __wrapped__, the SDK follows it, and the output
    is then validated against the original ToolResult return type instead of
    the dict actually returned. The ToolResult dataclass is flattened to a dict,
    and the tool's call log is cleared afterwards: the agent keeps that log per
    investigation, but a server that stays up for days would otherwise grow it
    for ever.
    """
    def call(*args, **kwargs) -> dict[str, Any]:
        try:
            r = fn(*args, **kwargs)
            return {"ok": r.ok, "summary": r.summary, "evidence": r.evidence}
        finally:
            tools.calls.clear()

    sig = inspect.signature(fn, eval_str=True)
    call.__signature__ = sig.replace(return_annotation=dict[str, Any])
    call.__name__ = fn.__name__
    call.__doc__ = fn.__doc__
    return call


def build_server(datadir: str | Path = "data") -> MCPServer:
    orders, txns, settlements, bank = load(Path(datadir))
    resolutions = Engine(orders, txns, settlements, bank).run()
    exceptions = [r for r in resolutions if not r.resolved]
    by_id = {r.entity_id: r for r in exceptions}

    tools = InvestigationTools(orders, txns, settlements, bank)
    db = build_database(orders, txns, settlements, bank, resolutions)
    descriptions = {t["name"]: t["description"] for t in TOOL_SCHEMA}

    server = MCPServer(
        SERVER_NAME,
        instructions=(
            "Read-only tools over one reconciled payment batch (merchant ledger, "
            "gateway report, settlement report, bank statement). Start with "
            "list_exceptions, then get_record_facts for a record, then use the "
            "check_* and search_* tools to gather evidence. Every result is "
            "computed deterministically. Report only what a tool returned, and "
            "do not do arithmetic yourself."))

    for name, fn in build_dispatch(tools).items():
        server.add_tool(_wrap(tools, fn), name=name,
                        description=descriptions[name], annotations=_READ_ONLY)

    @server.tool(annotations=_READ_ONLY)
    def list_exceptions(limit: int = 25) -> dict[str, Any]:
        """List records the deterministic tiers could not resolve, each with
        the reason the automated tiers give. The matcher's classification is
        deliberately left out, as it is in the in-process agent's context, so
        an investigation reaches its own conclusion."""
        limit = max(1, min(int(limit), 100))
        return {"total": len(exceptions),
                "exceptions": [{"entity_id": r.entity_id,
                                "entity_type": r.entity_type,
                                "detail": r.detail}
                               for r in exceptions[:limit]]}

    @server.tool(annotations=_READ_ONLY)
    def get_record_facts(entity_id: str) -> dict[str, Any]:
        """Raw values for one unresolved record (identifiers and amounts, no
        conclusions). The matcher's classification is deliberately not
        included, so an investigation stays independent of it."""
        r = by_id.get(entity_id)
        if r is None:
            return {"ok": False,
                    "summary": f"{entity_id} is not an unresolved record"}
        return {"ok": True, "entity_type": r.entity_type,
                "facts": facts_for(r, orders, txns, settlements, bank)}

    @server.tool(name="describe_schema", annotations=_READ_ONLY)
    def describe_schema_tool() -> str:
        """Tables and columns of the batch for use with run_sql, with the real
        values of every low-cardinality column. Call this before writing SQL."""
        return describe_schema(db)

    @server.tool(annotations=_READ_ONLY)
    def run_sql(query: str) -> dict[str, Any]:
        """Run one read-only SQLite SELECT over the batch. Every *_paise column
        comes back with a matching *_inr column; quote that one. At most 100
        rows are returned and truncation is reported. Do counting, summing and
        arithmetic in the SQL, not afterwards."""
        return run_query(db, query).payload()

    # Exposed so tests can check the tools' state directly. Not part of the
    # protocol surface.
    server.investigation_tools = tools
    server.database = db
    return server


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--data", default="data")
    ap.add_argument("--transport", default="stdio",
                    choices=["stdio", "streamable-http"])
    args = ap.parse_args()
    build_server(args.data).run(args.transport)


if __name__ == "__main__":
    main()
