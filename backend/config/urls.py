from django.contrib import admin
from django.http import HttpResponse
from django.urls import include, path
from django.utils import timezone
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView
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
        "Disallow: /admin/",
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
    return HttpResponse("""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Rakho — Pharmacy Inventory & Expiry Manager for Bangladesh</title>
<meta name="description" content="বাংলাদেশের ফার্মেসির জন্য তৈরি। ওষুধের মেয়াদ, স্টক আর বাকির খাতা এক অ্যাপে। Works offline, free to start — stock, expiry alerts, baki book and FEFO billing for pharmacies in Bangladesh.">
<meta name="keywords" content="pharmacy management Bangladesh, medicine expiry tracker, ফার্মেসি ম্যানেজমেন্ট, ওষুধের মেয়াদ, বাকির খাতা, POS pharmacy app, drug inventory app BD">
<link rel="canonical" href="https://rakho-api.onrender.com/">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Rakho">
<meta property="og:title" content="Rakho — Pharmacy Inventory & Expiry Manager">
<meta property="og:description" content="Expiry alerts before medicine expires. A baki book that never forgets. FEFO billing that protects profit. Built for Bangladeshi pharmacies, free to start.">
<meta property="og:url" content="https://rakho-api.onrender.com/">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="Rakho — Pharmacy Inventory & Expiry Manager">
<meta name="twitter:description" content="Expiry alerts, baki book and FEFO billing for Bangladeshi pharmacies. Free to start, works offline.">
<meta name="theme-color" content="#8B5E34">
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "SoftwareApplication",
  "name": "Rakho",
  "applicationCategory": "BusinessApplication",
  "operatingSystem": "Android",
  "description": "Pharmacy inventory, expiry tracking, baki (credit) book and FEFO point-of-sale for pharmacies in Bangladesh. Free to start, works offline.",
  "offers": { "@type": "Offer", "price": "0", "priceCurrency": "BDT" },
  "featureList": "Expiry alerts, Low stock alerts, Baki credit book, FEFO batch billing, Sales reports with CSV export, Works offline, Bangla & English"
}
</script>
<style>
  :root { --paper:#FBF9F4; --card:#FAF6F0; --variant:#EFE6DB; --ink:#2D2016;
          --taupe:#816C5A; --umber:#8B5E34; --deep:#4A2F17; }
  * { margin:0; padding:0; box-sizing:border-box; }
  body { font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
         background:var(--paper); color:var(--ink); line-height:1.65; }
  main { max-width:820px; margin:0 auto; padding:56px 22px 40px; }
  .kicker { display:inline-block; background:var(--variant); color:var(--deep);
            padding:5px 14px; border-radius:999px; font-size:.8rem; font-weight:600;
            letter-spacing:.02em; margin-bottom:18px; }
  h1 { font-family:Georgia,'Times New Roman',serif; font-size:2.5rem; line-height:1.15;
       color:var(--ink); margin-bottom:10px; }
  h1 .accent { color:var(--umber); }
  .sub { font-size:1.05rem; color:var(--taupe); max-width:620px; margin-bottom:30px; }
  h2 { font-family:Georgia,serif; font-size:1.35rem; margin:34px 0 12px; }
  .cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr));
           gap:14px; margin:16px 0 8px; }
  .card { background:var(--card); border:1px solid var(--variant); border-radius:16px;
          padding:20px; }
  .card h3 { font-size:1rem; margin-bottom:6px; color:var(--deep); }
  .card p { font-size:.9rem; color:var(--taupe); }
  .cta { display:flex; gap:12px; flex-wrap:wrap; margin-top:26px; }
  .btn { padding:13px 24px; border-radius:12px; text-decoration:none; font-weight:600;
         font-size:.95rem; transition:transform .15s; }
  .btn:hover { transform:translateY(-1px); }
  .btn-primary { background:var(--umber); color:#fff; }
  .btn-outline { border:1.5px solid var(--umber); color:var(--deep); }
  .bn { font-size:1rem; color:var(--taupe); margin-top:8px; }
  footer { max-width:820px; margin:0 auto; padding:26px 22px 46px; color:var(--taupe);
           font-size:.85rem; display:flex; gap:18px; flex-wrap:wrap; }
  footer a { color:var(--umber); }
  @media (max-width:520px) { h1{font-size:1.9rem;} }
</style>
</head>
<body>
<main>
  <span class="kicker">Built for pharmacies in Bangladesh</span>
  <h1>Never lose money to <span class="accent">expired medicine</span> again.</h1>
  <p class="sub">
    Rakho tracks every batch's expiry date, alerts you before medicine expires,
    keeps a baki book that never forgets, and bills with first-expired-first-out
    rotation — so old stock sells first and profit stays protected.
    Free to start. Works without internet.
  </p>
  <p class="sub bn">
    বাংলাদেশের ফার্মেসির জন্য তৈরি — ওষুধের মেয়াদ শেষ হওয়ার আগেই সতর্কতা,
    বাকির হিসাব আলাদা করে রাখা, আর অফলাইনেও চলে। একদম ফ্রি-তে শুরু।
  </p>

  <h2>What Rakho does for your shop</h2>
  <div class="cards">
    <div class="card">
      <h3>⏰ Expiry radar</h3>
      <p>Expired batches can never be sold by mistake, and you see what expires
      this month — with the taka value at risk — before it becomes a loss.</p>
    </div>
    <div class="card">
      <h3>🤝 Baki book</h3>
      <p>Who owes what, since when. Record a credit sale with the customer's
      name and settle it the moment money arrives. Nothing forgotten.</p>
    </div>
    <div class="card">
      <h3>🧾 Smart billing</h3>
      <p>FEFO rotation automatically sells the nearest-expiry batch first.
      Cash, bKash, Nagad, card and baki in one fast counter screen.</p>
    </div>
    <div class="card">
      <h3>📶 Works offline</h3>
      <p>Load-shedding or no network — sell and receive stock without internet.
      Everything syncs when the connection returns. Bangla & English.</p>
    </div>
  </div>

  <h2>Free, with a national medicine database</h2>
  <p class="sub" style="margin-bottom:6px;">
    Start free with manual entry and full offline features. Connect a Rakho API
    key to search ~14,000 Bangladesh medicines (brand, generic, strength,
    manufacturer) while adding stock — no typing, no spelling mistakes.
  </p>

  <div class="cta">
    <a class="btn btn-primary" href="/app/">Open the web app</a>
    <a class="btn btn-outline" href="/api/docs/">API docs</a>
  </div>
</main>
<footer>
  <span>Rakho © 2026 · Pharmacy inventory & expiry management</span>
  <a href="/privacy/">Privacy</a>
  <a href="/terms/">Terms</a>
  <a href="/api/v1/health/">Status</a>
</footer>
</body>
</html>""", content_type="text/html")


urlpatterns = [
    path("", landing, name="landing"),
    path("robots.txt", robots_txt, name="robots"),
    path("sitemap.xml", sitemap_xml, name="sitemap"),
    path("privacy/", privacy, name="privacy"),
    path("terms/", terms, name="terms"),
    path("app/", AppView.as_view(), name="app"),
    path("app/<path:route>", AppView.as_view(), name="app-route"),
    path("admin/", admin.site.urls),
    path("api/v1/", include("inventory.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]
