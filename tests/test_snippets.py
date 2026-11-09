import uuid

from tests.conftest import signup


async def test_snippet_crud_roundtrip(auth, fake_groq):
    c, user, _ = auth
    r = await c.post("/api/snippets", json={"title": "  Hello  ", "code": "print('hi')\n", "language": "python", "description": "  demo  ", "isPublic": "true"})
    assert r.status_code == 201
    s = r.json()["snippet"]
    assert s["title"] == "Hello" and s["code"] == "print('hi')" and s["language"] == "python"
    assert s["description"] == "demo" and s["isPublic"] is True and s["userId"] == user["id"]
    assert fake_groq.calls == []  # language given -> no detection call

    listing = (await c.get("/api/snippets")).json()["snippets"]
    assert [x["id"] for x in listing] == [s["id"]]
    assert (await c.get(f"/api/snippets/{s['id']}")).json()["snippet"]["title"] == "Hello"

    r = await c.put(f"/api/snippets/{s['id']}", json={"title": "Renamed", "isPublic": False, "description": ""})
    u = r.json()["snippet"]
    assert u["title"] == "Renamed" and u["isPublic"] is False and u["description"] == "" and u["code"] == "print('hi')"
    r = await c.put(f"/api/snippets/{s['id']}", json={"code": "x = 1"})
    assert r.json()["snippet"]["code"] == "x = 1" and r.json()["snippet"]["title"] == "Renamed"  # untouched fields stay

    assert (await c.delete(f"/api/snippets/{s['id']}")).json() == {"success": True}
    assert (await c.get(f"/api/snippets/{s['id']}")).json() == {"error": "Snippet not found"}


async def test_language_auto_detection_and_fallback(auth, fake_groq):
    c, _, _ = auth
    fake_groq.reply = "  Python  "
    r = await c.post("/api/snippets", json={"title": "t", "code": "def f(): pass"})
    assert r.json()["snippet"]["language"] == "Python"
    r = await c.post("/api/snippets", json={"title": "t", "code": "x", "language": "auto"})
    assert r.json()["snippet"]["language"] == "Python"
    fake_groq.reply = RuntimeError("groq down")
    r = await c.post("/api/snippets", json={"title": "t", "code": "x"})
    assert r.status_code == 201 and r.json()["snippet"]["language"] == "plaintext"  # detection is best-effort
    assert len(fake_groq.calls[0]["messages"][0]["content"]) > 0


async def test_snippet_validation_messages(auth):
    c, _, _ = auth
    cases = [
        ({"title": "", "code": "x"}, "Title must be 1–100 characters"),
        ({"title": "t" * 101, "code": "x"}, "Title must be 1–100 characters"),
        ({"title": "t", "code": ""}, "Code must be 1–50000 characters"),
        ({"title": "t", "code": "x", "language": "l" * 51}, "Language name too long"),
        ({"title": "t", "code": "x", "description": "d" * 501}, "Description max 500 characters"),
        ({"title": "t", "code": "x", "isPublic": "maybe"}, "isPublic must be true or false"),
    ]
    for payload, message in cases:
        r = await c.post("/api/snippets", json=payload)
        assert r.status_code == 400 and r.json() == {"error": message}, payload
    r = await c.put(f"/api/snippets/{uuid.uuid4()}", json={"code": ""})
    assert r.json() == {"error": "Code must be 1–50000 characters"}
    r = await c.put(f"/api/snippets/{uuid.uuid4()}", json={"title": ""})
    assert r.json() == {"error": "Invalid value"}
    assert (await c.get("/api/snippets/not-a-uuid")).json() == {"error": "snippetId must be a valid UUID"}


async def test_snippets_are_private_to_their_owner(client, fake_groq):
    await signup(client, "owner@example.com")
    sid = (await client.post("/api/snippets", json={"title": "t", "code": "x", "language": "js"})).json()["snippet"]["id"]
    client.cookies.clear()
    await signup(client, "other@example.com")
    assert (await client.get("/api/snippets")).json() == {"snippets": []}
    assert (await client.get(f"/api/snippets/{sid}")).status_code == 404
    assert (await client.put(f"/api/snippets/{sid}", json={"title": "hijack"})).status_code == 404
    assert (await client.delete(f"/api/snippets/{sid}")).status_code == 404
    client.cookies.clear()
    r = await client.get("/api/snippets")
    assert r.status_code == 401


async def test_unknown_route_and_health(client):
    assert (await client.get("/health")).json() == {"status": "ok", "service": "CodeBox API"}
    r = await client.get("/api/nope")
    assert r.status_code == 404 and r.json() == {"status": "error", "message": "Route not found"}
    r = await client.put("/api/login")  # wrong method on a real path -> same 404 as Express
    assert r.status_code == 404
    r = await client.get("/health")
    assert r.headers["x-content-type-options"] == "nosniff" and "x-frame-options" in r.headers
