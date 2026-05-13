"""Integration-style test for `LocaleMiddleware` against a minimal FastAPI app.

We avoid spinning up the full MemStack app (heavy DB / Redis fixtures) and
instead mount only the middleware + a probe route. The probe echoes the
translated form of a known catalog key plus the resolved locale so we can
assert end-to-end behaviour: header → contextvar → gettext → response.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.infrastructure.i18n import current_locale, gettext
from src.infrastructure.i18n.middleware import LocaleMiddleware


@pytest.fixture
def app() -> FastAPI:
    fastapi_app = FastAPI()
    fastapi_app.add_middleware(LocaleMiddleware)

    @fastapi_app.get("/probe")
    async def probe() -> dict[str, str]:
        return {
            "locale": current_locale(),
            "message": gettext("Invalid email or password"),
        }

    return fastapi_app


@pytest.mark.asyncio
async def test_default_locale_when_no_headers(app: FastAPI) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/probe")
    assert response.status_code == 200
    body = response.json()
    assert body["locale"] == "en_US"
    assert body["message"] == "Invalid email or password"
    # Content-Language uses hyphenated tag for HTTP transport.
    assert response.headers.get("content-language") == "en-US"


@pytest.mark.asyncio
async def test_accept_language_negotiates_chinese(app: FastAPI) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/probe", headers={"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5"}
        )
    body = response.json()
    assert body["locale"] == "zh_CN"
    assert body["message"] == "邮箱或密码错误"
    assert response.headers.get("content-language") == "zh-CN"


@pytest.mark.asyncio
async def test_x_language_override_beats_accept_language(app: FastAPI) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/probe",
            headers={"Accept-Language": "en-US,en;q=0.9", "X-Language": "zh-CN"},
        )
    body = response.json()
    assert body["locale"] == "zh_CN"
    assert body["message"] == "邮箱或密码错误"


@pytest.mark.asyncio
async def test_query_param_override(app: FastAPI) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/probe?lang=zh-CN", headers={"Accept-Language": "en-US"}
        )
    body = response.json()
    assert body["locale"] == "zh_CN"


@pytest.mark.asyncio
async def test_unknown_locale_falls_back_to_default(app: FastAPI) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/probe", headers={"Accept-Language": "fr-FR,de;q=0.8"})
    body = response.json()
    assert body["locale"] == "en_US"
