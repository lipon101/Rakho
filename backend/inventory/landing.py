"""Public marketing landing page.

Self-contained HTML (no build step, no external JS) so a deploy can never
break it. The signup form posts to the public API and shows the issued key
inline — a visitor becomes a working pharmacy without any manual step.

Facts that a visitor can check are assembled from their real source rather
than typed into the copy: the Pro price comes from the setting the checkout
charges (``PRO_PRICE_BDT``), the catalogue size comes from the database, and
the FAQ answers are rendered into both the visible accordion and the
``FAQPage`` structured data from one list, so the page can never tell Google
something different from what a visitor reads.

The install section works the same way. It always renders, because the Android
app is the product and a page that never mentions it reads as if there were no
app. ``play_store_url()`` decides only what the visitor is offered: a real Play
button once ``PLAY_STORE_URL`` holds a listing (a test link counts — that is
often the only install path a pre-launch app has), and otherwise the free API
key, with no external link and no schema ``downloadUrl`` anywhere. A download
button that 404s costs more trust than one that is not there yet.
"""

import json
from html import escape

from django.conf import settings

from .pricing import pro_price_bdt  # noqa: F401  (re-exported for callers/tests)

_HEAD = """<!DOCTYPE html>
<html lang="bn">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Rakho — ফার্মেসি ম্যানেজমেন্ট অ্যাপ | Pharmacy Inventory, Expiry & Baki App for Bangladesh</title>
<meta name="description" content="বাংলাদেশের ফার্মেসির জন্য বানানো অ্যাপ: মেয়াদ শেষ হওয়ার আগেই সতর্কতা, FEFO বিলিং, ব্যাচ ধরে স্টক আর বাকির খাতা। অফলাইনে চলে, ফ্রি-তে শুরু। Pharmacy inventory, expiry alerts, baki book and FEFO billing that works offline.">
<meta name="robots" content="index,follow,max-image-preview:large,max-snippet:-1">
<link rel="canonical" href="https://rakho-api.onrender.com/">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Rakho">
<meta property="og:url" content="https://rakho-api.onrender.com/">
<meta property="og:locale" content="bn_BD">
<meta property="og:locale:alternate" content="en_US">
<meta property="og:title" content="Rakho — ফার্মেসি ম্যানেজমেন্ট অ্যাপ">
<meta property="og:description" content="মেয়াদোত্তীর্ণ ওষুধে আর টাকা হারাবেন না। মেয়াদ, স্টক, বিক্রি আর বাকির খাতা, সব এক জায়গায়; অফলাইনেও চলে।">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="Rakho — ফার্মেসি ম্যানেজমেন্ট অ্যাপ">
<meta name="twitter:description" content="মেয়াদোত্তীর্ণ ওষুধে আর টাকা হারাবেন না। মেয়াদ, স্টক, বিক্রি আর বাকির খাতা, সব এক জায়গায়।">
<meta name="twitter:image" content="https://rakho-api.onrender.com/static/brand/og.png">
<meta property="og:image" content="https://rakho-api.onrender.com/static/brand/og.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:type" content="image/png">
<meta property="og:image:alt" content="Rakho — ফার্মেসির মেয়াদ, স্টক, বিক্রি ও বাকির খাতা">
<meta name="theme-color" content="#0E9F6E">
<meta name="author" content="Rakho">
<link rel="icon" type="image/png" sizes="32x32" href="/static/brand/favicon-32.png">
<link rel="apple-touch-icon" href="/static/brand/apple-touch-icon.png">
<link rel="alternate" hreflang="bn-BD" href="https://rakho-api.onrender.com/">
<link rel="alternate" hreflang="x-default" href="https://rakho-api.onrender.com/">
<style>
  :root{
    --green:#0E9F6E; --green-deep:#0B6B4A; --green-ink:#075038;
    --ink:#101B15; --muted:#5E7268; --paper:#FBFAF7; --card:#ffffff;
    --line:#E7E2D5; --soft:#EDF6F1;
    --lift:0 22px 44px -26px rgba(11,32,22,.34);
  }
  *{margin:0;padding:0;box-sizing:border-box}
  /* Anchor links must not hide under the sticky nav; smooth scrolling is
     opt-out for anyone who has asked for reduced motion. */
  html{scroll-behavior:smooth;scroll-padding-top:84px}
  @media (prefers-reduced-motion:reduce){
    html{scroll-behavior:auto}
    .card, .btn-primary, .step, .qa, .play-badge{transition:none !important}
    .card:hover, .btn-primary:hover, .play-badge:hover{transform:none !important}
  }
  body{font-family:'Segoe UI',system-ui,-apple-system,Roboto,'Noto Sans Bengali',sans-serif;
       background:var(--paper);color:var(--ink);line-height:1.6;-webkit-font-smoothing:antialiased}
  .wrap{max-width:1080px;margin:0 auto;padding:0 22px}
  a{color:var(--green-deep);text-decoration:none}
  nav{position:sticky;top:0;background:rgba(251,250,246,.9);backdrop-filter:blur(10px);
      border-bottom:1px solid var(--line);z-index:20}
  nav .wrap{display:flex;align-items:center;justify-content:space-between;height:64px}
  .logo{display:flex;align-items:center;gap:10px;font-weight:800;font-size:1.25rem;color:var(--green-deep)}
  .logo .mark{width:34px;height:34px;border-radius:10px;background:linear-gradient(135deg,var(--green),var(--green-deep));
      display:flex;align-items:center;justify-content:center;color:#fff;font-size:18px}
  .btn{display:inline-block;padding:12px 22px;border-radius:12px;font-weight:700;font-size:.95rem;
       transition:transform .15s ease,box-shadow .15s ease;cursor:pointer;border:none}
  .btn-primary{background:var(--green);color:#fff;box-shadow:0 8px 20px -6px rgba(14,159,110,.5)}
  .btn-primary:hover{transform:translateY(-2px)}
  .btn-outline{border:1.5px solid var(--green);color:var(--green-deep);background:transparent}
  .btn-sm{padding:9px 16px;font-size:.85rem}
  .hero{padding:88px 0 64px;text-align:center;
        background:radial-gradient(115% 80% at 50% -10%,#E9F5EF 0%,rgba(251,250,247,0) 62%)}
  .badge{display:inline-flex;align-items:center;gap:8px;background:#fff;color:var(--green-ink);
         font-weight:700;font-size:.78rem;padding:7px 15px;border-radius:999px;margin-bottom:20px;
         border:1px solid #DCE9E2;box-shadow:0 6px 18px -12px rgba(11,32,22,.4)}
  /* Marks a card as a paid feature. The catalogue search is Pro-only on the
     server, so the card must not read as if it ships with the free plan. */
  .pro-tag{display:inline-block;background:var(--green);color:#fff;font-size:.62rem;font-weight:800;
           letter-spacing:.05em;text-transform:uppercase;padding:2px 7px;border-radius:999px;
           margin-right:6px;vertical-align:1px}
  h1{font-size:clamp(2.05rem,5.2vw,3.45rem);line-height:1.12;font-weight:800;letter-spacing:-.028em}
  h1 .accent{color:var(--green)}
  .hero p.sub{max-width:560px;margin:20px auto 0;font-size:1.1rem;color:var(--muted);line-height:1.55}
  .hero .cta{margin-top:30px;display:flex;gap:12px;justify-content:center;flex-wrap:wrap}
  .trust{margin-top:26px;display:flex;gap:10px;justify-content:center;flex-wrap:wrap;
         font-size:.82rem;color:var(--muted)}
  .trust span{background:#fff;border:1px solid var(--line);border-radius:999px;padding:6px 13px}
  section{padding:66px 0}
  .eyebrow{display:block;text-align:center;color:var(--green);font-weight:800;font-size:.7rem;
           letter-spacing:.2em;text-transform:uppercase;margin-bottom:10px}
  h2{font-size:clamp(1.45rem,3.1vw,2.1rem);font-weight:800;text-align:center;letter-spacing:-.02em}
  .lead{text-align:center;color:var(--muted);max-width:560px;margin:12px auto 0}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(232px,1fr));gap:18px;margin-top:40px}
  .card{background:linear-gradient(180deg,#fff 0%,#FDFCF8 100%);border:1px solid var(--line);
        border-radius:20px;padding:26px 24px;
        transition:transform .16s ease,box-shadow .16s ease,border-color .16s ease}
  .card:hover{transform:translateY(-4px);box-shadow:var(--lift);border-color:#DCE9E2}
  .card .ic{display:inline-grid;place-items:center;width:44px;height:44px;border-radius:13px;
            background:var(--soft);font-size:1.25rem}
  .card h3{margin:14px 0 7px;font-size:1.03rem;letter-spacing:-.01em}
  .card p{font-size:.9rem;color:var(--muted);line-height:1.55}
  .plans{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:20px;margin-top:38px}
  .plan{background:var(--card);border:1.5px solid var(--line);border-radius:20px;padding:28px;position:relative}
  .plan.pro{border-color:var(--green);box-shadow:0 20px 40px -18px rgba(14,159,110,.35)}
  .plan .tag{position:absolute;top:-12px;left:50%;transform:translateX(-50%);background:var(--green);
             color:#fff;font-size:.7rem;font-weight:800;padding:4px 12px;border-radius:999px;letter-spacing:.05em}
  .plan h3{font-size:1.1rem}
  .plan .price{font-size:2.1rem;font-weight:800;margin:10px 0 2px;color:var(--green-deep)}
  .plan .per{color:var(--muted);font-size:.85rem}
  .plan ul{list-style:none;margin:18px 0}
  .plan li{padding:7px 0;font-size:.92rem;display:flex;gap:9px;color:var(--ink)}
  .plan li::before{content:"\\2713";color:var(--green);font-weight:800}
  .signup{background:linear-gradient(160deg,#0B6B4A,#0E9F6E);border-radius:26px;color:#fff;
          padding:44px 30px;margin-top:10px}
  .signup h2{color:#fff}
  .signup .lead{color:#d9efe6}
  form{max-width:520px;margin:30px auto 0;display:grid;gap:12px}
  input{width:100%;padding:14px 16px;border-radius:12px;border:1.5px solid transparent;font-size:.98rem;
        background:rgba(255,255,255,.96);color:var(--ink)}
  input:focus{outline:none;border-color:#fff;box-shadow:0 0 0 4px rgba(255,255,255,.25)}
  form .btn-primary{background:#fff;color:var(--green-deep);font-size:1rem}
  .form-note{font-size:.8rem;color:#cfe9de;text-align:center}
  #result{display:none;margin-top:20px;background:#fff;color:var(--ink);border-radius:16px;padding:20px;text-align:left}
  #result .key{font-family:monospace;background:var(--soft);border:1px dashed var(--green);padding:12px;
               border-radius:10px;word-break:break-all;font-weight:700;color:var(--green-deep);margin:10px 0}
  /* Skip link + screen-reader-only form labels */
  .skip{position:absolute;left:-9999px;top:0;background:var(--card);color:var(--ink) !important;
        padding:12px 16px;border-radius:0 0 12px 0;font-weight:700;z-index:99}
  .skip:focus{left:0}
  .sr{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;
      clip:rect(0 0 0 0);white-space:nowrap;border:0}
  .navlinks{display:flex;gap:18px;font-weight:600;font-size:.92rem}
  .btn:focus-visible, .navlinks a:focus-visible, footer a:focus-visible,
  .qa summary:focus-visible{outline:2px solid var(--green-deep);outline-offset:3px;border-radius:8px}

  /* Install band. Rendered only when PLAY_STORE_URL is set, so the page never
     offers a download that leads nowhere. */
  .install{background:var(--card);border-top:1px solid var(--line);border-bottom:1px solid var(--line)}
  .install .wrap{display:flex;align-items:center;justify-content:space-between;gap:26px;flex-wrap:wrap}
  .install h2{text-align:left;margin:0 0 8px}
  .install p{color:var(--muted);max-width:520px;font-size:.96rem}
  .install-act{display:flex;flex-direction:column;align-items:flex-start;gap:10px}
  /* A Play badge built from type and one CSS triangle, so the band ships no
     bitmap and cannot render as a broken image before static files collect. */
  .play-badge{display:inline-flex;align-items:center;gap:12px;background:var(--ink);color:#fff;
              padding:11px 18px 11px 16px;border-radius:14px;box-shadow:var(--lift);
              transition:transform .15s ease,box-shadow .15s ease}
  .play-badge:hover{transform:translateY(-2px)}
  .play-badge .stack{display:flex;flex-direction:column;line-height:1.18}
  .play-badge .kicker{font-size:.6rem;letter-spacing:.16em;text-transform:uppercase;color:#A9C4B7}
  .play-badge .name{font-weight:800;font-size:1.02rem;letter-spacing:-.01em}
  .play-badge .tri{width:19px;height:21px;flex:none;
                   background:conic-gradient(from -50deg,#00C3FF,#8EF0A1 42%,#FFD250 72%,#FF6A5A);
                   clip-path:polygon(3% 0,100% 50%,3% 100%)}
  /* Pre-launch: the badge is shown, never linked. A button that 404s costs
     more trust than one that is visibly not ready yet. */
  .play-badge.soon{background:#28352E;box-shadow:none}
  /* No lift on hover: an inert badge must not invite a click it cannot honour. */
  .play-badge.soon:hover{transform:none}
  .play-badge.soon .kicker{color:#8CA79A}
  .soon-chip{background:#fff;color:#28352E;font-size:.64rem;font-weight:800;
             padding:4px 9px;border-radius:999px;margin-left:6px;white-space:nowrap}
  .install-link{font-weight:700;font-size:.88rem;color:var(--green-deep)}

  /* 3-step how it works */
  .steps{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:18px;margin-top:40px}
  .step{background:var(--card);border:1px solid var(--line);border-radius:20px;padding:26px 24px}
  .step .n{display:inline-grid;place-items:center;width:32px;height:32px;border-radius:10px;
           background:var(--soft);color:var(--green-ink);font-weight:800;font-size:.92rem}
  .step h3{margin:14px 0 6px;font-size:1.02rem}
  .step p{font-size:.9rem;color:var(--muted);line-height:1.55}

  /* FAQ: native details/summary so it works with JavaScript disabled */
  .faq{max-width:780px;margin:34px auto 0;display:grid;gap:10px}
  .qa{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 18px}
  .qa summary{font-weight:700;font-size:.98rem;cursor:pointer;list-style:none}
  .qa summary::-webkit-details-marker{display:none}
  .qa summary::after{content:"+";float:right;font-weight:800;color:var(--green)}
  .qa[open] summary::after{content:"\\2013"}
  .qa p{margin-top:10px;color:var(--muted);font-size:.92rem}

  /* Inline form error instead of a blocking alert() dialog */
  .form-error{display:none;font-size:.85rem;font-weight:600;color:#FFE7E2;background:#8C2415;
              border-radius:10px;padding:10px 12px;text-align:center;margin:0}
  .form-error.show{display:block}
  footer{border-top:1px solid var(--line);padding:34px 0;color:var(--muted);font-size:.85rem}
  footer .wrap{display:flex;justify-content:space-between;gap:14px;flex-wrap:wrap}
  @media(max-width:720px){.navlinks{display:none}}
  @media(max-width:560px){
    .hero{padding:56px 0 44px}
    section{padding:48px 0}
    .signup{padding:32px 20px}
    .install .wrap{justify-content:flex-start}
  }
</style>
<script type="application/ld+json">
{
  "@context":"https://schema.org",
  "@graph":[
    {
      "@type":"Organization",
      "@id":"https://rakho-api.onrender.com/#organization",
      "name":"Rakho",
      "url":"https://rakho-api.onrender.com/",
      "areaServed":{"@type":"Country","name":"Bangladesh"},
      "description":"ফার্মেসির মেয়াদ, স্টক, বিক্রি ও বাকির হিসাবের সফটওয়্যার।"
    },
    {
      "@type":"SoftwareApplication",
      "@id":"https://rakho-api.onrender.com/#software",
      "name":"Rakho",
      "url":"https://rakho-api.onrender.com/",
      "applicationCategory":"BusinessApplication",
      "applicationSubCategory":"Pharmacy management",
      "operatingSystem":"Android, Web",
      __DOWNLOAD_URL__"inLanguage":["bn-BD","en"],
      "publisher":{"@id":"https://rakho-api.onrender.com/#organization"},
      "description":"মেয়াদ শেষ হওয়ার আগেই সতর্কতা, FEFO বিলিং, স্টক ও বাকির খাতা, অফলাইনেও চলে।",
      "featureList":[
        "মেয়াদ রাডার: কোন ব্যাচের মেয়াদ আগে শেষ হবে, আগেই জানা যায়",
        "বাকির খাতা: কে কত বাকি নিয়েছে, তার পূর্ণ হিসাব",
        "দ্রুত বিলিং: ক্যাশ, বিকাশ, নগদ ও বাকি এক স্ক্রিনে",
        "অফলাইনে চলে, নেট ফিরলে নিজেই সিংক হয়",
        "লো স্টক অ্যালার্ট",
        "রিপোর্ট ও CSV এক্সপোর্ট",
        "মেয়াদোত্তীর্ণ ওষুধ রাইট-অফ"
      ],
      "offers":[
        {
          "@type":"Offer",
          "name":"ফ্রি",
          "price":0,
          "priceCurrency":"BDT",
          "description":"বিক্রি, স্টক, মেয়াদ ও বাকি — চিরকালের জন্য ফ্রি, ১টি ডিভাইস।"
        },
        {
          "@type":"Offer",
          "name":"Pro",
          "price":__PRO_PRICE__,
          "priceCurrency":"BDT",
          "description":"সব ডিভাইসে লাইভ সিংক, ক্লাউড ব্যাকআপ ও রিপোর্ট এক্সপোর্ট — মাসিক।"
        }
      ]
    },
    {
      "@type":"FAQPage",
      "@id":"https://rakho-api.onrender.com/#faq",
      "mainEntity":[
        {"@type":"Question","name":__FAQ_Q1__,"acceptedAnswer":{"@type":"Answer","text":__FAQ_A1__}},
        {"@type":"Question","name":__FAQ_Q2__,"acceptedAnswer":{"@type":"Answer","text":__FAQ_A2__}},
        {"@type":"Question","name":__FAQ_Q3__,"acceptedAnswer":{"@type":"Answer","text":__FAQ_A3__}},
        {"@type":"Question","name":__FAQ_Q4__,"acceptedAnswer":{"@type":"Answer","text":__FAQ_A4__}}
      ]
    }
  ]
}
</script>
</head>
"""

