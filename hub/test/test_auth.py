'''auth flow tests: register/login/me/logout + the gate. run from repo root: venv/bin/python hub/test/test_auth.py'''

import json
import shutil

from fastapi.testclient import TestClient

from fab.config import FAB_DIR
from hub.back.app import app
from hub.back.auth import COOKIE_NAME

TEST_USER = "test_auth_user"


def cleanup():
    for p in (FAB_DIR / "auth" / "users.json", FAB_DIR / "auth" / "sessions.json"):
        if p.exists():
            data = json.loads(p.read_text())
            if "users" in p.name:
                data.pop(TEST_USER, None)
            else:
                data = {k: v for k, v in data.items() if v.get("user") != TEST_USER}
            p.write_text(json.dumps(data))
    shutil.rmtree(FAB_DIR / "users" / TEST_USER, ignore_errors=True)


def main():
    cleanup()
    with TestClient(app) as client:
        # gate: no cookie -> html page loads redirect to /login, api calls 401
        r = client.get("/", headers={"accept": "text/html"}, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/login", r.status_code
        assert client.get("/thoughtgraph/boards").status_code == 401
        # the login page itself is public
        assert client.get("/login").status_code == 200

        # register, then we're in
        r = client.post("/auth/register", json={"username": TEST_USER, "password": "pw123"})
        assert r.status_code == 200 and r.json()["user"] == TEST_USER, r.text
        token = client.cookies.get(COOKIE_NAME)
        assert token
        assert client.get("/auth/me").json()["user"] == TEST_USER
        assert client.get("/", headers={"accept": "text/html"}).status_code == 200

        # duplicate register rejected, bad login rejected
        assert client.post("/auth/register", json={"username": TEST_USER, "password": "x"}).status_code == 400
        assert client.post("/auth/login", json={"username": TEST_USER, "password": "wrong"}).status_code == 401

        # logout kills the session, login restores it
        assert client.post("/auth/logout").status_code == 200
        assert client.get("/auth/me").status_code == 401
        r = client.post("/auth/login", json={"username": TEST_USER, "password": "pw123"})
        assert r.status_code == 200, r.text
        assert client.get("/auth/me").json()["user"] == TEST_USER

        # the session token survives a relogin: cookie set fresh, /auth/me works
        new_token = client.cookies.get(COOKIE_NAME)
        client.cookies.clear()
        assert client.get("/auth/me").status_code == 401
        client.cookies.set(COOKIE_NAME, new_token)
        assert client.get("/auth/me").json()["user"] == TEST_USER

    cleanup()
    print("test_auth OK")


if __name__ == "__main__":
    main()
