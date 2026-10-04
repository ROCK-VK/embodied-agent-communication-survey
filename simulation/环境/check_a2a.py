"""Check installed A2A SDK types and its official Agent Card HTTP route."""
import asyncio
import json
import platform
from importlib.metadata import version
from pathlib import Path

import httpx
from starlette.applications import Starlette
from a2a.server.routes import create_agent_card_routes
from a2a.types import AgentCard
from a2a.utils.constants import AGENT_CARD_WELL_KNOWN_PATH

async def main():
    card = AgentCard(name="Environment check", description="Local SDK acceptance only",
                     version="0.0.1", default_input_modes=["text/plain"],
                     default_output_modes=["text/plain"])
    copied = AgentCard()
    copied.ParseFromString(card.SerializeToString())
    assert copied.name == card.name
    app = Starlette(routes=create_agent_card_routes(card))
    # In-process HTTP validates the SDK route without reserving any host port.
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://localhost") as client:
        response = await client.get(AGENT_CARD_WELL_KNOWN_PATH)
        response.raise_for_status()
        assert response.json()["name"] == card.name
    result = {"scope": "SDK protobuf and Agent Card HTTP ASGI smoke only",
              "python": platform.python_version(), "sdk": version("a2a-sdk"),
              "http_status": response.status_code, "card_path": AGENT_CARD_WELL_KNOWN_PATH}
    output = Path(__file__).parent / "验收产物"
    output.mkdir(exist_ok=True)
    (output / "a2a-check.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    asyncio.run(main())
