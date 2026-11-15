"""Pages and JSON API for signed-in (registered) users. Anonymous users are rejected."""
import functools
import json
import time
from collections import defaultdict, deque

from django.conf import settings
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from . import captcha, firebase_auth, media, presence, services
from .content import daily_question
from .forms import ProfileForm
from .models import Report
from .store import get_store


# ---------- helpers ----------
def registered_only(view):
    """HTML pages: send anonymous visitors back to the landing page."""
    @functools.wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.session.get("registered"):
            return redirect("landing")
        return view(request, *args, **kwargs)
    return wrapper


def api_registered(view):
    """JSON endpoints: 401 for anonymous users, 403 until the profile is complete."""
    @functools.wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.session.get("registered"):
            return JsonResponse({"error": "Sign in with Google to use this feature."}, status=401)
        if not request.session.get("nickname"):
            return JsonResponse({"error": "Complete your profile first."}, status=403)
        return view(request, *args, **kwargs)
    return wrapper


def body(request):
    try:
        data = json.loads(request.body or b"{}")
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


_hits = defaultdict(deque)


def throttled(uid, key, limit, window=60):
    q = _hits[(uid, key)]
    now = time.monotonic()
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= limit:
        return True
    q.append(now)
    return False


def uid_of(request):
    return request.session["uid"]


# ---------- login ----------
@require_POST
def google_login(request):
    data = body(request)
    if not captcha.human_ok(request):
        return JsonResponse({"error": "Please complete the human check first. Reload the page and try again."}, status=400)
    try:
        info = firebase_auth.verify_google_token(data.get("id_token", ""))
    except firebase_auth.AuthError as exc:
        return JsonResponse({"error": str(exc)}, status=401)
    uid, st = info["uid"], get_store()
    existing = st.user_get(uid) or {}
    if "created_at" not in existing:
        st.user_set(uid, {"created_at": services.now_ms()})
    st.user_set(uid, {"email": info["email"]})  # private; never returned by the API
    request.session.flush()
    request.session["registered"] = True
    request.session["uid"] = uid
    request.session["anon_id"] = f"u_{uid}"
    if existing.get("nickname"):
        request.session["nickname"] = existing["nickname"]
    request.session.set_expiry(settings.SESSION_COOKIE_AGE_REGISTERED)
    return JsonResponse({"redirect": "/dashboard/"})


# ---------- pages ----------
def _dashboard_ctx(request, form=None):
    uid = uid_of(request)
    me = services.get_profile(uid) or {}
    ctx = {"daily_question": daily_question(), "online_total": presence.count()}
    if me.get("nickname"):
        lists = services.friend_lists(uid)
        ctx.update(online_friends=[f for f in lists["friends"] if f["online"]],
                   friend_count=len(lists["friends"]), incoming=lists["incoming"],
                   conversations=services.list_conversations(
                          uid, friends={f["uid"] for f in lists["friends"]})[:5],
                   notifications=services.list_notifications(uid)[:6])
    else:
        ctx.update(needs_profile=True, form=form or ProfileForm(),
                   visibility_choices=services.VISIBILITY)
    if form is not None:
        ctx["form"] = form
    return ctx


@registered_only
def dashboard(request):
    return render(request, "chat/dashboard.html", _dashboard_ctx(request))


@registered_only
def friends_page(request):
    if not request.session.get("nickname"):
        return redirect("dashboard")
    return render(request, "chat/friends.html")


@registered_only
def messages_page(request):
    if not request.session.get("nickname"):
        return redirect("dashboard")
    uid, with_uid = uid_of(request), request.GET.get("with", "")
    active = None
    if with_uid:
        active = services.view_profile(uid, with_uid)
        if active and active["relationship"] != "friends" and not services.history(uid, with_uid):
            active = None
    return render(request, "chat/messages.html", {
        "conversations": services.list_conversations(uid), "active": active,
        "report_reasons": Report.REASONS, "with_uid": with_uid if active else ""})


@registered_only
def profile_page(request):
    if not request.session.get("nickname"):
        return redirect("dashboard")
    return render(request, "chat/profile.html", _profile_ctx(request))


def _profile_ctx(request, form=None):
    uid = uid_of(request)
    me = services.get_profile(uid)
    initial = {"nickname": me["nickname"], "age": me.get("age"), "gender": me.get("gender"),
               "bio": me.get("bio"), "interests": ", ".join(me.get("interests", [])),
               "visibility": me.get("visibility", "public")}
    return {"form": form or ProfileForm(initial=initial), "visibility_choices": services.VISIBILITY}