_BODY_HEAD = """<body>
<a class="skip" href="#get">সরাসরি ফ্রি কী নিতে যান</a>
<nav><div class="wrap">
  <div class="logo"><span class="mark" aria-hidden="true">✚</span>Rakho</div>
  <div class="navlinks">
    <a href="#features">ফিচার</a>
    <a href="#app">অ্যাপ</a>
    <a href="#pricing">দাম</a>
    <a href="#faq">প্রশ্ন</a>
  </div>
  <a class="btn btn-primary btn-sm" href="#get">ফ্রি শুরু করুন</a>
</div></nav>

<header class="hero"><div class="wrap">
  <span class="badge">🇧🇩 বাংলাদেশের ফার্মেসির জন্য</span>
  <h1>মেয়াদোত্তীর্ণ ওষুধে<br>আর <span class="accent">টাকা হারাবেন না</span></h1>
  <p class="sub">মেয়াদ, স্টক, বিল আর বাকির খাতা এক অ্যাপে। অফলাইনেও চলে,
  শুরু করতে টাকা লাগে না।</p>
  <div class="cta">
    <a class="btn btn-primary" href="#get">ফ্রি-তে শুরু করুন</a>
    <a class="btn btn-outline" href="#features">ফিচার দেখুন</a>
  </div>
  <div class="trust"><span>কার্ড লাগবে না</span><span>লোডশেডিং-এও চলে</span><span>বাংলা ও English</span></div>
</div></header>

<section id="features"><div class="wrap">
  <span class="eyebrow">ফিচার</span>
  <h2>দোকানের পুরো হিসাব, এক অ্যাপে</h2>
  <div class="grid">
    <div class="card"><div class="ic">⏰</div><h3>মেয়াদ রাডার</h3><p>কোন ব্যাচ আগে ফুরোবে, আগেই দেখা যায়। মেয়াদোত্তীর্ণ মাল বিক্রি হয় না।</p></div>
    <div class="card"><div class="ic">🤝</div><h3>বাকির খাতা</h3><p>কে কত বাকি, সব এক জায়গায়। টাকা এলেই এক ট্যাপে মিটে যায়।</p></div>
    <div class="card"><div class="ic">🧾</div><h3>দ্রুত বিলিং</h3><p>FEFO নিজেই আগের মেয়াদের ব্যাচ বেছে নেয়। ক্যাশ, বিকাশ, নগদ আর বাকি, সব এক স্ক্রিনেই।</p></div>
    <div class="card"><div class="ic">📶</div><h3>অফলাইনে চলে</h3><p>লোডশেডিং-এও বিক্রি থামে না। নেট ফিরলেই নিজে থেকে সিংক হয়।</p></div>
    __CATALOG_CARD__
    <div class="card"><div class="ic">📊</div><h3>রিপোর্ট</h3><p>দৈনিক বিক্রি, লাভ আর টপ ওষুধ, এক নজরে। CSV-তেও এক্সপোর্ট হয়।</p></div>
    <div class="card"><div class="ic">📉</div><h3>লো স্টক অ্যালার্ট</h3><p>শেলফ খালি হওয়ার আগেই সতর্কতা আসে, ক্রেতাকে ফেরাতে হয় না।</p></div>
    <div class="card"><div class="ic">🗑️</div><h3>নষ্ট ওষুধ রাইট-অফ</h3><p>নষ্ট বা মেয়াদোত্তীর্ণ মাল ট্যাপে বাদ, হিসাব পরিষ্কার থাকে।</p></div>
  </div>
</div></section>

__INSTALL_SECTION__

<section id="how"><div class="wrap">
  <span class="eyebrow">শুরু</span>
  <h2>এক মিনিটেই চালু</h2>
  <div class="steps">
    <div class="step"><span class="n" aria-hidden="true">১</span><h3>নাম দিন</h3><p>আপনার আর দোকানের নাম দিলেই ফ্রি API কী তৈরি।</p></div>
    <div class="step"><span class="n" aria-hidden="true">২</span><h3>অ্যাপে লগইন</h3><p>কী-টি বসিয়ে দিলেই দোকানের হিসাব চালু।</p></div>
    <div class="step"><span class="n" aria-hidden="true">৩</span><h3>বিক্রি শুরু</h3><p>ওষুধ যোগ করুন, FEFO নিজেই ব্যাচ গুছিয়ে দেবে।</p></div>
  </div>
</div></section>

<section id="pricing" style="background:var(--soft)"><div class="wrap">
  <span class="eyebrow">দাম</span>
  <h2>সহজ মূল্য</h2>
  <p class="lead">শুরুটা ফ্রি। দোকান বড় হলে Pro।</p>
  <div class="plans">
    <div class="plan">
      <h3>ফ্রি</h3>
      <div class="price">৳০</div><div class="per">চিরকালের জন্য</div>
      <ul>
        <li>বিক্রি, স্টক, মেয়াদ, বাকি</li>
        <li>অফলাইনে সম্পূর্ণ</li>
        <li>১টি ডিভাইস</li>
        <li>ওষুধ নিজে যোগ করুন</li>
      </ul>
      <a class="btn btn-outline" href="#get" style="width:100%;text-align:center">শুরু করুন</a>
    </div>
    <div class="plan pro">
      <span class="tag">সবচেয়ে জনপ্রিয়</span>
      <h3>Pro</h3>
      <div class="price">৳__PRO_PRICE_BN__</div><div class="per">প্রতি মাস</div>
      <ul>
        <li>ফ্রি-এর সবকিছু</li>
        <li>সব ডিভাইসে লাইভ সিংক</li>
        <li>ক্যাটালগ থেকে অটো এন্ট্রি</li>
        <li>ক্লাউড ব্যাকআপ</li>
        <li>রিপোর্ট এক্সপোর্ট (CSV/PDF)</li>
      </ul>
      <a class="btn btn-primary" href="#get" style="width:100%;text-align:center">Pro নিন</a>
    </div>
  </div>
</div></section>

<section id="faq"><div class="wrap">
  <span class="eyebrow">প্রশ্ন</span>
  <h2>সাধারণ প্রশ্ন</h2>
  __FAQ_HTML__
</div></section>
"""

