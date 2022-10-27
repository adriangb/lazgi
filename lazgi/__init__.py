from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncContextManager, AsyncIterator, Callable

from asgi_lifespan_middleware import LifespanMiddleware

from lazgi._types import ASGIApp, Receive, Scope, Send


class LazyApp:
    __slots__ = ("_factory", "_call")
    _call: ASGIApp

    def __init__(self, __factory: Callable[[], AsyncContextManager[ASGIApp]]) -> None:
        self._factory = __factory
        self._call = self._handle_lifespan

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self._call(scope, receive, send)

    async def _handle_lifespan(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        if scope["type"] == "lifespan":

            @asynccontextmanager
            async def lifespan(*args: Any) -> AsyncIterator[None]:
                try:
                    async with self._factory() as self._call:
                        yield
                finally:
                    self._call = self._handle_lifespan

            await LifespanMiddleware(self.__call__, lifespan=lifespan)(
                scope, receive, send
            )
            return
        await self._call(scope, receive, send)
        return
