from __future__ import annotations

import os
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict, List
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route
from starlette.testclient import TestClient
from starlette.types import ASGIApp, Receive, Scope, Send

from lazgi import LazyApp

DATABASE_QUERIES: Dict[str, List[str]] = defaultdict(list)


@pytest.fixture(autouse=True)
def clear_db() -> None:
    DATABASE_QUERIES.clear()


class DataBase:
    """
    A placeholder representing a database
    that needs to be initialized from an async context
    """

    def __init__(self, queries: List[str]) -> None:
        self.queries = queries

    async def execute(self, __query: str) -> None:
        self.queries.append(__query)

    @classmethod
    @asynccontextmanager
    async def connect(cls, __dsn: str) -> AsyncIterator[DataBase]:
        yield cls(DATABASE_QUERIES[__dsn])


class HTTPResource:
    """
    A hypothetical CBV like thing base class.
    This would be provided by a web framework.
    """

    def __init__(self) -> None:
        ...

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        assert scope["type"] == "http"
        method: str = scope["method"]
        handler = getattr(self, f"on_{method.lower()}")
        resp: Response = await handler(Request(scope, receive, send))
        await resp(scope, receive, send)


# User code
class MyHTTPResource(HTTPResource):
    def __init__(self, db: DataBase) -> None:
        self.db = db

    async def on_get(self, request: Request) -> Response:
        await self.db.execute("endpoint")
        return Response(content=b"Hello!", status_code=200)


@asynccontextmanager
async def lifespan_tester(app: Starlette) -> AsyncIterator[None]:
    """Exists only to make sure the app's lifespan gets called"""
    db: DataBase = app.state.db
    await db.execute("lifespan")
    yield


def create_app(db: DataBase) -> Starlette:
    routes = [Route("/", MyHTTPResource(db))]
    app = Starlette(routes=routes, lifespan=lifespan_tester)
    app.state.db = db
    return app


@asynccontextmanager
async def main() -> AsyncIterator[ASGIApp]:
    dsn = os.environ["DB_DSN"]
    async with DataBase.connect(dsn) as db:
        yield create_app(db)


# this is a global variable accessible from Gunicorn or Uvicorn
app = LazyApp(main)


def test_lazy_app_loaded_via_env() -> None:
    """Simulate what this would look like if the app is called
    from Gunicorn of Uvicorn's command line
    """
    with patch.dict(os.environ, {"DB_DSN": "admin@example.com"}):
        with TestClient(app) as client:
            resp = client.get("/")
            assert resp.status_code == 200
    # make sure LazyApp forwards lifespans correctly
    assert DATABASE_QUERIES == {"admin@example.com": ["lifespan", "endpoint"]}


@pytest.mark.anyio
async def test_lazy_app_from_tests() -> None:
    """Simulate calling the app from tests"""
    # this would all be fixtures
    # that run schema migrations, etc.
    async with DataBase.connect("localhost") as db:
        app = create_app(db)
        client = AsyncClient(app=app, base_url="http://example.com")
        resp = await client.get("/")
        assert resp.status_code == 200
    # the app's lifespan won't be triggered
    assert DATABASE_QUERIES == {"localhost": ["endpoint"]}
