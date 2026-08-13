from __future__ import annotations

import asyncio
import json

from fastapi import FastAPI
from pydantic import BaseModel, Field


class Item(BaseModel):
    name: str
    price: float = Field(gt=0)


app = FastAPI(title="Static API")


@app.post("/items/{item_id}", response_model=Item)
def put_item(item_id: int, item: Item) -> Item:
    assert item_id == 7
    return item


async def request(path: str, body: bytes) -> tuple[int, dict]:
    request_pending = True
    messages: list[dict] = []

    async def receive() -> dict:
        nonlocal request_pending
        if request_pending:
            request_pending = False
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode("ascii")),
        ],
        "client": ("127.0.0.1", 52100),
        "server": ("staticpython", 80),
    }
    await app(scope, receive, send)
    starts = [message for message in messages if message["type"] == "http.response.start"]
    assert len(starts) == 1
    response_body = b"".join(
        message.get("body", b"")
        for message in messages
        if message["type"] == "http.response.body"
    )
    return starts[0]["status"], json.loads(response_body)


async def main() -> None:
    status, payload = await request(
        "/items/7",
        json.dumps({"name": "widget", "price": "2.5"}).encode("utf-8"),
    )
    assert status == 200
    assert payload == {"name": "widget", "price": 2.5}

    status, payload = await request(
        "/items/7",
        json.dumps({"name": "broken", "price": 0}).encode("utf-8"),
    )
    assert status == 422
    assert payload["detail"][0]["type"] == "greater_than"
    assert payload["detail"][0]["loc"] == ["body", "price"]

    schema = app.openapi()
    assert schema["info"]["title"] == "Static API"
    assert "post" in schema["paths"]["/items/{item_id}"]


asyncio.run(main())