_BODY_TAIL = """
<section id="get"><div class="wrap">
  <div class="signup">
    <h2>আজই ফ্রি শুরু করুন</h2>
    <p class="lead">নাম দুটো লিখুন, সাথে সাথে ফ্রি API কী তৈরি।</p>
    <form id="signupForm">
      <label class="sr" for="owner">আপনার নাম</label>
      <input type="text" id="owner" placeholder="আপনার নাম" maxlength="120" autocomplete="name" required>
      <label class="sr" for="pharmacy">ফার্মেসির নাম</label>
      <input type="text" id="pharmacy" placeholder="ফার্মেসির নাম" maxlength="180" autocomplete="organization" required>
      <label class="sr" for="whatsapp">হোয়াটসঅ্যাপ নম্বর (ঐচ্ছিক)</label>
      <input type="tel" id="whatsapp" placeholder="হোয়াটসঅ্যাপ নম্বর (ঐচ্ছিক)" maxlength="32" autocomplete="tel">
      <input type="text" id="website" tabindex="-1" autocomplete="off" style="position:absolute;left:-9999px;opacity:0" aria-hidden="true">
      <button type="submit" class="btn btn-primary" id="submitBtn">ফ্রি API কী পান</button>
      <p class="form-error" id="formError" role="alert"></p>
      <p class="form-note">কোনো পেমেন্ট লাগবে না। কী দিয়েই অ্যাপে লগইন করে কাজ শুরু করুন।</p>
    </form>
    <div id="result" role="status" aria-live="polite">
      <strong aria-hidden="true">🎉</strong> <strong>অভিনন্দন! আপনার API কী তৈরি হয়ে গেছে।</strong>
      <p style="margin-top:8px;font-size:.9rem;color:var(--muted)">এটি এখনই কপি করে নিরাপদে রাখুন — পরে আর দেখা যাবে না।</p>
      <div class="key" id="keyBox"></div>
      <button class="btn btn-primary btn-sm" id="copyBtn" style="background:var(--green);color:#fff">কী কপি করুন</button>
      <a class="btn btn-outline btn-sm" id="payLink" style="margin-left:8px">Pro আপগ্রেড</a>
    </div>
  </div>
</div></section>

<footer><div class="wrap">
  <span>Rakho © 2026 · ফার্মেসি ম্যানেজমেন্ট</span>
  <span>
    <a href="/privacy/">প্রাইভেসি</a> ·
    <a href="/terms/">শর্তাবলী</a> ·
    <a href="/api/docs/">API</a> ·
    <a href="/api/v1/health/">স্ট্যাটাস</a>
  </span>
</div></footer>

<script>
(function(){
  var form = document.getElementById('signupForm');
  var result = document.getElementById('result');
  var keyBox = document.getElementById('keyBox');
  var btn = document.getElementById('submitBtn');
  var copyBtn = document.getElementById('copyBtn');
  var payLink = document.getElementById('payLink');
  var key = '';
  var err = document.getElementById('formError');
  function showError(message){
    err.textContent = message; err.className = 'form-error show';
  }
  form.addEventListener('submit', function(e){
    e.preventDefault();
    err.textContent = ''; err.className = 'form-error';
    btn.disabled = true; btn.textContent = 'তৈরি হচ্ছে…';
    fetch('/api/v1/signup/', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        owner_name: document.getElementById('owner').value,
        pharmacy_name: document.getElementById('pharmacy').value,
        whatsapp: document.getElementById('whatsapp').value,
        website: document.getElementById('website').value
      })
    }).then(function(r){ return r.json().then(function(d){ return {ok:r.ok, d:d}; }); })
    .then(function(res){
      btn.disabled = false; btn.textContent = 'ফ্রি API কী পান';
      if(res.ok && res.d.api_key){
        key = res.d.api_key;
                keyBox.textContent = key;
        var upgradeUrl = res.d.upgrade_url || res.d.status_url;
        if(upgradeUrl){ payLink.href = upgradeUrl; }
        result.style.display = 'block';
        form.style.display = 'none';
        result.scrollIntoView({behavior:'smooth', block:'center'});
      } else {
        showError(res.d && res.d.error ? res.d.error : 'কিছু ভুল হয়েছে। আবার চেষ্টা করুন।');
      }
    }).catch(function(){
      btn.disabled = false; btn.textContent = 'ফ্রি API কী পান';
      showError('সার্ভারে পৌঁছানো যায়নি। ইন্টারনেট পরীক্ষা করে আবার চেষ্টা করুন।');
    });
  });
  copyBtn.addEventListener('click', function(){
    if(!key) return;
    if(navigator.clipboard){ navigator.clipboard.writeText(key).then(function(){
      copyBtn.textContent = '✓ কপি হয়েছে';
      setTimeout(function(){ copyBtn.textContent = 'কী কপি করুন'; }, 2000);
    }); } else { prompt('কপি করুন:', key); }
  });
})();
</script>
</body>
</html>"""


