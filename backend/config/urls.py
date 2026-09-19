from django.contrib import admin
from django.conf import settings
from django.http import HttpResponse
from django.urls import include, path
from django.utils import timezone
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView
from inventory.landing import landing_page
from inventory.pay import pay_page
from inventory.static_pages import privacy_policy, terms_of_service
from inventory.views import AppView

# Brand the owner console — no default "Django administration" labels.
admin.site.site_header = "Rakho Console"
admin.site.site_title = "Rakho"
admin.site.index_title = "Storefront & pharmacy management"


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
        "",
        f"Sitemap: https://rakho-api.onrender.com/sitemap.xml",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")


def sitemap_xml(request):
    entries = [
        ("https://rakho-api.onrender.com/", "1.0", "weekly"),
        ("https://rakho-api.onrender.com/app/", "0.9", "weekly"),
        ("https://rakho-api.onrender.com/privacy/", "0.3", "yearly"),
        ("https://rakho-api.onrender.com/terms/", "0.3", "yearly"),
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


def landing(request):
    return HttpResponse(landing_page(), content_type="text/html")


def pay(request, token):
    """Public Pro checkout page for a signup's private token."""
    return HttpResponse(pay_page(token), content_type="text/html")


urlpatterns = [
    path("", landing, name="landing"),
    path("robots.txt", robots_txt, name="robots"),
    path("sitemap.xml", sitemap_xml, name="sitemap"),
    path("privacy/", privacy, name="privacy"),
    path("terms/", terms, name="terms"),
    path("pay/<str:token>/", pay, name="pay"),
    path("app/", AppView.as_view(), name="app"),
    path("app/<path:route>", AppView.as_view(), name="app-route"),
    path(settings.ADMIN_URL, admin.site.urls),
    path("api/v1/", include("inventory.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]
