async def test_health_without_login(client):
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "imap_listening": True,
        "accounts_total": 0,
        "accounts_authorized": 0,
    }
