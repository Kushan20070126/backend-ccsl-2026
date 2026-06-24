from authlib.integrations.starlette_client import OAuth
from app.core.config import settings

oauth = OAuth()

# ─── Google ───────────────────────────────────────────────────────────────────
oauth.register(
    name="google",
    client_id=settings.GOOGLE_CLIENT_ID,
    client_secret=settings.GOOGLE_CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
    redirect_uri=settings.GOOGLE_REDIRECT_URI,
)

# ─── GitHub ───────────────────────────────────────────────────────────────────
oauth.register(
    name="github",
    client_id=settings.GITHUB_CLIENT_ID,
    client_secret=settings.GITHUB_CLIENT_SECRET,
    access_token_url="https://github.com/login/oauth/access_token",
    authorize_url="https://github.com/login/oauth/authorize",
    api_base_url="https://api.github.com/",
    client_kwargs={"scope": "user:email"},
    redirect_uri=settings.GITHUB_REDIRECT_URI,
)

# ─── Facebook ─────────────────────────────────────────────────────────────────
oauth.register(
    name="facebook",
    client_id=settings.FACEBOOK_CLIENT_ID,
    client_secret=settings.FACEBOOK_CLIENT_SECRET,
    access_token_url="https://graph.facebook.com/oauth/access_token",
    authorize_url="https://www.facebook.com/dialog/oauth",
    api_base_url="https://graph.facebook.com/",
    client_kwargs={"scope": "email public_profile"},
    redirect_uri=settings.FACEBOOK_REDIRECT_URI,
)

# ─── Apple ────────────────────────────────────────────────────────────────────
# Apple uses Sign In with Apple (SIWA) with a private key
# The client_secret for Apple is a JWT signed with your private key
oauth.register(
    name="apple",
    client_id=settings.APPLE_CLIENT_ID,
    # Apple client_secret is generated dynamically (see oauth_service.py)
    server_metadata_url="https://appleid.apple.com/.well-known/openid-configuration",
    client_kwargs={"scope": "name email", "response_mode": "form_post"},
    redirect_uri=settings.APPLE_REDIRECT_URI,
)
