'''auth: the gate, the session cookie, and the things that keep a stolen file useless.

every test runs against a throwaway ~/.fab (the fab_home fixture behind `client`), so the
real users.json is never touched.'''

import json
import time

import pytest

from hub.back import auth
from hub.back.auth import COOKIE_NAME
from hub.test.conftest import PASSWORD, register

USER = "tester"


# ---- the gate ----

def test_pages_redirect_and_api_calls_401_without_a_session(client):
    r = client.get("/", headers={"accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert client.get("/thoughtgraph/boards").status_code == 401
    assert client.get("/auth/me").status_code == 401


@pytest.mark.parametrize("path", ["/login", "/TechnoParadisal.css", "/hub.css", "/orbital.png"])
def test_the_login_page_and_its_assets_are_public(client, path):
    assert client.get(path).status_code == 200


def test_a_session_opens_every_door(client, user):
    assert client.get("/auth/me").json()["user"] == user
    assert client.get("/", headers={"accept": "text/html"}).status_code == 200
    assert client.get("/thoughtgraph/boards").status_code == 200


# ---- register / login / logout ----

def test_register_then_login_round_trip(client):
    register(client, USER)
    assert client.post("/auth/register", json={"username": USER, "password": "x"}).status_code == 400
    assert client.post("/auth/login", json={"username": USER, "password": "wrong"}).status_code == 401

    assert client.post("/auth/logout").status_code == 200
    assert client.get("/auth/me").status_code == 401

    assert client.post("/auth/login", json={"username": USER, "password": PASSWORD}).status_code == 200
    assert client.get("/auth/me").json()["user"] == USER


def test_the_cookie_is_the_whole_session(client, user):
    token = client.cookies[COOKIE_NAME]
    client.cookies.clear()
    assert client.get("/auth/me").status_code == 401
    client.cookies.set(COOKIE_NAME, token)
    assert client.get("/auth/me").json()["user"] == user


@pytest.mark.parametrize("username", ["", "   ", "has space", "sl/ash", "dot.dot", "x" * 33])
def test_usernames_are_restricted_to_what_can_be_a_directory_name(client, username):
    # the username becomes users/{name}/ on disk, so the charset is the allowlist
    r = client.post("/auth/register", json={"username": username, "password": PASSWORD})
    assert r.status_code == 400, r.text


def test_an_empty_password_is_refused(client):
    assert client.post("/auth/register", json={"username": USER, "password": ""}).status_code == 400


# ---- what a stolen file would be worth ----

def test_passwords_are_salted_scrypt_never_plaintext(client, user):
    stored = json.loads(auth.USERS_PATH.read_text())[user]
    assert PASSWORD not in json.dumps(stored)
    assert len(bytes.fromhex(stored["salt"])) == 16
    assert stored["hash"] == auth._hash_password(PASSWORD, bytes.fromhex(stored["salt"]))


def test_session_tokens_are_hashed_at_rest(client, user):
    # without this a stolen sessions.json could be replayed straight back as a cookie
    token = client.cookies[COOKIE_NAME]
    sessions = json.loads(auth.SESSIONS_PATH.read_text())
    assert token not in sessions and token not in json.dumps(sessions)
    assert auth._token_key(token) in sessions


def test_two_users_with_one_password_get_different_hashes(client):
    register(client, "one")
    register(client, "two")
    users = json.loads(auth.USERS_PATH.read_text())
    assert users["one"]["salt"] != users["two"]["salt"]
    assert users["one"]["hash"] != users["two"]["hash"]


def test_an_expired_session_is_rejected_and_pruned(client, user):
    token = client.cookies[COOKIE_NAME]
    sessions = json.loads(auth.SESSIONS_PATH.read_text())
    sessions[auth._token_key(token)]["expires"] = time.time() - 1
    auth.SESSIONS_PATH.write_text(json.dumps(sessions))
    assert auth.user_for_token(token) is None
    assert json.loads(auth.SESSIONS_PATH.read_text()) == {}, "expired sessions are swept on use"


def test_logout_deletes_the_session_server_side(client, user):
    token = client.cookies[COOKIE_NAME]
    client.post("/auth/logout")
    assert json.loads(auth.SESSIONS_PATH.read_text()) == {}
    assert auth.user_for_token(token) is None, "the token is dead even if the cookie is replayed"


# ---- rate limiting ----

def test_repeated_bad_logins_are_throttled(client):
    # registering already spends one attempt on this same (username, ip) key, so count the
    # codes rather than assuming exactly where the cutoff lands
    register(client, USER)
    codes = [client.post("/auth/login", json={"username": USER, "password": "wrong"}).status_code
             for _ in range(auth.MAX_ATTEMPTS + 1)]
    assert codes[0] == 401 and codes[-1] == 429
    # the throttle is keyed per user, so it must not lock out everyone else on this ip
    register(client, "bystander")


def test_mass_registration_from_one_ip_is_throttled(client):
    # every register costs a scrypt hash and a disk write, so the cap is per-ip too
    for i in range(auth.MAX_ATTEMPTS):
        client.post("/auth/register", json={"username": "", "password": PASSWORD})
    r = client.post("/auth/register", json={"username": "fresh_name", "password": PASSWORD})
    assert r.status_code == 429


def test_the_attempt_window_expires(client):
    register(client, USER)
    for _ in range(auth.MAX_ATTEMPTS):
        client.post("/auth/login", json={"username": USER, "password": "wrong"})
    assert client.post("/auth/login", json={"username": USER, "password": PASSWORD}).status_code == 429
    # rewind the recorded attempts past the window — patching the clock means patching the
    # global time module, which every other caller in the process shares
    for key, stamps in auth._attempts.items():
        auth._attempts[key] = [t - auth.ATTEMPT_WINDOW - 1 for t in stamps]
    assert client.post("/auth/login", json={"username": USER, "password": PASSWORD}).status_code == 200


# ---- cookie flags ----

def test_the_cookie_is_httponly_and_only_secure_over_https(client):
    r = client.post("/auth/register", json={"username": USER, "password": PASSWORD})
    cookie = r.headers["set-cookie"]
    assert "httponly" in cookie.lower() and "samesite=lax" in cookie.lower()
    assert "secure" not in cookie.lower(), "http://localhost logins must keep working"
    client.post("/auth/logout")
    r = client.post("/auth/login", json={"username": USER, "password": PASSWORD},
                    headers={"x-forwarded-proto": "https"})
    assert "secure" in r.headers["set-cookie"].lower(), "behind a TLS proxy the cookie must be Secure"