def catalog_card(count):
    """Feature card for the medicine catalogue.

    The count is never invented: the page previously advertised
    "১৪,০০০+ ওষুধের তালিকা" while the catalogue in production was empty, so the
    card promised a search that returned nothing. It now states the real
    catalogue size when there is one, and otherwise describes manual entry,
    which is what actually works on a fresh install.
    """
    icon = '<div class="ic" aria-hidden="true">💊</div>'
    if count > 0:
        body = (f'<span class="pro-tag">Pro</span> প্ল্যানে '
                f"<strong>{count:,}</strong>টি ওষুধ। "
                "নামের কয়েক অক্ষরেই সঠিকটা আসে।")
    else:
        body = ("নিজের ওষুধ নিজে যোগ করুন। একবার লিখলেই "
                "প্রতিটি বিক্রিতে কাজে লাগে।")
    return f'<div class="card">{icon}<h3>ওষুধের তালিকা</h3><p>{body}</p></div>'


def _catalog_count():
    """Live catalogue size. The marketing page must never 500 because the
    database is unreachable, so any failure simply falls back to 0."""
    try:
        from .models import CatalogMedicine
        return CatalogMedicine.objects.count()
    except Exception:  # noqa: BLE001 - a landing page must always render
        return 0


_BENGALI_DIGITS = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")


