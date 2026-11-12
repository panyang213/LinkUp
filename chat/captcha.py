"""Cloudflare Turnstile verification (server side)."""
import json
import logging
import urllib.parse
import urllib.request

from django.conf import settings

logger = logging.getLogger(__name__)
VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
COOKIE = "linkup_human"          # signed cookie proving this browser passed the check
PASS_SECONDS = 60 * 60 * 24      # remembered for 24 hours


def enabled():
    return bool(settings.TURNSTILE_SITE_KEY and settings.TURNSTILE_SECRET_KEY)


def client_ip(request):
    return request.META.get("REMOTE_ADDR")


def _post(data):
    req = urllib.request.Request(VERIFY_URL, urllib.parse.urlencode(data).encode(), method="POST")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.load(resp)


def verify(token, ip=None):
    """True if the token is valid (or CAPTCHA is disabled). Fails closed on any error."""
    if not enabled():
        return True
    if not isinstance(token, str) or not token or len(token) > 2048:
        logger.warning("Turnstile: no token received from the browser")
        return False
    data = {"secret": settings.TURNSTILE_SECRET_KEY, "response": token}
    if ip:
        data["remoteip"] = ip
    try:
        result = _post(data)
    except Exception as exc:
        logger.warning("Turnstile: could not reach Cloudflare: %r", exc)
        return False
    if not result.get("success"):
        logger.warning("Turnstile: Cloudflare rejected the token: %s", result.get("error-codes"))
    return bool(result.get("success"))


def human_ok(request):
    """True if CAPTCHA is off, or this browser holds a valid, unexpired pass."""
    if not enabled():
        return True
    return request.get_signed_cookie(COOKIE, default=None, max_age=PASS_SECONDS) == "1"


def mark_human(response):
    response.set_signed_cookie(COOKIE, "1", max_age=PASS_SECONDS, httponly=True, samesite="Lax")