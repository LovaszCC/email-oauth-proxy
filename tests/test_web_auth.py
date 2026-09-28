async def test_login_page(client):
    response = await client.get("/login")
    assert response.status_code == 200
    assert 'name="password"' in response.text


async def test_login_wrong_password(client):
    response = await client.post("/login", data={"username": "admin", "password": "nope"})
    assert response.status_code == 401
    assert "Invalid username or password" in response.text


async def test_login_wrong_user(client):
    response = await client.post("/login", data={"username": "root", "password": "pw"})
    assert response.status_code == 401


async def test_login_success_and_redirect_when_logged_in(admin):
    response = await admin.get("/login")
    assert response.status_code == 303
    assert response.headers["location"] == "/"


async def test_logout(admin):
    response = await admin.post("/logout")
    assert response.status_code == 303
    assert response.headers["location"] == "/login"
    response = await admin.get("/login")
    assert response.status_code == 200