@registered_only
@require_POST
def profile_save(request):
    uid = uid_of(request)
    existing = services.get_profile(uid) or {}
    form = ProfileForm(request.POST, request.FILES)
    if not form.is_valid():
        if existing.get("nickname"):
            return render(request, "chat/profile.html", _profile_ctx(request, form))
        return render(request, "chat/dashboard.html", _dashboard_ctx(request, form))
    cd = form.cleaned_data
    data = {"nickname": cd["nickname"], "age": cd["age"], "gender": cd["gender"], "bio": cd["bio"],
            "interests": cd["interests"], "visibility": cd["visibility"],
            "photo_url": existing.get("photo_url", "")}
    if cd["photo"]:
        try:
            data["photo_url"] = media.save_avatar(uid, cd["photo"]["data"], cd["photo"]["content_type"])
        except Exception:
            form.add_error("photo", "Photo upload isn't available right now. Save without a photo or try later.")
            if existing.get("nickname"):
                return render(request, "chat/profile.html", _profile_ctx(request, form))
            return render(request, "chat/dashboard.html", _dashboard_ctx(request, form))
    elif cd["remove_photo"]:
        media.delete_avatar(uid)
        data["photo_url"] = ""
    services.save_profile(uid, data)
    request.session["nickname"] = data["nickname"]
    request.session["anon_id"] = f"u_{uid}"
    return redirect("profile" if existing.get("nickname") else "dashboard")


@registered_only
def user_profile(request, other):
    prof = services.view_profile(uid_of(request), other)
    if not prof:
        raise Http404
    return render(request, "chat/user_profile.html", {
        "p": prof, "report_reasons": Report.REASONS})

@registered_only
def media_file(request, path):
    """Serve an uploaded picture from the media/ folder, to signed-in users only."""
    target = media.resolve(path)
    if not target:
        raise Http404
    response = FileResponse(open(target, "rb"), content_type=media.content_type_of(target))
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, max-age=86400"   # file names are unique per upload
    return response

@registered_only
def avatar(request, uid):
    got = get_store().avatar_get(uid)
    if not got:
        raise Http404
    return HttpResponse(got[0], content_type=got[1])


# ---------- JSON API ----------
@api_registered
@require_GET
def api_search(request):
    return JsonResponse({"results": services.search_users(uid_of(request), request.GET.get("q", ""))})


@api_registered
@require_GET
def api_friends(request):
    return JsonResponse(services.friend_lists(uid_of(request)))


def _action(request, fn, *args):
    try:
        result = fn(uid_of(request), *args)
    except services.ServiceError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse({"ok": True, "result": result})


@api_registered
@require_POST
def api_friend_request(request):
    if throttled(uid_of(request), "freq", 10):
        return JsonResponse({"error": "Too many requests. Try again in a minute."}, status=429)
    return _action(request, services.send_request, str(body(request).get("uid", "")))


@api_registered
@require_POST
def api_friend_respond(request):
    data = body(request)
    return _action(request, services.respond_request, str(data.get("request_id", "")), bool(data.get("accept")))


@api_registered
@require_POST
def api_friend_remove(request):
    return _action(request, services.remove_friend, str(body(request).get("uid", "")))


@api_registered
@require_POST
def api_block(request):
    return _action(request, services.block_user, str(body(request).get("uid", "")))


@api_registered
@require_GET
def api_history(request, other):
    uid = uid_of(request)
    if not services.view_profile(uid, other):
        return JsonResponse({"error": "Not found."}, status=404)
    return JsonResponse({"messages": services.history(uid, other), "me": uid})


@api_registered
@require_POST
def api_delete_conversation(request, other):
    services.delete_conversation(uid_of(request), other)
    return JsonResponse({"ok": True})


@api_registered
@require_POST
def api_report(request):
    data = body(request)
    reason, other = data.get("reason"), str(data.get("uid", ""))
    if reason not in dict(Report.REASONS) or not other:
        return JsonResponse({"error": "Choose a reason."}, status=400)
    if throttled(uid_of(request), "report", 5):
        return JsonResponse({"error": "Too many reports. Try again later."}, status=429)
    details = data.get("details")
    Report.objects.create(reporter_id=uid_of(request), reported_id=other, reason=reason,
                          details=details.strip()[:500] if isinstance(details, str) else "")
    return JsonResponse({"ok": True})


@api_registered
@require_GET
def api_notifications(request):
    return JsonResponse({"notifications": services.list_notifications(uid_of(request))})


@api_registered
@require_POST
def api_notifications_read(request):
    services.mark_notifications_read(uid_of(request))
    return JsonResponse({"ok": True})
