from django.conf import settings
from django.contrib import admin
from django.http import FileResponse, Http404, HttpResponse
from django.urls import include, path

# The page is served by the same server as the API, so it calls the API on its own origin whatever host or tunnel it is opened from.
API_BOOTSTRAP = '<script>window.NEXA_API = location.origin + "/api";</script>'


def frontend(request):
    page = settings.FRONTEND_DIR / "Nexa.html"
    if not page.is_file():
        raise Http404("frontend/Nexa.html was not found")
    html = page.read_text(encoding="utf-8").replace("<head>", "<head>\n" + API_BOOTSTRAP, 1)
    response = HttpResponse(html, content_type="text/html; charset=utf-8")
    response["Cache-Control"] = "no-cache"
    return response


def frontend_asset(request, name):
    assets = {"Nexa.css": "text/css; charset=utf-8", "Nexa.js": "application/javascript; charset=utf-8"}
    if name not in assets:
        raise Http404
    asset = settings.FRONTEND_DIR / name
    if not asset.is_file():
        raise Http404
    response = FileResponse(asset.open("rb"), content_type=assets[name])
    response["Cache-Control"] = "no-cache"
    return response


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("api.urls")),
]

if settings.SERVE_FRONTEND:
    urlpatterns += [
        path("", frontend),
        path("Nexa.html", frontend),
        path("Nexa.css", frontend_asset, {"name": "Nexa.css"}),
        path("Nexa.js", frontend_asset, {"name": "Nexa.js"}),
    ]
