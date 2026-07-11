"""OAuth-провайдер линковки: авторизация, обмен кода, ротация refresh."""

from __future__ import annotations

import sqlite3
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient

from tests.test_api import ClientAndApp, bootstrap_admin, container_of

BROKER = "https://social.yandex.net/broker/redirect"

AUTHORIZE_QUERY = {
    "response_type": "code",
    "client_id": "ya-client",
    "redirect_uri": BROKER,
    "state": "st-123",
}


def authorize(client: TestClient, password: str = "password123") -> str:
    """Проходит форму логина, возвращает одноразовый код из редиректа."""
    response = client.post(
        "/oauth/authorize",
        data={
            "username": "admin",
            "password": password,
            "client_id": "ya-client",
            "redirect_uri": BROKER,
            "state": "st-123",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302, response.text
    location = response.headers["location"]
    assert location.startswith(BROKER)
    query = parse_qs(urlsplit(location).query)
    assert query["state"] == ["st-123"]
    return query["code"][0]


def exchange(client: TestClient, code: str) -> dict[str, str]:
    response = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": BROKER,
            "client_id": "ya-client",
            "client_secret": "ya-secret",
        },
    )
    assert response.status_code == 200, response.text
    body: dict[str, str] = response.json()
    return body


def link_account(client: TestClient) -> dict[str, str]:
    """Полная линковка: код → пара токенов (переиспользуется в /v1.0-тестах)."""
    return exchange(client, authorize(client))


def test_authorize_form_validation(client_app: ClientAndApp) -> None:
    client, app = client_app
    bootstrap_admin(client, app)

    ok = client.get("/oauth/authorize", params=AUTHORIZE_QUERY)
    assert ok.status_code == 200
    assert "Разрешить Яндексу" in ok.text
    assert 'value="st-123"' in ok.text  # state доезжает hidden-полем

    for bad in (
        {**AUTHORIZE_QUERY, "client_id": "чужой"},
        {**AUTHORIZE_QUERY, "redirect_uri": "https://evil.example/cb"},
        {**AUTHORIZE_QUERY, "response_type": "token"},
    ):
        response = client.get("/oauth/authorize", params=bad)
        assert response.status_code == 400
        assert response.json() == {"error": "invalid_request"}


def test_authorize_wrong_password_rerenders_form(client_app: ClientAndApp) -> None:
    client, app = client_app
    bootstrap_admin(client, app)
    response = client.post(
        "/oauth/authorize",
        data={
            "username": "admin",
            "password": "мимо",
            "client_id": "ya-client",
            "redirect_uri": BROKER,
            "state": "st-123",
        },
        follow_redirects=False,
    )
    assert response.status_code == 200  # снова форма, без редиректа
    assert "неверный логин или пароль" in response.text


def test_code_exchange_and_single_use(client_app: ClientAndApp) -> None:
    client, app = client_app
    bootstrap_admin(client, app)
    code = authorize(client)

    tokens = exchange(client, code)
    assert tokens["token_type"] == "bearer"
    assert tokens["expires_in"] == 3600
    assert tokens["access_token"] != tokens["refresh_token"]

    # код одноразовый
    replay = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": BROKER,
            "client_id": "ya-client",
            "client_secret": "ya-secret",
        },
    )
    assert replay.status_code == 400
    assert replay.json() == {"error": "invalid_grant"}


def test_token_endpoint_rejects_bad_client_and_grant(
    client_app: ClientAndApp,
) -> None:
    client, app = client_app
    bootstrap_admin(client, app)
    code = authorize(client)

    bad_secret = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": BROKER,
            "client_id": "ya-client",
            "client_secret": "не тот",
        },
    )
    assert bad_secret.status_code == 401
    assert bad_secret.json() == {"error": "invalid_client"}

    wrong_redirect = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "https://evil.example/cb",
            "client_id": "ya-client",
            "client_secret": "ya-secret",
        },
    )
    assert wrong_redirect.status_code == 400

    unsupported = client.post(
        "/oauth/token",
        data={
            "grant_type": "password",
            "client_id": "ya-client",
            "client_secret": "ya-secret",
        },
    )
    assert unsupported.status_code == 400
    assert unsupported.json() == {"error": "unsupported_grant_type"}


def test_expired_code_rejected(client_app: ClientAndApp) -> None:
    client, app = client_app
    bootstrap_admin(client, app)
    code = authorize(client)

    # состариваем код прямой записью в файл БД (WAL допускает второго писателя)
    db_path = container_of(app).settings.data_dir / "easy_breezy.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("UPDATE oauth_codes SET expires_at = 1")

    response = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": BROKER,
            "client_id": "ya-client",
            "client_secret": "ya-secret",
        },
    )
    assert response.status_code == 400
    assert response.json() == {"error": "invalid_grant"}


def test_refresh_rotation(client_app: ClientAndApp) -> None:
    client, app = client_app
    bootstrap_admin(client, app)
    first = link_account(client)

    rotated_response = client.post(
        "/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": first["refresh_token"],
            "client_id": "ya-client",
            "client_secret": "ya-secret",
        },
    )
    assert rotated_response.status_code == 200
    rotated = rotated_response.json()
    assert rotated["access_token"] != first["access_token"]

    # старая пара погашена целиком: и refresh, и access
    stale = client.post(
        "/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": first["refresh_token"],
            "client_id": "ya-client",
            "client_secret": "ya-secret",
        },
    )
    assert stale.status_code == 400
    old_access = client.get(
        "/v1.0/user/devices",
        headers={"Authorization": f"Bearer {first['access_token']}"},
    )
    assert old_access.status_code == 401
    new_access = client.get(
        "/v1.0/user/devices",
        headers={"Authorization": f"Bearer {rotated['access_token']}"},
    )
    assert new_access.status_code == 200