def bengali_digits(number):
    """ASCII digits → Bengali, so the Bangla copy reads naturally."""
    return str(number).translate(_BENGALI_DIGITS)


def faq_items(price_bn):
    """The one source of truth for the FAQ.

    Rendered into both the visible accordion and the FAQPage structured data,
    so the page cannot say one thing to a visitor and another to Google —
    which is a structured-data violation that costs rich results.
    """
    return [
        (
            "Rakho ব্যবহার করতে টাকা লাগে?",
            "না। ফ্রি প্ল্যানে বিক্রি, স্টক, মেয়াদ আর বাকি চিরকাল ফ্রি; কার্ড "
            "লাগে না। Pro ৳" + price_bn + "/মাসে সব ডিভাইসে সিংক, ব্যাকআপ আর "
            "রিপোর্ট এক্সপোর্ট যোগ হয়।",
        ),
        (
            "ইন্টারনেট না থাকলে কি চলবে?",
            "হ্যাঁ। লোডশেডিং বা নেট ছাড়াই বিক্রি ও স্টক চলে, নেট ফিরলে নিজেই "
            "সিংক হয়।",
        ),
        (
            "শুরু করতে কী লাগবে?",
            "শুধু আপনার নাম আর দোকানের নাম; সাথে সাথেই ফ্রি API কী পাবেন।",
        ),
        (
            "ডেটা কি নিরাপদ থাকবে?",
            "হ্যাঁ। হিসাব আপনার নিজের অ্যাকাউন্টে থাকে, API কী দিয়েই সুরক্ষিত। "
            "কী হারালে কনসোল থেকে নতুন নিতে পারেন, পুরোনোটা বাতিল হয়ে যায়।",
        ),
    ]


