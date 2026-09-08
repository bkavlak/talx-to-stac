import json
from pathlib import Path

import httpx
import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def schedule_payload() -> dict:
    return fixture("foss4g-europe-2025.schedule.json")


@pytest.fixture
def video_payload() -> dict:
    return fixture("foss4geurope.videos.json")


def stub_client(routes: dict[str, dict]) -> httpx.Client:
    """A client that answers with canned JSON, matched on URL path substring."""

    def handler(request: httpx.Request) -> httpx.Response:
        for fragment, payload in routes.items():
            if fragment in str(request.url):
                return httpx.Response(200, json=payload)
        return httpx.Response(404, json={})

    return httpx.Client(transport=httpx.MockTransport(handler))
