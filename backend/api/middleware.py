import re

LOCAL_ORIGIN = re.compile(r"https?://(localhost|127\.0\.0\.1|\[::1\])(:\d{1,5})?")


class AdminLocalOnlyMiddleware:
    """Hides /admin/ from requests that arrive through a tunnel or proxy.

    Cloudflare Tunnel adds forwarding headers to every request it relays, while a browser on this machine sends none.
    """

    FORWARDED = ("Cf-Connecting-Ip", "X-Forwarded-For", "X-Forwarded-Host")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django.conf import settings
        from django.http import Http404

        if settings.ADMIN_LOCAL_ONLY and request.path.startswith("/admin") and any(h in request.headers for h in self.FORWARDED):
            raise Http404("Not found")
        return self.get_response(request)


class CorsMiddleware:
    """Minimal CORS for the token-authenticated JSON API (no cookies are used, so credentials are not allowed)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django.conf import settings
        from django.http import HttpResponse

        origin = request.headers.get("Origin")
        allowed = bool(origin) and (
            origin in settings.CORS_ALLOWED_ORIGINS
            or (settings.CORS_ALLOW_LOCAL_DEV and LOCAL_ORIGIN.fullmatch(origin) is not None)
        )
        if request.method == "OPTIONS" and request.headers.get("Access-Control-Request-Method"):
            response = HttpResponse(status=204)
        else:
            response = self.get_response(request)
        if allowed:
            response["Access-Control-Allow-Origin"] = origin
            response["Access-Control-Allow-Methods"] = "GET, POST, PATCH, DELETE, OPTIONS"
            response["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
            response["Access-Control-Expose-Headers"] = "X-Total-Count"
            response["Access-Control-Max-Age"] = "600"
            response["Vary"] = "Origin"
        return response
