"""Template context for signed-in (registered) pages."""
from . import services
from .matchmaker import matchmaker


def registered(request):
    s = request.session
    if not s.get("registered"):
        return {"is_registered": False}
    uid = s["uid"]
    me = services.get_profile(uid) or {}
    ctx = {"is_registered": True, "me_uid": uid, "me": me, "online": matchmaker.online}
    if me.get("nickname"):
        ctx.update(services.nav_counts(uid))
    return ctx
