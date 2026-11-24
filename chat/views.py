import json
import uuid

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from . import captcha
from .content import ICEBREAKERS, MOODS, TOPICS, daily_question
from .forms import AnonymousEntryForm
from .matchmaker import matchmaker
from .models import Report


def landing(request, form=None):
    return render(request, "chat/landing.html", {
        "form": form or AnonymousEntryForm(),
        "open_modal": form is not None,
        "min_age": settings.MIN_AGE,
        "has_session": bool(request.session.get("anon_id")) and not request.session.get("registered"),
        "online": matchmaker.online,
        "firebase_web_config": settings.FIREBASE_WEB_CONFIG,
        "turnstile_site_key": settings.TURNSTILE_SITE_KEY if captcha.enabled() else "",
        "registered": bool(request.session.get("registered")),
        "human_gate": captcha.enabled() and not captcha.human_ok(request)
                      and not request.session.get("anon_id"),
    })


@require_POST
def verify_human(request):
    """Called once by the full-screen check; remembers the result in a signed cookie."""
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        data = {}
    token = data.get("token") if isinstance(data, dict) else None
    if not captcha.verify(token, captcha.client_ip(request)):
        return JsonResponse({"error": "Verification failed. Please try again."}, status=400)
    response = JsonResponse({"ok": True})
    captcha.mark_human(response)
    return response


@require_POST
def enter_anonymously(request):
    form = AnonymousEntryForm(request.POST)
    valid = form.is_valid()
    if not captcha.human_ok(request):
        form.add_error(None, "Please complete the human check first. Reload the page and try again.")
        valid = False
    if not valid:
        return landing(request, form)
    request.session.flush()
    request.session["anon_id"] = uuid.uuid4().hex
    request.session["nickname"] = form.cleaned_data["nickname"]
    return redirect("chat")


def chat(request):
    if not request.session.get("anon_id"):
        return redirect("landing")
    if not request.session.get("nickname"): 
        return redirect("dashboard")
    return render(request, "chat/chat.html", {
        "nickname": request.session["nickname"],
        "moods": MOODS,
        "daily_question": daily_question(),
        "report_reasons": Report.REASONS,
        "client_config": {"topics": TOPICS, "icebreakers": ICEBREAKERS,      # json_script turns this into JSON itself
                    "ice_servers": settings.WEBRTC_ICE_SERVERS},
        "online": matchmaker.online,
    })


@require_POST
def leave(request):
    request.session.flush()
    return redirect("landing")


def online_count(request):
    return JsonResponse({"count": matchmaker.online})