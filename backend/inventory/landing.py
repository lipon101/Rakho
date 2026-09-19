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
"""

import json

from django.conf import settings

from .pricing import pro_price_bdt  # noqa: F401  (re-exported for callers/tests)

_HEAD = """<!DOCTYPE html>
<html lang="bn">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Rakho — ফার্মেসি ম্যানেজমেন্ট অ্যাপ | Pharmacy Inventory, Expiry & Baki App for Bangladesh</title>
<meta name="description" content="বাংলাদেশের ফার্মেসির জন্য বানানো অ্যাপ — মেয়াদোত্তীর্ণ ওষুধের সতর্কতা, FEFO বিলিং, স্টক আর বাকির খাতা। অফলাইনেও চলে, ফ্রি-তে শুরু। Pharmacy inventory, expiry alerts, baki book and FEFO billing that works offline.">
<meta name="robots" content="index,follow,max-image-preview:large,max-snippet:-1">
<link rel="canonical" href="https://rakho-api.onrender.com/">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Rakho">
<meta property="og:url" content="https://rakho-api.onrender.com/">
<meta property="og:locale" content="bn_BD">
<meta property="og:locale:alternate" content="en_US">
<meta property="og:title" content="Rakho — ফার্মেসি ম্যানেজমেন্ট অ্যাপ">
<meta property="og:description" content="মেয়াদোত্তীর্ণ ওষুধে আর টাকা হারাবেন না। মেয়াদ, স্টক, বিক্রি আর বাকির খাতা — সব এক জায়গায়, অফলাইনেও চলে।">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="Rakho — ফার্মেসি ম্যানেজমেন্ট অ্যাপ">
<meta name="twitter:description" content="মেয়াদোত্তীর্ণ ওষুধে আর টাকা হারাবেন না। মেয়াদ, স্টক, বিক্রি আর বাকির খাতা — সব এক জায়গায়।">
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
    --green:#0E9F6E; --green-deep:#0B6B4A; --ink:#122019; --muted:#5b6f66;
    --paper:#FBFAF6; --card:#ffffff; --line:#E7E2D5; --soft:#EAF4EF;
  }
  *{margin:0;padding:0;box-sizing:border-box}
  /* Anchor links must not hide under the sticky nav; smooth scrolling is
     opt-out for anyone who has asked for reduced motion. */
  html{scroll-behavior:smooth;scroll-padding-top:84px}
  @media (prefers-reduced-motion:reduce){
    html{scroll-behavior:auto}
    .card, .btn-primary, .step, .qa{transition:none !important}
    .card:hover, .btn-primary:hover{transform:none !important}
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
  .hero{padding:72px 0 56px;text-align:center}
  .badge{display:inline-block;background:var(--soft);color:var(--green-deep);font-weight:700;
         font-size:.8rem;padding:6px 14px;border-radius:999px;margin-bottom:18px;border:1px solid #d4e8de}
  h1{font-size:clamp(2rem,5vw,3.3rem);line-height:1.15;font-weight:800;letter-spacing:-.02em}
  h1 .accent{color:var(--green)}
  .hero p.sub{max-width:640px;margin:18px auto 0;font-size:1.12rem;color:var(--muted)}
  .hero .cta{margin-top:30px;display:flex;gap:12px;justify-content:center;flex-wrap:wrap}
  .trust{margin-top:22px;font-size:.85rem;color:var(--muted)}
  .trust span{margin:0 10px}
  section{padding:54px 0}
  h2{font-size:clamp(1.4rem,3vw,2rem);font-weight:800;text-align:center;letter-spacing:-.01em}
  .lead{text-align:center;color:var(--muted);max-width:600px;margin:10px auto 0}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:18px;margin-top:38px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:24px;
        transition:transform .15s ease,box-shadow .15s ease}
  .card:hover{transform:translateY(-4px);box-shadow:0 14px 30px -12px rgba(18,32,25,.12)}
  .card .ic{font-size:1.7rem}
  .card h3{margin:12px 0 6px;font-size:1.05rem}
  .card p{font-size:.92rem;color:var(--muted)}
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

  /* 3-step how it works */
  .steps{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:18px;margin-top:36px}
  .step{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:24px}
  .step .n{display:inline-grid;place-items:center;width:30px;height:30px;border-radius:9px;
           background:var(--soft);color:var(--green-deep);font-weight:800;font-size:.9rem}
  .step h3{margin:12px 0 6px;font-size:1.02rem}
  .step p{font-size:.92rem;color:var(--muted)}

  /* FAQ: native details/summary so it works with JavaScript disabled */
  .faq{max-width:780px;margin:34px auto 0;display:grid;gap:10px}
  .qa{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 18px}
  .qa summary{font-weight:700;font-size:.98rem;cursor:pointer;list-style:none}
  .qa summary::-webkit-details-marker{display:none}
  .qa summary::after{content:"+";float:right;font-weight:800;color:var(--green)}
  .qa[open] summary::after{content:"\2013"}
  .qa p{margin-top:10px;color:var(--muted);font-size:.92rem}

  /* Inline form error instead of a blocking alert() dialog */
  .form-error{display:none;font-size:.85rem;font-weight:600;color:#FFE7E2;background:#8C2415;
              border-radius:10px;padding:10px 12px;text-align:center;margin:0}
  .form-error.show{display:block}
  footer{border-top:1px solid var(--line);padding:34px 0;color:var(--muted);font-size:.85rem}
  footer .wrap{display:flex;justify-content:space-between;gap:14px;flex-wrap:wrap}
  @media(max-width:720px){.navlinks{display:none}}
  @media(max-width:560px){.hero{padding:52px 0 40px}.signup{padding:32px 20px}}
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
      "inLanguage":["bn-BD","en"],
      "publisher":{"@id":"https://rakho-api.onrender.com/#organization"},
      "description":"মেয়াদোত্তীর্ণ ওষুধের সতর্কতা, FEFO বিলিং, স্টক ও বাকির খাতা — অফলাইনেও চলে।",
      "featureList":[
        "মেয়াদ রাডার — ব্যাচের মেয়াদ শেষ হওয়ার আগেই সতর্কতা",
        "বাকির খাতা — কে কত পাবে তার হিসাব",
        "দ্রুত বিলিং — ক্যাশ, বিকাশ, নগদ ও বাকি এক স্ক্রিনে",
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
    <a href="#pricing">দাম</a>
    <a href="#faq">প্রশ্ন</a>
  </div>
  <a class="btn btn-primary btn-sm" href="#get">ফ্রি শুরু করুন</a>
</div></nav>

<header class="hero"><div class="wrap">
  <span class="badge">🇧🇩 বাংলাদেশের ফার্মেসির জন্য তৈরি</span>
  <h1>মেয়াদোত্তীর্ণ ওষুধে<br>আর <span class="accent">টাকা হারাবেন না</span></h1>
  <p class="sub">ওষুধের মেয়াদ, স্টক, বিক্রি আর বাকির খাতা — সব এক অ্যাপে।
  মেয়াদ শেষের আগে সতর্কতা, অফলাইনেও চলে, আর ফ্রি-তে শুরু।</p>
  <div class="cta">
    <a class="btn btn-primary" href="#get">ফ্রি অ্যাকাউন্ট খুলুন</a>
    <a class="btn btn-outline" href="#features">কী কী পাবেন</a>
  </div>
  <div class="trust"><span>✓ কার্ড লাগবে না</span><span>✓ অফলাইনে চলে</span><span>✓ বাংলা ও English</span></div>
</div></header>

<section id="features"><div class="wrap">
  <h2>আপনার দোকানের জন্য যা যা আছে</h2>
  <p class="lead">ছোট দোকান থেকে বড় ফার্মেসি — সবার কাজ সহজ করতে বানানো।</p>
  <div class="grid">
    <div class="card"><div class="ic">⏰</div><h3>মেয়াদ রাডার</h3><p>কোন ব্যাচের মেয়াদ শেষ হচ্ছে আগেই জানান দেয় — মেয়াদোত্তীর্ণ ওষুধ ভুলেও বিক্রি হয় না।</p></div>
    <div class="card"><div class="ic">🤝</div><h3>বাকির খাতা</h3><p>কে কত টাকা পাবে, কখন থেকে — সব লেখা থাকে। টাকা এলেই এক ট্যাপে হিসাব মিটে যায়।</p></div>
    <div class="card"><div class="ic">🧾</div><h3>দ্রুত বিলিং</h3><p>FEFO পদ্ধতিতে আগে মেয়াদের ওষুধ আগে বিক্রি হয়। ক্যাশ, বিকাশ, নগদ, বাকি — সব এক স্ক্রিনে।</p></div>
    <div class="card"><div class="ic">📶</div><h3>অফলাইনে চলে</h3><p>লোডশেডিং বা নেট না থাকলেও বিক্রি ও স্টক চলতে থাকে। নেট ফিরলে নিজেই সিংক হয়।</p></div>
    __CATALOG_CARD__
    <div class="card"><div class="ic">📊</div><h3>রিপোর্ট</h3><p>দৈনিক বিক্রি, লাভ, সবচেয়ে বেশি বিক্রিত ওষুধ — এক নজরে সব, এক্সপোর্ট করা যায়।</p></div>
    <div class="card"><div class="ic">📉</div><h3>লো স্টক অ্যালার্ট</h3><p>কোন ওষুধ শেষ হয়ে আসছে আগেই জানিয়ে দেয় — ক্রেতাকে খালি হাতে ফিরিয়ে দিতে হয় না।</p></div>
    <div class="card"><div class="ic">🗑️</div><h3>নষ্ট ওষুধ রাইট-অফ</h3><p>মেয়াদোত্তীর্ণ বা নষ্ট ওষুধ এক ট্যাপে স্টক থেকে বাদ — হিসাব সবসময় পরিষ্কার থাকে।</p></div>
  </div>
</div></section>

<section id="how"><div class="wrap">
  <h2>শুরু করতে ৩ ধাপ</h2>
  <p class="lead">কার্ড লাগে না, সেটআপ লাগে না — নাম দিলেই কাজ শুরু।</p>
  <div class="steps">
    <div class="step"><span class="n" aria-hidden="true">১</span><h3>ফ্রি API কী নিন</h3><p>আপনার নাম আর ফার্মেসির নাম দিন — সাথে সাথে কী তৈরি।</p></div>
    <div class="step"><span class="n" aria-hidden="true">২</span><h3>অ্যাপে কী দিয়ে লগইন</h3><p>কী-টি কপি করে অ্যাপে বসান। আপনার ফার্মেসির হিসাব চালু।</p></div>
    <div class="step"><span class="n" aria-hidden="true">৩</span><h3>ওষুধ যোগ করে বিক্রি শুরু</h3><p>ওষুধ ও মেয়াদ যোগ করুন — বিক্রির সময় FEFO নিজেই আগের মেয়াদের ব্যাচ আগে বেছে নেবে।</p></div>
  </div>
</div></section>

<section id="pricing" style="background:var(--soft)"><div class="wrap">
  <h2>সহজ মূল্য</h2>
  <p class="lead">ফ্রি-তে শুরু করুন, দরকার হলে Pro-তে যান।</p>
  <div class="plans">
    <div class="plan">
      <h3>ফ্রি</h3>
      <div class="price">৳০</div><div class="per">চিরকালের জন্য</div>
      <ul>
        <li>বিক্রি, স্টক, মেয়াদ ও বাকি</li>
        <li>অফলাইনে সম্পূর্ণ চলে</li>
        <li>১টি ডিভাইস</li>
        <li>ম্যানুয়াল ওষুধ এন্ট্রি</li>
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
        <li>ক্যাটালগ থেকে অটো ওষুধ এন্ট্রি</li>
        <li>ক্লাউড ব্যাকআপ</li>
        <li>রিপোর্ট এক্সপোর্ট (CSV/PDF)</li>
      </ul>
      <a class="btn btn-primary" href="#get" style="width:100%;text-align:center">Pro নিন</a>
    </div>
  </div>
</div></section>

<section id="faq"><div class="wrap">
  <h2>সাধারণ প্রশ্ন</h2>
  <p class="lead">যা সবাই জিজ্ঞেস করেন।</p>
  __FAQ_HTML__
</div></section>
"""

_BODY_TAIL = """
<section id="get"><div class="wrap">
  <div class="signup">
    <h2>আজই শুরু করুন — ১ মিনিটেই</h2>
    <p class="lead">নাম আর ফার্মেসির নাম দিন, সাথে সাথে আপনার ফ্রি API কী পেয়ে যাবেন।</p>
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
        body = (f"জাতীয় ক্যাটালগে এখন <strong>{count:,}</strong>টি ওষুধ — "
                "নাম লিখলেই চলে আসে, পুরোটা টাইপ করতে হয় না।")
    else:
        body = ("নিজের ওষুধ নিজে যোগ করুন — নাম, সল্ট, শক্তি আর দাম একবার "
                "লিখলেই প্রতিটি বিক্রিতে কাজে লাগে।")
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
            "না। ফ্রি প্ল্যানে বিক্রি, স্টক, মেয়াদ আর বাকির হিসাব চিরকালের জন্য "
            "ফ্রি — কার্ড বা পেমেন্ট লাগে না। দরকার হলে Pro ৳" + price_bn +
            "/মাসে সব ডিভাইসে সিংক, ক্লাউড ব্যাকআপ ও রিপোর্ট এক্সপোর্ট পাওয়া যায়।",
        ),
        (
            "ইন্টারনেট না থাকলে কি চলবে?",
            "হ্যাঁ। লোডশেডিং বা নেট না থাকলেও বিক্রি ও স্টক চলতে থাকে; নেট ফিরলে "
            "নিজে থেকে সিংক হয়ে যায়।",
        ),
        (
            "শুরু করতে কী লাগবে?",
            "শুধু আপনার নাম আর ফার্মেসির নাম দিলেই সাথে সাথে একটি ফ্রি API কী "
            "পাবেন — কোনো কার্ড বা ডাউনলোড লাগে না।",
        ),
        (
            "ডেটা কি নিরাপদ থাকবে?",
            "আপনার ফার্মেসির হিসাব আপনার নিজের অ্যাকাউন্টের অধীনে থাকে এবং API "
            "কী দিয়েই সুরক্ষিত থাকে। কী হারালে কনসোল থেকে নতুন কী নিতে পারেন, "
            "আর পুরোনো কী সাথে সাথে বাতিল করা যায়।",
        ),
    ]


def faq_html(items):
    """Visible accordion. Native <details> so it works without JavaScript."""
    rows = "".join(
        f'<details class="qa"><summary>{question}</summary><p>{answer}</p></details>'
        for question, answer in items
    )
    return f'<div class="faq">{rows}</div>'


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
        .replace("__CATALOG_CARD__", catalog_card(_catalog_count()))
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
