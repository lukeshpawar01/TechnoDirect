"""Test helper: sign in with email + password and return the JWT pair."""


def jwt_login(client, email, password):
    r = client.post("/api/auth/token/", {"email": email, "password": password}, format="json")
    assert r.status_code == 200, r.content
    return r.json()