def faq_html(items):
    """Visible accordion. Native <details> so it works without JavaScript."""
    rows = "".join(
        f'<details class="qa"><summary>{question}</summary><p>{answer}</p></details>'
        for question, answer in items
    )
    return f'<div class="faq">{rows}</div>'


#: The URL shapes Google Play serves to installers. A published app is
#: ``/store/apps/details``; an unreleased one is reachable only through
#: ``/apps/testing`` (closed test) or ``/apps/internaltest``, and that tester
#: link is often the only way a shop can install the app before launch, so
#: refusing those shapes would hide a working install path.
PLAY_URL_PREFIXES = (
    "https://play.google.com/store/apps/",
    "https://play.google.com/apps/testing/",
    "https://play.google.com/apps/internaltest/",
)


def play_store_url():
    """The configured Play link, or ``""`` when there is nothing to link to.

    A download button is the easiest thing on a page to get wrong: a mistyped
    package id or a draft listing is a 404 on the one tap that was supposed to
    install the product. So only the real Play shapes are accepted, a value
    carrying whitespace is refused rather than silently truncated into a
    broken href, and anything else means "no install path yet".
    """
    url = str(getattr(settings, "PLAY_STORE_URL", "") or "").strip()
    if len(url) > 400 or any(character.isspace() for character in url):
        return ""
    if not url.startswith(PLAY_URL_PREFIXES):
        return ""
    return url


