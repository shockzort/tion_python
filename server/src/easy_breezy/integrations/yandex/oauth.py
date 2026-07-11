"""OAuth2-провайдер линковки аккаунта (план §6).

Минимальный сервер авторизации на один клиент (Яндекс): страница логина —
автономный HTML (открывается в webview приложения Яндекса, SPA не годится),
код одноразовый (TTL 10 мин), в БД — только sha256-хэши кодов и токенов.
"""

from __future__ import annotations

import html
import secrets
import time

import structlog
from fastapi import APIRouter, Form, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel

from easy_breezy.api.deps import ContainerDep
from easy_breezy.auth import AuthError, ThrottledError, hash_token
from easy_breezy.container import AppContainer
from easy_breezy.storage.repos.oauth import OAuthRepo

log = structlog.get_logger(__name__)

router = APIRouter(tags=["oauth"])

CODE_TTL_SECONDS = 600
ACCESS_TTL_SECONDS = 3600
REFRESH_TTL_SECONDS = 365 * 86400

_PAGE = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Easy Breezy — доступ для Яндекса</title>
<style>
  body {{ margin: 0; min-height: 100dvh; display: flex; align-items: center;
         justify-content: center; background: #0f172a; color: #e2e8f0;
         font: 16px/1.4 system-ui, sans-serif; }}
  form {{ width: min(92vw, 22rem); background: #1e293b; border-radius: 16px;
          padding: 24px; display: flex; flex-direction: column; gap: 12px; }}
  h1 {{ font-size: 1.15rem; margin: 0; }}
  p {{ margin: 0; font-size: .85rem; color: #94a3b8; }}
  input {{ padding: 10px 12px; border-radius: 10px; border: 1px solid #334155;
           background: #0f172a; color: inherit; font: inherit; }}
  button {{ padding: 10px; border: 0; border-radius: 10px; background: #0284c7;
            color: #fff; font: inherit; cursor: pointer; }}
  .error {{ color: #f87171; font-size: .85rem; margin: 0; }}
</style>
</head>
<body>
<form method="post" action="/oauth/authorize">
  <h1>Разрешить Яндексу управлять бризерами?</h1>
  <p>Войдите учётной записью Easy Breezy, чтобы связать аккаунты.</p>
  {error}
  <input name="username" placeholder="Логин" autocomplete="username" required>
  <input name="password" type="password" placeholder="Пароль"
         autocomplete="current-password" required>
  <input type="hidden" name="client_id" value="{client_id}">
  <input type="hidden" name="redirect_uri" value="{redirect_uri}">
  <input type="hidden" name="state" value="{state}">
  <button type="submit">Войти и разрешить</button>
</form>
</body>
</html>"""


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = ACCESS_TTL_SECONDS


def _client_valid(container: AppContainer, client_id: str) -> bool:
    expected = container.settings.yandex_client_id
    return expected is not None and secrets.compare_digest(
        client_id.encode(), expected.encode()
    )


def _redirect_valid(container: AppContainer, redirect_uri: str) -> bool:
    # точное совпадение с брокером Яндекса — никаких подстрок и поддоменов
    return redirect_uri == container.settings.yandex_redirect_uri


def _login_page(
    client_id: str, redirect_uri: str, state: str, error: str | None = None
) -> HTMLResponse:
    return HTMLResponse(
        _PAGE.format(
            client_id=html.escape(client_id, quote=True),
            redirect_uri=html.escape(redirect_uri, quote=True),
            state=html.escape(state, quote=True),
            error=f'<p class="error">{html.escape(error)}</p>' if error else "",
        )
    )


@router.get("/oauth/authorize")
async def authorize_form(
    container: ContainerDep,
    response_type: str = Query(default=""),
    client_id: str = Query(default=""),
    redirect_uri: str = Query(default=""),
    state: str = Query(default=""),
) -> Response:
    """Страница логина линковки; невалидный клиент получает 400, не редирект."""
    if (
        response_type != "code"
        or not _client_valid(container, client_id)
        or not _redirect_valid(container, redirect_uri)
    ):
        return JSONResponse({"error": "invalid_request"}, status_code=400)
    return _login_page(client_id, redirect_uri, state)


@router.post("/oauth/authorize")
async def authorize_submit(
    container: ContainerDep,
    username: str = Form(default=""),
    password: str = Form(default=""),
    client_id: str = Form(default=""),
    redirect_uri: str = Form(default=""),
    state: str = Form(default=""),
) -> Response:
    if not _client_valid(container, client_id) or not _redirect_valid(
        container, redirect_uri
    ):
        return JSONResponse({"error": "invalid_request"}, status_code=400)
    try:
        user = await container.auth.verify_credentials(username, password)
    except (AuthError, ThrottledError) as exc:
        return _login_page(client_id, redirect_uri, state, error=str(exc))

    code = secrets.token_urlsafe(32)
    now = int(time.time())
    async with container.db.session() as session:
        repo = OAuthRepo(session)
        await repo.purge_expired(now=now)
        await repo.create_code(
            code_hash=hash_token(code),
            client_id=client_id,
            redirect_uri=redirect_uri,
            user_id=user.id,
            expires_at=now + CODE_TTL_SECONDS,
        )
    log.info("oauth_code_issued", username=username)
    separator = "&" if "?" in redirect_uri else "?"
    location = f"{redirect_uri}{separator}code={code}&state={state}"
    return RedirectResponse(location, status_code=302)


@router.post("/oauth/token")
async def token_endpoint(
    container: ContainerDep,
    grant_type: str = Form(default=""),
    code: str = Form(default=""),
    refresh_token: str = Form(default=""),
    redirect_uri: str = Form(default=""),
    client_id: str = Form(default=""),
    client_secret: str = Form(default=""),
) -> Response:
    """Обмен кода и ротация refresh-токена (form-urlencoded, креды в body)."""
    expected_secret = container.settings.yandex_client_secret
    if (
        not _client_valid(container, client_id)
        or expected_secret is None
        or not secrets.compare_digest(client_secret.encode(), expected_secret.encode())
    ):
        return JSONResponse({"error": "invalid_client"}, status_code=401)

    if grant_type == "authorization_code":
        return await _grant_by_code(container, code=code, redirect_uri=redirect_uri)
    if grant_type == "refresh_token":
        return await _grant_by_refresh(container, refresh_token=refresh_token)
    return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)


async def _grant_by_code(
    container: AppContainer, *, code: str, redirect_uri: str
) -> Response:
    now = int(time.time())
    async with container.db.session() as session:
        repo = OAuthRepo(session)
        stored = await repo.consume_code(hash_token(code), now=now)
        if stored is None or stored.redirect_uri != redirect_uri:
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        response = await _issue_tokens(repo, user_id=stored.user_id, now=now)
    log.info("oauth_tokens_issued", user_id=stored.user_id)
    return JSONResponse(response.model_dump())


async def _grant_by_refresh(container: AppContainer, *, refresh_token: str) -> Response:
    now = int(time.time())
    async with container.db.session() as session:
        repo = OAuthRepo(session)
        stored = await repo.get_valid_by_refresh(hash_token(refresh_token), now=now)
        if stored is None:
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        await repo.revoke(stored.id)  # ротация: старая пара гаснет целиком
        response = await _issue_tokens(repo, user_id=stored.user_id, now=now)
    log.info("oauth_tokens_rotated", user_id=stored.user_id)
    return JSONResponse(response.model_dump())


async def _issue_tokens(repo: OAuthRepo, *, user_id: int, now: int) -> TokenResponse:
    access = secrets.token_urlsafe(32)
    refresh = secrets.token_urlsafe(32)
    await repo.create_tokens(
        access_hash=hash_token(access),
        refresh_hash=hash_token(refresh),
        user_id=user_id,
        access_expires_at=now + ACCESS_TTL_SECONDS,
        refresh_expires_at=now + REFRESH_TTL_SECONDS,
    )
    return TokenResponse(access_token=access, refresh_token=refresh)
