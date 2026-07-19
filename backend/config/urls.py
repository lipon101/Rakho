from django.contrib import admin
from django.http import HttpResponse
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView
from inventory.views import AppView


def landing(request):
    return HttpResponse("""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Rakho API — Pharmacy Inventory</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
    color: #e2e8f0; min-height: 100vh; display: flex;
    align-items: center; justify-content: center; text-align: center;
  }
  .card {
    background: rgba(30, 41, 59, 0.8); border: 1px solid rgba(99, 102, 241, 0.2);
    border-radius: 16px; padding: 48px; max-width: 520px;
    backdrop-filter: blur(12px); box-shadow: 0 25px 50px rgba(0,0,0,0.4);
  }
  h1 { font-size: 2.5rem; font-weight: 700; margin-bottom: 8px; }
  h1 span { color: #818cf8; }
  .badge {
    display: inline-block; background: rgba(99, 102, 241, 0.15);
    color: #a5b4fc; padding: 4px 14px; border-radius: 20px;
    font-size: 0.8rem; font-weight: 500; margin-bottom: 24px;
  }
  .links { display: flex; flex-direction: column; gap: 10px; margin-top: 28px; }
  .links a {
    display: flex; align-items: center; justify-content: center; gap: 8px;
    padding: 12px 20px; border-radius: 10px;
    text-decoration: none; font-weight: 500; font-size: 0.95rem;
    transition: all 0.2s;
  }
  .btn-docs {
    background: #6366f1; color: #fff;
  }
  .btn-docs:hover { background: #4f46e5; transform: translateY(-1px); }
  .btn-outline {
    border: 1px solid rgba(99, 102, 241, 0.3); color: #c7d2fe;
  }
  .btn-outline:hover { background: rgba(99, 102, 241, 0.1); }
  .footer { margin-top: 32px; font-size: 0.75rem; color: #64748b; }
</style>
</head>
<body>
<div class="card">
  <h1>Rakho <span>API</span></h1>
  <div class="badge">v1.0.0 &bull; Operational</div>
  <p style="color:#94a3b8;line-height:1.6;">
    REST API for pharmacy inventory management — medicines, batches, purchases, sales, FEFO stock rotation, and expiry alerts.
  </p>
  <div class="links">
    <a href="/app/" class="btn-docs">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></svg>
      Open App
    </a>
    <a href="/api/docs/" class="btn-docs">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
      Swagger Docs
    </a>
    <a href="/api/v1/" class="btn-outline">API Root</a>
    <a href="/api/v1/health/" class="btn-outline">Health Check</a>
  </div>
  <div class="footer">Rakho &copy; 2026</div>
</div>
</body>
</html>""", content_type="text/html")


urlpatterns = [
    path("", landing, name="landing"),
    path("app/", AppView.as_view(), name="app"),
    path("admin/", admin.site.urls),
    path("api/v1/", include("inventory.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]