def install_section():
    """The install band. The Play badge is its subject; the key is the fallback.

    A shopkeeper who lands here should see "get the app" first, not "get an API
    key" — the app is the thing they will use every day. So the badge is the
    primary element in both states, and only its honesty changes: with a Play
    link configured it is the button, and before the listing is published it is
    drawn inert and labelled শীঘ্রই আসছে rather than pointing at a 404. The free
    key stays as the one action that works today, in the smaller type.
    """
    url = play_store_url()
    label = (
        '<span class="stack"><span class="kicker">Get it on</span>'
        '<span class="name">Google Play</span></span>'
    )
    triangle = '<span class="tri" aria-hidden="true"></span>'
    if url:
        badge = (
            f'<a class="play-badge" href="{escape(url, quote=True)}" '
            'target="_blank" rel="noopener">' + triangle + label + "</a>"
        )
        key_line = (
            '<a class="install-link" href="#get">'
            "অ্যাপে লগইন করতে ফ্রি API কী নিন →</a>"
        )
    else:
        badge = (
            '<span class="play-badge soon">' + triangle + label +
            '<span class="soon-chip">শীঘ্রই আসছে</span></span>'
        )
        key_line = (
            '<a class="install-link" href="#get">'
            "লগইনের ফ্রি API কী নিন →</a>"
        )
    return (
        '<section id="app" class="install"><div class="wrap"><div>'
        "<h2>দোকানটা এবার ফোনে নিন</h2>"
        "<p>Rakho-র অ্যান্ড্রয়েড অ্যাপেই বিক্রি, স্টক আর বাকির হিসাব, "
        "হাতের ফোনে।</p>"
        '</div><div class="install-act">'
        + badge
        + key_line
        + "</div></div></section>"
    )


