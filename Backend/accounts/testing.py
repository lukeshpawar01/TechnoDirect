"""Test helper: complete the two-step (password + emailed OTP) login and return the JWT pair."""
import re

from django.core import mail


def jwt_login(client, email, password):
    r = client.post("/api/auth/token/", {"email": email, "password": password}, format="json")
    assert r.status_code == 200, r.content
    body = r.json()
    if "access" in body:  # OTP disabled
        return body
    code = re.search(r"\b(\d{6})\b", mail.outbox[-1].body).group(1)
    r = client.post("/api/auth/otp/verify/", {"challenge_id": body["challenge_id"], "code": code}, format="json")
    assert r.status_code == 200, r.content
    return r.json()
