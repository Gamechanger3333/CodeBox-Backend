from app.config import get_settings


async def test_root_route_is_friendly_for_browsers_and_platform_probes(client):
    r = await client.get("/")
    assert r.status_code == 200 and r.json()["service"] == "CodeBox API"
    assert (await client.head("/")).status_code == 200  # Render sends HEAD / and GET / by default


async def test_frontend_url_accepts_trailing_slash_and_several_origins(client, monkeypatch):
    """Vercel gives one production URL plus preview URLs; a trailing slash typed into Render must not break CORS."""
    from app.main import create_app
    import httpx

    monkeypatch.setattr(get_settings(), "frontend_url", "https://codebox-frontend.vercel.app/ , https://preview.vercel.app")
    assert get_settings().frontend_origins == ["https://codebox-frontend.vercel.app", "https://preview.vercel.app"]
    transport = httpx.ASGITransport(app=create_app(), raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="https://api.test") as c:
        for origin in ("https://codebox-frontend.vercel.app", "https://preview.vercel.app"):
            r = await c.options("/api/login", headers={"Origin": origin, "Access-Control-Request-Method": "POST"})
            assert r.headers["access-control-allow-origin"] == origin
            assert r.headers["access-control-allow-credentials"] == "true"
        bad = await c.options("/api/login", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
        assert "access-control-allow-origin" not in bad.headers
