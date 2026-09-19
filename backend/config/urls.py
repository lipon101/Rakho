from django.conf import settings
from django.http import HttpResponse, HttpResponseRedirect
from django.templatetags.static import static
from django.urls import include, path
from django.utils import timezone
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView
from inventory.admin import admin_site
from inventory.landing import landing_page
from inventory.pay import pay_page
from inventory.static_pages import privacy_policy, terms_of_service
from inventory.views import AppView


def privacy(request):
    """Google Play requires a public privacy policy URL for the app listing."""
    return HttpResponse(privacy_policy(), content_type="text/html")


def terms(request):
    return HttpResponse(terms_of_service(), content_type="text/html")


def robots_txt(request):
    lines = [
        "User-agent: *",
        "Allow: /",
        f"Disallow: /{settings.ADMIN_URL}",
        "Disallow: /api/",
        # Per-signup checkout pages carry a private token and are noindex; keep
        # crawlers off them as well so the tokens never end up in an index.
        "Disallow: /pay/",
        "",
        # Same canonical origin the page declares, so robots and canonical can
        # never disagree about which host is the real one.
        f"Sitemap: {settings.SITE_URL}/sitemap.xml",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")


def sitemap_xml(request):
    base = settings.SITE_URL
    entries = [
        (f"{base}/", "1.0", "weekly"),
        (f"{base}/app/", "0.9", "weekly"),
        (f"{base}/privacy/", "0.3", "yearly"),
        (f"{base}/terms/", "0.3", "yearly"),
    ]
    today = timezone.localdate().isoformat()
    xml = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for loc, priority, freq in entries:
        xml.append(
            f"  <url><loc>{loc}</loc><lastmod>{today}</lastmod>"
            f"<changefreq>{freq}</changefreq><priority>{priority}</priority></url>"
        )
    xml.append("</urlset>")
    return HttpResponse("\n".join(xml), content_type="application/xml")


def favicon(request):
    """Serves the brand mark for pages that declare no icon of their own.

    Browsers ask for /favicon.ico on every origin, and the console, the
    checkout page, the legal pages and the SPA all used to answer 404 — so the
    tab and the Android home-screen shortcut fell back to a blank icon.
    """
    return HttpResponseRedirect(static("brand/favicon-32.png"))


def landing(request):
    return HttpResponse(landing_page(), content_type="text/html")


def pay(request, token):
    """Public Pro checkout page for a signup's private token."""
    return HttpResponse(pay_page(token), content_type="text/html")


urlpatterns = [
    path("", landing, name="landing"),
    path("favicon.ico", favicon, name="favicon"),
    path("robots.txt", robots_txt, name="robots"),
    path("sitemap.xml", sitemap_xml, name="sitemap"),
    path("privacy/", privacy, name="privacy"),
    path("terms/", terms, name="terms"),
    path("pay/<str:token>/", pay, name="pay"),
    path("app/", AppView.as_view(), name="app"),
    path("app/<path:route>", AppView.as_view(), name="app-route"),
    path(settings.ADMIN_URL, admin_site.urls),
    path("api/v1/", include("inventory.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]