def download_url_property():
    """The ``downloadUrl`` line for the JSON-LD block, or ``""``.

    The property is emitted whole — indent and trailing comma included —
    because the block is assembled by string replacement: returning half of it
    would leave invalid JSON and silently disable every rich result on the
    page.
    """
    url = play_store_url()
    if not url:
        return ""
    return ('"downloadUrl": ' + json.dumps(url, ensure_ascii=False)
            + ",\r\n      ")


def landing_page():
    price = pro_price_bdt()
    items = faq_items(bengali_digits(price))
    html = _HEAD + _BODY_HEAD + _BODY_TAIL

    # Structured data is assembled here rather than hand-written, so a value
    # that contains a quote or a backslash can never produce invalid JSON that
    # silently disables every rich result on the page.
    for index, (question, answer) in enumerate(items, start=1):
        html = html.replace(
            f"__FAQ_Q{index}__", json.dumps(question, ensure_ascii=False)
        )
        html = html.replace(
            f"__FAQ_A{index}__", json.dumps(answer, ensure_ascii=False)
        )

    html = (
        html.replace("__FAQ_HTML__", faq_html(items))
        .replace("__INSTALL_SECTION__", install_section())
        .replace("__CATALOG_CARD__", catalog_card(_catalog_count()))
        .replace("__DOWNLOAD_URL__", download_url_property())
        .replace("__PRO_PRICE__", str(price))
        .replace("__PRO_PRICE_BN__", bengali_digits(price))
        # The absolute URLs written above are rewritten to the canonical origin
        # from settings, so a custom domain does not leave canonical/OG tags and
        # structured-data @ids pointing at the old host.
        .replace("https://rakho-api.onrender.com", site_url())
    )
    return html


def site_url():
    return getattr(settings, "SITE_URL", "https://rakho-api.onrender.com").rstrip("/")
