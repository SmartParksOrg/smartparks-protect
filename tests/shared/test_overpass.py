"""The one call to an Overpass API (phase 33, decision D270): the answer read, a busy server's
refusal tried once more, a final word passed straight on, and the reason kept either way."""

import asyncio

import httpx
import pytest

from shared import overpass
from shared.trace import ApplicationError


def _mock_client(monkeypatch, handler):
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs.setdefault("transport", httpx.MockTransport(handler))
        return real(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    monkeypatch.setattr(overpass, "RETRY_PAUSE_S", 0.0)


def _fetch():
    return asyncio.run(overpass.fetch_overpass("https://overpass.example/api", "[out:json];"))


def test_the_query_goes_out_and_the_answer_comes_back(monkeypatch):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"elements": []})

    _mock_client(monkeypatch, handler)
    assert _fetch() == {"elements": []}
    assert len(seen) == 1
    assert b"data=" in seen[0].content
    assert seen[0].headers["User-Agent"].startswith("SmartParksProtect/")


def test_a_busy_server_is_asked_once_more(monkeypatch):
    answers = [httpx.Response(504, text="gateway timeout"), httpx.Response(200, json={"ok": 1})]
    asked = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal asked
        asked += 1
        return answers.pop(0)

    _mock_client(monkeypatch, handler)
    assert _fetch() == {"ok": 1}
    assert asked == 2


def test_a_refusal_that_holds_is_the_answer_with_its_reason(monkeypatch):
    asked = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal asked
        asked += 1
        return httpx.Response(504, text="gateway timeout")

    _mock_client(monkeypatch, handler)
    with pytest.raises(ApplicationError) as failure:
        _fetch()
    assert "504" in failure.value.message and failure.value.retryable
    assert asked == overpass.ATTEMPTS


def test_a_server_that_cannot_be_reached_is_tried_again(monkeypatch):
    asked = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal asked
        asked += 1
        if asked == 1:
            raise httpx.ConnectError("no route", request=request)
        return httpx.Response(200, json={"elements": []})

    _mock_client(monkeypatch, handler)
    assert _fetch() == {"elements": []}
    assert asked == 2


def test_a_final_word_is_not_repeated(monkeypatch):
    asked = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal asked
        asked += 1
        return httpx.Response(400, text="line 1: parse error")

    _mock_client(monkeypatch, handler)
    with pytest.raises(ApplicationError) as failure:
        _fetch()
    assert "400" in failure.value.message and not failure.value.retryable
    assert asked == 1


def test_an_answer_that_is_not_json_is_refused(monkeypatch):
    asked = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal asked
        asked += 1
        return httpx.Response(200, text="<html>maintenance</html>")

    _mock_client(monkeypatch, handler)
    with pytest.raises(ApplicationError) as failure:
        _fetch()
    assert "not JSON" in failure.value.message
    assert asked == 1


def test_several_servers_are_asked_in_turn(monkeypatch):
    """Decision D279: a host pinned to a tired backend is refused nearly every time, so the
    next attempt goes to another server rather than to the same one again."""
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        return (
            httpx.Response(504, text="gateway timeout")
            if "first" in str(request.url)
            else httpx.Response(200, json={"elements": []})
        )

    _mock_client(monkeypatch, handler)
    answer = asyncio.run(
        overpass.fetch_overpass(
            "https://first.example/api , https://second.example/api", "[out:json];"
        )
    )
    assert answer == {"elements": []}
    assert asked == ["https://first.example/api", "https://second.example/api"]


def test_every_server_refusing_is_the_answer_with_the_reason(monkeypatch):
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        return httpx.Response(504, text="gateway timeout")

    _mock_client(monkeypatch, handler)
    with pytest.raises(ApplicationError) as failure:
        asyncio.run(
            overpass.fetch_overpass(
                ["https://first.example/api", "https://second.example/api"], "[out:json];"
            )
        )
    assert "504" in failure.value.message
    assert failure.value.context["url"] == "https://second.example/api"
    # both servers, twice each, and no more
    assert len(asked) == overpass.ATTEMPTS
    assert asked.count("https://first.example/api") == 2


def test_a_list_of_one_behaves_as_one_server(monkeypatch):
    assert overpass.servers("  https://one.example/api  ") == ["https://one.example/api"]
    assert overpass.servers("a,,b , c") == ["a", "b", "c"]
    assert overpass.servers([" a ", ""]) == ["a"]
    with pytest.raises(ApplicationError) as failure:
        asyncio.run(overpass.fetch_overpass("  ,  ", "[out:json];"))
    assert "No OpenStreetMap server" in failure.value.message
