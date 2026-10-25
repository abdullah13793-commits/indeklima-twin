"""End-to-end MCP test: spawn the server over stdio with the official client, list tools, call every tool."""
import json
import sys
from pathlib import Path

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]


async def _session_calls():
    params = StdioServerParameters(command=sys.executable, args=[str(ROOT / "src" / "mcp_server.py")])
    out = {}
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            init = await s.initialize()
            out["server"] = init.server_info.name
            out["tools"] = sorted(t.name for t in (await s.list_tools()).tools)

            async def call(name, args=None):
                res = await s.call_tool(name, args or {})
                assert not res.is_error, (name, res)
                sc = res.structured_content
                if sc is not None:
                    return sc["result"] if set(sc) == {"result"} else sc
                return json.loads(res.content[0].text)
            out["overview"] = await call("building_overview")
            out["broken"] = await call("list_rooms", {"broken_only": True})
            r1 = next(f["room"] for f in out["overview"]["findings"] if f["rule"] == "R1")
            out["promise"] = await call("room_promise", {"room_id": r1})
            out["findings"] = await call("list_findings", {"category": "building"})
            out["ts"] = await call("room_timeseries", {"room_id": r1, "period": "winter", "resolution_min": 120})
            out["sql"] = await call("query", {"sql": "select room, max(co2) as peak from sensors where period='winter' group by room order by peak desc limit 3"})
            out["sql_write"] = await call("query", {"sql": "delete from sensors"})
            out["sql_file"] = await call("query", {"sql": "select * from read_csv('C:/Windows/win.ini')"})
            out["bcf"] = await call("export_bcf")
    return out


def test_mcp_end_to_end():
    o = anyio.run(_session_calls)
    assert o["server"] == "indeklima-twin"
    assert {"building_overview", "list_rooms", "room_promise", "list_findings", "room_timeseries", "query", "export_bcf"} <= set(o["tools"])
    assert o["overview"]["rooms_monitored"] == 37
    assert any(r["room"] == o["promise"]["room"] for r in o["broken"])
    assert o["promise"]["explanations"] and "VAV" in o["promise"]["explanations"][0]["diagnosis"]
    assert len(o["ts"]["rows"]) > 50 and o["sql"]["rows"][0][0] == o["promise"]["room"]
    assert "error" in o["sql_write"] and "error" in o["sql_file"]          # read-only sandbox holds
    assert o["bcf"]["topics"] == 7
    (ROOT / "results" / "mcp_session.json").write_text(json.dumps(o, indent=1, default=str), encoding="utf-8")
