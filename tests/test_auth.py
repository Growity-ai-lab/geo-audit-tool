"""Auth flow tests: protection, login/JWT, admin-only invites.

These use the unauthenticated `auth_client` (real get_current_user), unlike the
other suites which use the auth-overridden `client`.
"""

from api import auth as auth_mod


def _login(client, email: str, password: str) -> str:
    resp = client.post("/auth/login", data={"username": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_password_hash_roundtrips():
    h = auth_mod.hash_password("süper-gizli-parola")
    assert h != "süper-gizli-parola"
    assert auth_mod.verify_password("süper-gizli-parola", h) is True
    assert auth_mod.verify_password("yanlış", h) is False


def test_protected_endpoints_require_auth(auth_client):
    assert auth_client.post("/audits", json={"url": "example.com"}).status_code == 401
    assert auth_client.get("/audits").status_code == 401
    assert auth_client.get("/clients").status_code == 401
    assert auth_client.post("/clients", json={"name": "X"}).status_code == 401


def test_login_and_run_audit(auth_client, make_user):
    make_user("admin@test.local", "password123", role="admin")
    token = _login(auth_client, "admin@test.local", "password123")

    me = auth_client.get("/auth/me", headers=_bearer(token)).json()
    assert me["email"] == "admin@test.local"
    assert me["role"] == "admin"

    resp = auth_client.post(
        "/audits", json={"url": "example.com"}, headers=_bearer(token)
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "done"
    assert body["reachable"] is True
    assert body["user_id"] == me["id"]


def test_login_rejects_bad_credentials(auth_client, make_user):
    make_user("user@test.local", "password123")
    assert (
        auth_client.post(
            "/auth/login",
            data={"username": "user@test.local", "password": "wrong"},
        ).status_code
        == 401
    )
    assert (
        auth_client.post(
            "/auth/login",
            data={"username": "ghost@test.local", "password": "password123"},
        ).status_code
        == 401
    )


def test_invalid_token_is_rejected(auth_client):
    resp = auth_client.get("/audits", headers=_bearer("not-a-real-token"))
    assert resp.status_code == 401


def test_admin_can_invite_member(auth_client, make_user):
    make_user("admin@test.local", "password123", role="admin")
    token = _login(auth_client, "admin@test.local", "password123")

    created = auth_client.post(
        "/auth/users",
        json={"email": "new@test.local", "password": "password123", "role": "member"},
        headers=_bearer(token),
    )
    assert created.status_code == 201
    assert created.json()["email"] == "new@test.local"

    # The invited member can now log in.
    member_token = _login(auth_client, "new@test.local", "password123")
    assert auth_client.get("/auth/me", headers=_bearer(member_token)).json()[
        "role"
    ] == "member"


def test_member_cannot_invite(auth_client, make_user):
    make_user("member@test.local", "password123", role="member")
    token = _login(auth_client, "member@test.local", "password123")
    resp = auth_client.post(
        "/auth/users",
        json={"email": "x@test.local", "password": "password123"},
        headers=_bearer(token),
    )
    assert resp.status_code == 403


def test_invite_rejects_duplicate_email(auth_client, make_user):
    make_user("admin@test.local", "password123", role="admin")
    token = _login(auth_client, "admin@test.local", "password123")
    payload = {"email": "dup@test.local", "password": "password123"}
    assert (
        auth_client.post("/auth/users", json=payload, headers=_bearer(token)).status_code
        == 201
    )
    assert (
        auth_client.post("/auth/users", json=payload, headers=_bearer(token)).status_code
        == 409
    )


def test_artifacts_remain_public(auth_client, make_user):
    # Artifacts are intentionally unauthenticated (uuid path = capability),
    # so browser <a href> downloads work without an Authorization header.
    make_user("admin@test.local", "password123", role="admin")
    token = _login(auth_client, "admin@test.local", "password123")
    audit = auth_client.post(
        "/audits", json={"url": "example.com"}, headers=_bearer(token)
    ).json()

    # No auth header on the artifact request:
    pdf = auth_client.get(audit["pdf_url"])
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
