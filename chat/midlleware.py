from django.http import HttpResponseRedirect


class LocalhostRedirectMiddleware:
    """Development helper: Firebase and Cloudflare only allow 'localhost', not '127.0.0.1'."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.get_host().split(":")[0] == "127.0.0.1":
            return HttpResponseRedirect(request.build_absolute_uri().replace("127.0.0.1", "localhost", 1))
        return self.get_response(request)