"""Public invitation acceptance page (/console/join?token=...).

A manager invites a staff member from the console; the email's only link is
this page. The token in the URL is the whole credential, so the page needs to
read who/where/what the invitation is before the recipient has any session,
then either create their account or point them at sign-in.

The page deliberately does not grant anything by itself: ``register`` creates
the account *and* spends the token in one step server-side, so there is no
client-side path to membership that skips validation.
"""

import json
from html import escape

from django.conf import settings


def _js_string(value: str) -> str:
    """A JSON string literal safe to embed inside an inline ``<script>``.

    The invitation token arrives in the URL, so it is attacker-controlled.
    Substituting it raw into a quoted JavaScript string lets a crafted link
    close the string and run script on this origin (reflected XSS).
    ``json.dumps`` quotes and escapes it as one string literal, and escaping
    ``<`` and ``>`` keeps a literal from closing the script block --- the page's
    own ``</script>`` must be the only one in the response.
    """
    return json.dumps(value).replace("<", "\\u003c").replace(">", "\\u003e")


def join_page(token: str):
    """Render the join page with the token embedded safely in script context.

    Everything else on the page is filled in by the browser from the read-only
    info endpoint, so an expired or unknown token produces the same honest
    message here as it does there: the server decides, the page just reports.
    """
    site = getattr(settings, "SITE_URL", "")
    page = """<!DOCTYPE html>
<html lang="bn">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Rakho — আমন্ত্রণ</title>
<meta name="robots" content="noindex">
<style>
  :root{--green:#0E9F6E;--deep:#0B6B4A;--ink:#122019;--muted:#5b6f66;--card:#fff;--line:#E7E2D5;--soft:#EAF4EF}
  *{margin:0;padding:0;box-sizing:border-box}
  body{font-family:'Segoe UI',system-ui,Roboto,'Noto Sans Bengali',sans-serif;background:#FBFAF6;
       color:var(--ink);min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:22px;max-width:480px;width:100%;
        padding:34px 30px;box-shadow:0 20px 50px -20px rgba(18,32,25,.18)}
  .logo{display:flex;align-items:center;gap:9px;font-weight:800;color:var(--deep);margin-bottom:6px}
  .logo .mark{width:32px;height:32px;border-radius:9px;background:linear-gradient(135deg,var(--green),var(--deep));
      display:flex;align-items:center;justify-content:center;color:#fff}
  h1{font-size:1.5rem;font-weight:800;margin:10px 0 2px}
  .sub{color:var(--muted);font-size:.92rem;margin-bottom:18px}
  dl{background:var(--soft);border-radius:14px;padding:16px 18px;margin-bottom:18px}
  dl div{display:flex;justify-content:space-between;gap:12px;padding:5px 0;font-size:.9rem}
  dt{color:var(--muted)}
  dd{font-weight:700;text-align:right}
  label{display:block;font-weight:700;font-size:.85rem;margin:14px 0 6px}
  input{width:100%;padding:14px 16px;border-radius:12px;border:1.5px solid var(--line);font-size:.98rem}
  input:focus{outline:none;border-color:var(--green);box-shadow:0 0 0 4px rgba(14,159,110,.15)}
  .btn{width:100%;margin-top:20px;padding:14px;border:none;border-radius:12px;background:var(--green);
       color:#fff;font-weight:800;font-size:1rem;cursor:pointer;box-shadow:0 10px 24px -8px rgba(14,159,110,.5)}
  .btn:disabled{opacity:.6;cursor:default}
  .alt{display:block;text-align:center;font-size:.85rem;color:var(--muted);margin-top:14px}
  .alt a{color:var(--deep);font-weight:700;text-decoration:none}
  .ok{display:none;background:var(--soft);border:1px solid var(--green);color:var(--deep);border-radius:12px;
      padding:16px;margin-top:6px;font-size:.92rem}
  .err{color:#B3261E;font-size:.85rem;margin-top:10px;display:none;line-height:1.5}
  .hint{font-size:.78rem;color:var(--muted);margin-top:6px}
  .load{color:var(--muted);font-size:.9rem}
</style>
</head>
<body>
<div class="card">
  <div class="logo"><span class="mark">✚</span>Rakho</div>
  <h1>আমন্ত্রণ</h1>
  <p class="sub load" id="loading">আমন্ত্রণটি যাচাই করা হচ্ছে…</p>

  <div id="info" style="display:none">
    <dl>
      <div><dt>দোকান</dt><dd id="org">—</dd></div>
      <div><dt>দায়িত্ব</dt><dd id="role">—</dd></div>
      <div><dt>আমন্ত্রণ জানিয়েছেন</dt><dd id="inviter">—</dd></div>
      <div><dt>ঠিকানা</dt><dd id="email">—</dd></div>
      <div><dt>মেয়াদ</dt><dd id="expires">—</dd></div>
    </dl>

    <form id="joinForm">
      <label for="username">ইউজারনেম</label>
      <input type="text" id="username" autocomplete="username" required>
      <label for="password">পাসওয়ার্ড</label>
      <input type="password" id="password" autocomplete="new-password" required>
      <p class="hint">পাসওয়ার্ড অন্তত ১২ অক্ষরের রাখুন — সাধারণ বা শুধু সংখ্যার পাসওয়ার্ড গ্রহণ করা হয় না।</p>
      <button type="submit" class="btn" id="joinBtn">অ্যাকাউন্ট খুলে যোগ দিন</button>
      <span class="alt">এই ঠিকানায় আগে থেকেই অ্যাকাউন্ট আছে? <a href="__CONSOLE__/">সাইন ইন করুন</a></span>
      <div class="err" id="errBox"></div>
    </form>

    <div class="ok" id="okBox">✓ যোগ দিয়ে গেছেন! এখন কনসোলে প্রবেশ করুন।
      <a href="__CONSOLE__/" style="color:var(--deep);font-weight:700">কনসোল খুলুন</a></div>
  </div>

  <div class="err" id="deadBox" style="display:none"></div>
</div>

<script>
(function(){
  var TOKEN=__TOKEN__;
  var info=document.getElementById('info'),loading=document.getElementById('loading'),
      form=document.getElementById('joinForm'),btn=document.getElementById('joinBtn'),
      err=document.getElementById('errBox'),ok=document.getElementById('okBox'),
      dead=document.getElementById('deadBox');
  var ROLES={owner:'মালিক',manager:'ম্যানেজার',staff:'স্টাফ'};

  // The API error envelope is {error:{code,detail,fields}}; a missing or spent
  // token answers 404 with no detail worth trusting, so the page says the one
  // true thing: the link is not valid any more.
  function message(body,fallback){
    var e=body&&body.error;
    if(!e){return fallback;}
    if(typeof e==='string'){return e;}
    var lines=[e.detail||fallback];
    var f=e.fields||{};
    for(var k in f){if(Object.prototype.hasOwnProperty.call(f,k)){
      (f[k]||[]).forEach(function(m){lines.push(m);});
    }}
    return lines.filter(Boolean).join(' ');
  }

  function showDead(text){
    loading.style.display='none';
    dead.textContent=text; dead.style.display='block';
  }

  fetch('/api/v1/org/invitations/info/?token='+encodeURIComponent(TOKEN))
    .then(function(r){return r.json().then(function(d){return{ok:r.ok,d:d};});})
    .then(function(res){
      if(!res.ok){ showDead(message(res.d,'এই আমন্ত্রণ লিংকটি অবৈধ — হয়তো মেয়াদ শেষ হয়েছে বা আগেই ব্যবহার হয়েছে।')); return; }
      var d=res.d;
      loading.style.display='none';
      document.getElementById('org').textContent=d.organisation||'—';
      document.getElementById('role').textContent=ROLES[d.role]||d.role||'—';
      document.getElementById('inviter').textContent=d.invited_by||'—';
      document.getElementById('email').textContent=d.email_masked||'—';
      document.getElementById('expires').textContent=d.expires_on||'—';
      info.style.display='block';
    })
    .catch(function(){ showDead('সার্ভারে পৌঁছানো যায়নি। ইন্টারনেট সংযোগ দেখে আবার চেষ্টা করুন।'); });

  form.addEventListener('submit',function(e){
    e.preventDefault(); err.style.display='none';
    btn.disabled=true; btn.textContent='তৈরি হচ্ছে…';
    fetch('/api/v1/org/invitations/register/',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({token:TOKEN,username:document.getElementById('username').value,password:document.getElementById('password').value})
    }).then(function(r){return r.json().then(function(d){return{ok:r.ok,d:d};});})
    .then(function(res){
      btn.disabled=false; btn.textContent='অ্যাকাউন্ট খুলে যোগ দিন';
      if(res.ok){ form.style.display='none'; ok.style.display='block'; return; }
      // An account already exists for the invited mailbox: signing in is the
      // right move, not a second identity for the same shop.
      var code=res.d&&res.d.error&&res.d.error.code;
      if(code==='account_exists'){
        err.textContent='এই ঠিকানায় অ্যাকাউন্ট আছে — উপরের লিংক থেকে সাইন ইন করে আমন্ত্রণ গ্রহণ করুন।';
      }else{
        err.textContent=message(res.d,'যোগ দেওয়া যায়নি। আবার চেষ্টা করুন।');
      }
      err.style.display='block';
    })
    .catch(function(){
      btn.disabled=false; btn.textContent='অ্যাকাউন্ট খুলে যোগ দিন';
      err.textContent='সার্ভারে পৌঁছানো যায়নি। আবার চেষ্টা করুন।'; err.style.display='block';
    });
  });
})();
</script>
</body>
</html>"""
    # Only the token --- the one attacker-controlled value --- reaches script
    # context, and ``_js_string`` makes it inert there. The console path is a
    # site constant, escaped as text for its HTML context.
    return page.replace("__TOKEN__", _js_string(token)).replace("__CONSOLE__", escape(str(site), quote=True) + "/app")
