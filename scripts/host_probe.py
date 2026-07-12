"""Verify /mcp/ accepts non-localhost Host headers (the HF Space scenario)."""
import httpx

r = httpx.post(
    "http://127.0.0.1:8000/mcp/",
    headers={
        "Host": "northpoint-demo.hf.space",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    },
    json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-03-26",
        "capabilities": {}, "clientInfo": {"name": "probe", "version": "0"}}},
)
print("status:", r.status_code)
assert r.status_code != 421, "DNS-rebinding 421 still firing"
print("NON-LOCALHOST HOST ACCEPTED - MCP will work behind the HF proxy")
