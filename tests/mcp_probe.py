"""Live MCP handshake probe: initialize -> tools/list -> call one tool.

Usage: python tests/mcp_probe.py http://127.0.0.1:8000/mcp/
"""
import asyncio
import sys

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def main(url: str) -> int:
    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            info = await session.initialize()
            print(f"initialized: {info.serverInfo.name}")
            tools = await session.list_tools()
            names = [t.name for t in tools.tools]
            print(f"tools ({len(names)}): {names}")
            assert len(names) == 5, "expected 5 tools"
            result = await session.call_tool("get_headline", {})
            text = result.content[0].text
            assert '"weeks"' in text and '"forecast"' in text
            print(f"get_headline returned {len(text)} bytes - MCP HANDSHAKE OK")
    return 0


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000/mcp/"
    sys.exit(asyncio.run(main(url)))
