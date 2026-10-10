"""The retired Pro checkout, rewritten as an honest notice.

Rakho became a free app: there is no plan to upgrade, no price to show and no
TrxID to collect, so this page asks for nothing.

It still answers, because ``/pay/<token>/`` links were emailed and saved — a
404 there reads like a scam to the person who paid attention to it. The token is
deliberately never written into the response. It used to be embedded in an
inline script that posted the payment form, which made this page a
reflected-XSS surface needing careful escaping; a page that does not echo it
has no such problem to have.
"""

from html import escape

from django.conf import settings

from .static_pages import CONTACT_EMAIL


def pay_page(token: str):
    """Render the "nothing to pay" notice.

    ``token`` is part of the historic URL and is accepted so old links keep
    resolving --- and then dropped, because the page has no legitimate use for
    an attacker-controlled value.
    """
    del token

    support = str(getattr(settings, "SUPPORT_EMAIL", CONTACT_EMAIL))
    support_escaped = escape(support, quote=True)

    whatsapp = str(getattr(settings, "SUPPORT_WHATSAPP", "")).strip()
    digits = "".join(character for character in whatsapp if character.isdigit())
    # wa.me takes the international number with no punctuation at all.
    contact = f'<a class="btn" href="https://wa.me/{escape(digits, quote=True)}">হোয়াটসঅ্যাপে লিখুন</a>' if digits else ""

    return """<!DOCTYPE html>
<html lang="bn">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Rakho — পেমেন্ট লাগে না</title>
<meta name="robots" content="noindex">
<style>
  :root{--green:#0E9F6E;--deep:#0B6B4A;--ink:#122019;--muted:#5b6f66;--card:#fff;--line:#E7E2D5;--soft:#EAF4EF}
  *{margin:0;padding:0;box-sizing:border-box}
  body{font-family:'Segoe UI',system-ui,Roboto,'Noto Sans Bengali',sans-serif;background:#FBFAF6;
       color:var(--ink);min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:22px;max-width:480px;width:100%;
        padding:34px 30px;box-shadow:0 20px 50px -20px rgba(18,32,25,.18);text-align:center}
  .mark{width:52px;height:52px;margin:0 auto 14px;border-radius:15px;
        background:linear-gradient(135deg,var(--green),var(--deep));display:flex;
        align-items:center;justify-content:center;color:#fff;font-size:1.6rem;font-weight:800}
  h1{font-size:1.45rem;font-weight:800;margin-bottom:6px}
  .free{display:inline-block;background:var(--soft);color:var(--deep);font-weight:800;
        font-size:.85rem;border-radius:999px;padding:6px 14px;margin:10px 0 16px}
  p.lead{color:var(--muted);font-size:.95rem;line-height:1.6}
  ul{text-align:left;list-style:none;margin:18px 0 22px}
  li{padding:7px 0;font-size:.92rem;display:flex;gap:9px;color:var(--ink)}
  li::before{content:"\\2713";color:var(--green);font-weight:800}
  .actions{display:flex;gap:10px;justify-content:center;flex-wrap:wrap;margin-top:6px}
  .btn{display:inline-block;padding:12px 20px;border-radius:12px;font-weight:700;font-size:.92rem;
       text-decoration:none;background:var(--soft);color:var(--deep)}
  .btn.primary{background:var(--green);color:#fff}
  .note{font-size:.8rem;color:var(--muted);margin-top:20px;line-height:1.6}
  .note a{color:var(--deep)}
</style>
</head>
<body>
<div class="card">
  <div class="mark" aria-hidden="true">✚</div>
  <h1>Rakho</h1>
  <span class="free">সম্পূর্ণ ফ্রি — কিছুই দিতে হবে না</span>
  <p class="lead">এই পেজটা আগে টাকা নেওয়ার জন্য ছিল। Rakho এখন সম্পূর্ণ ফ্রি,
  তাই এখানে কোনো বিল, কোনো ফর্ম বা কোনো পেমেন্ট নেই।</p>

  <ul>
    <li>বিক্রি, স্টক, মেয়াদ রাডার আর বাকির খাতা</li>
    <li>সব ডিভাইসে অটো সিংক ও ক্লাউড ব্যাকআপ</li>
    <li>২১,০০০+ ওষুধের ক্যাটালগ সার্চ</li>
    <li>রিপোর্ট ও CSV এক্সপোর্ট</li>
  </ul>

  <div class="actions">
    <a class="btn primary" href="/#free">অ্যাপ নামান</a>__CONTACT__
  </div>

  <p class="note">আগে কোনো পেমেন্ট করে থাকলে বা কোনো প্রশ্ন থাকলে লিখুন:
    <a href="mailto:__SUPPORT__">__SUPPORT__</a></p>
</div>
</body>
</html>""".replace("__CONTACT__", contact).replace("__SUPPORT__", support_escaped)
