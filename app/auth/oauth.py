from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.config import Config

from app.db.session import get_db
from app.services.oauth_service import OAuthService
from app.core.oauth_config import oauth
from app.core.config import settings

router = APIRouter(prefix="/auth", tags=["OAuth"])


# ─── Google ───────────────────────────────────────────────────────────────────

@router.get("/google/login")
async def google_login(request: Request):
    """Redirect user to Google's OAuth consent screen."""
    return await oauth.google.authorize_redirect(request, settings.GOOGLE_REDIRECT_URI)


@router.get("/google/callback")
async def google_callback(request: Request, db: AsyncSession = Depends(get_db)):
    """Handle Google OAuth callback and issue JWT tokens."""
    token = await oauth.google.authorize_access_token(request)
    access_token, refresh_token = await OAuthService.handle_google_callback(db, token)

    # Redirect to frontend with tokens in query string (or use cookies in production)
    return RedirectResponse(
        url=f"{settings.FRONTEND_URL}/oauth-success?access_token={access_token}&refresh_token={refresh_token}"
    )


# ─── GitHub ───────────────────────────────────────────────────────────────────

@router.get("/github/login")
async def github_login(request: Request):
    """Redirect user to GitHub's OAuth authorization page."""
    return await oauth.github.authorize_redirect(request, settings.GITHUB_REDIRECT_URI)


@router.get("/github/callback")
async def github_callback(request: Request, db: AsyncSession = Depends(get_db)):
    """Handle GitHub OAuth callback and issue JWT tokens."""
    token = await oauth.github.authorize_access_token(request)
    access_token, refresh_token = await OAuthService.handle_github_callback(db, token)

    return RedirectResponse(
        url=f"{settings.FRONTEND_URL}/oauth-success?access_token={access_token}&refresh_token={refresh_token}"
    )


# ─── Facebook ─────────────────────────────────────────────────────────────────

@router.get("/facebook/login")
async def facebook_login(request: Request):
    """Redirect user to Facebook's OAuth dialog."""
    return await oauth.facebook.authorize_redirect(request, settings.FACEBOOK_REDIRECT_URI)


@router.get("/facebook/callback")
async def facebook_callback(request: Request, db: AsyncSession = Depends(get_db)):
    """Handle Facebook OAuth callback and issue JWT tokens."""
    token = await oauth.facebook.authorize_access_token(request)
    access_token, refresh_token = await OAuthService.handle_facebook_callback(db, token)

    return RedirectResponse(
        url=f"{settings.FRONTEND_URL}/oauth-success?access_token={access_token}&refresh_token={refresh_token}"
    )


# ─── Apple ────────────────────────────────────────────────────────────────────

@router.get("/apple/login")
async def apple_login(request: Request):
    """Redirect user to Apple's Sign In page."""
    return await oauth.apple.authorize_redirect(request, settings.APPLE_REDIRECT_URI)


@router.post("/apple/callback")  # Apple uses POST for the callback
async def apple_callback(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Handle Apple Sign In callback.
    Apple sends: id_token, user (JSON string, first login only), code
    """
    form = await request.form()
    id_token = form.get("id_token")
    user_data_raw = form.get("user")

    if not id_token:
        raise HTTPException(status_code=400, detail="No id_token received from Apple")

    user_data = None
    if user_data_raw:
        import json
        try:
            user_data = json.loads(user_data_raw)
        except Exception:
            pass

    access_token, refresh_token = await OAuthService.handle_apple_callback(db, id_token, user_data)

    return RedirectResponse(
        url=f"{settings.FRONTEND_URL}/oauth-success?access_token={access_token}&refresh_token={refresh_token}"
    )
