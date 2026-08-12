from __future__ import annotations

import asyncio
import socket

from uvicorn import Config, Server


RESPONSE_BODY = b"static-uvicorn"


async def app(scope, receive, send) -> None:
    if scope["type"] != "http" or scope["path"] != "/probe":
        raise AssertionError(f"unexpected ASGI scope: {scope!r}")
    request = await receive()
    if request["type"] != "http.request":
        raise AssertionError(f"unexpected ASGI request event: {request!r}")
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", b"text/plain")],
        }
    )
    await send(
        {
            "type": "http.response.body",
            "body": RESPONSE_BODY,
        }
    )


async def probe() -> None:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    listener.setblocking(False)

    config = Config(
        app=app,
        loop="asyncio",
        http="h11",
        ws="none",
        lifespan="off",
        log_config=None,
        access_log=False,
        timeout_keep_alive=1,
    )
    server = Server(config)
    task = asyncio.create_task(server.serve(sockets=[listener]))
    writer = None
    try:
        for _ in range(500):
            if server.started:
                break
            if task.done():
                await task
                raise AssertionError("Uvicorn stopped before accepting connections")
            await asyncio.sleep(0.01)
        if not server.started:
            raise AssertionError("Uvicorn did not start within five seconds")

        host, port = listener.getsockname()[:2]
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=5,
        )
        writer.write(
            b"GET /probe HTTP/1.1\r\n"
            b"Host: 127.0.0.1\r\n"
            b"Connection: close\r\n\r\n"
        )
        await writer.drain()
        response = await asyncio.wait_for(reader.read(), timeout=5)
        if b"HTTP/1.1 200 OK" not in response or RESPONSE_BODY not in response:
            raise AssertionError(f"unexpected Uvicorn response: {response!r}")
    finally:
        if writer is not None:
            writer.close()
            await writer.wait_closed()
        server.should_exit = True
        try:
            await asyncio.wait_for(task, timeout=5)
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            listener.close()


asyncio.run(probe())
