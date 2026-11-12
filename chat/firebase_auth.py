"""Verify Firebase ID tokens (Google sign-in) on the server."""
from django.conf import settings


class AuthError(Exception):
    pass


def init_app():
    import firebase_admin
    from firebase_admin import credentials
    if not firebase_admin._apps:
        options = {}
        if settings.FIREBASE_STORAGE_BUCKET:
            options["storageBucket"] = settings.FIREBASE_STORAGE_BUCKET
        firebase_admin.initialize_app(credentials.Certificate(settings.FIREBASE_CREDENTIALS), options)


def verify_google_token(id_token):
    """Return {'uid', 'email'} for a valid Google-provider Firebase ID token."""
    if not settings.FIREBASE_CREDENTIALS:
        raise AuthError("Firebase is not configured on the server.")
    init_app()
    from firebase_admin import auth
    try:
        decoded = auth.verify_id_token(id_token, clock_skew_seconds=60)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("Firebase token check failed: %r", exc)
        detail = f" ({exc})" if settings.DEBUG else ""
        raise AuthError("Invalid or expired sign-in." + detail) from exc
    if decoded.get("firebase", {}).get("sign_in_provider") != "google.com":
        raise AuthError("Only Google sign-in is supported.")
    if not decoded.get("email_verified"):
        raise AuthError("Your Google email isn't verified.")
    return {"uid": decoded["uid"], "email": decoded.get("email", "")}
