"""Public marketing landing page.

Self-contained HTML (no build step, no external JS) so a deploy can never
break it. The signup form posts to the public API and shows the issued key
inline — a visitor becomes a working pharmacy without any manual step.
"""

_HEAD = """<!DOCTYPE html>
<html lang="bn">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Rakho — ফার্মেসি ম্যানেজমেন্ট অ্যাপ | Pharmacy App for Bangladesh</title>
<meta name="description" content="বাংলাদেশের ফার্মেসির জন্য তৈরি। ওষুধের মেয়াদ, স্টক, বিক্রি আর বাকির খাতা এক অ্যাপে। Expiry alerts, stock, baki book & FEFO billing — free to start, works offline.">
<meta property="og:title" content="Rakho — ফার্মেসি ম্যানেজমেন্ট অ্যাপ">
<meta property="og:description" content="ওষুধের মেয়াদ শেষ হওয়ার আগেই সতর্কতা। বাকির হিসাব, স্টক, বিক্রি — সব এক জায়গায়। ফ্রি-তে শুরু করুন।">
<meta name="theme-color" content="#0E9F6E">
<style>
  :root{
    --green:#0E9F6E; --green-deep:#0B6B4A; --ink:#122019; --muted:#5b6f66;
    --paper:#FBFAF6; --card:#ffffff; --line:#E7E2D5; --soft:#EAF4EF;
  }
  *{margin:0;padding:0;box-sizing:border-box}
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
  footer{border-top:1px solid var(--line);padding:34px 0;color:var(--muted);font-size:.85rem}
  footer .wrap{display:flex;justify-content:space-between;gap:14px;flex-wrap:wrap}
  @media(max-width:560px){.hero{padding:52px 0 40px}}
</style>
</head>
"""

_BODY_HEAD = """<body>
<nav><div class="wrap">
  <div class="logo"><span class="mark">✚</span>Rakho</div>
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
    <div class="card"><div class="ic">💊</div><h3>১৪,০০০+ ওষুধের তালিকা</h3><p>জাতীয় ক্যাটালগ থেকে নাম লিখলেই ওষুধ চলে আসে — টাইপ করতে হয় না।</p></div>
    <div class="card"><div class="ic">📊</div><h3>রিপোর্ট</h3><p>দৈনিক বিক্রি, লাভ, সবচেয়ে বেশি বিক্রিত ওষুধ — এক নজরে সব, এক্সপোর্ট করা যায়।</p></div>
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
      <div class="price">৳২৯৯</div><div class="per">প্রতি মাস</div>
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
"""

_BODY_TAIL = """
<section id="get"><div class="wrap">
  <div class="signup">
    <h2>আজই শুরু করুন — ১ মিনিটেই</h2>
    <p class="lead">নাম আর ফার্মেসির নাম দিন, সাথে সাথে আপনার ফ্রি API কী পেয়ে যাবেন।</p>
    <form id="signupForm">
      <input type="text" id="owner" placeholder="আপনার নাম" required>
      <input type="text" id="pharmacy" placeholder="ফার্মেসির নাম" required>
      <input type="tel" id="whatsapp" placeholder="হোয়াটসঅ্যাপ নম্বর (ঐচ্ছিক)">
      <input type="text" id="website" tabindex="-1" autocomplete="off" style="position:absolute;left:-9999px;opacity:0" aria-hidden="true">
      <button type="submit" class="btn btn-primary" id="submitBtn">ফ্রি API কী পান</button>
      <p class="form-note">কোনো পেমেন্ট লাগবে না। কী দিয়েই অ্যাপে লগইন করে কাজ শুরু করুন।</p>
    </form>
    <div id="result">
      <strong>🎉 অভিনন্দন! আপনার API কী তৈরি হয়ে গেছে।</strong>
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
  form.addEventListener('submit', function(e){
    e.preventDefault();
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
        alert(res.d && res.d.error ? res.d.error : 'কিছু ভুল হয়েছে। আবার চেষ্টা করুন।');
      }
    }).catch(function(){
      btn.disabled = false; btn.textContent = 'ফ্রি API কী পান';
      alert('সার্ভারে পৌঁছানো যায়নি। ইন্টারনেট পরীক্ষা করে আবার চেষ্টা করুন।');
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


def landing_page():
    return _HEAD + _BODY_HEAD + _BODY_TAIL
