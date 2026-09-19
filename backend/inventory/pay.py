"""Public Pro upgrade / payment page.

A customer opens this from their private status link, pays the configured MFS
number (bKash/Nagad) by Send Money, and submits the TrxID. The plan is only
activated after the owner verifies the payment in the admin — this page never
grants access by itself.
"""

from django.conf import settings

from .pricing import pro_price_bdt


def pay_page(token: str):
    number = getattr(settings, "PAYMENT_NUMBER", "+8801580857515")
    methods = getattr(settings, "PAYMENT_METHODS", "bKash / Nagad")
    # The same helper the landing page and the console use, so the price shown
    # before payment and the amount asked for here can never disagree.
    price = pro_price_bdt()
    return """<!DOCTYPE html>
<html lang="bn">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Rakho Pro আপগ্রেড</title>
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
  .sub{color:var(--muted);font-size:.92rem;margin-bottom:20px}
  .amount{background:linear-gradient(135deg,var(--green),var(--deep));color:#fff;border-radius:14px;
          padding:16px 18px;display:flex;justify-content:space-between;align-items:center;margin-bottom:20px}
  .amount .lbl{opacity:.9;font-size:.85rem}.amount .val{font-size:1.5rem;font-weight:800}
  ol.steps{list-style:none;margin:0 0 20px}
  ol.steps li{display:flex;gap:11px;padding:9px 0;font-size:.93rem}
  ol.steps .n{width:24px;height:24px;flex:none;border-radius:50%;background:var(--soft);color:var(--deep);
              font-weight:800;font-size:.8rem;display:flex;align-items:center;justify-content:center}
  .num{font-family:monospace;background:var(--soft);border:1px dashed var(--green);padding:3px 8px;
       border-radius:7px;font-weight:700;color:var(--deep)}
  input{width:100%;padding:14px 16px;border-radius:12px;border:1.5px solid var(--line);font-size:.98rem}
  input:focus{outline:none;border-color:var(--green);box-shadow:0 0 0 4px rgba(14,159,110,.15)}
  label{display:block;font-weight:700;font-size:.85rem;margin:14px 0 6px}
  .btn{width:100%;margin-top:20px;padding:14px;border:none;border-radius:12px;background:var(--green);
       color:#fff;font-weight:800;font-size:1rem;cursor:pointer;box-shadow:0 10px 24px -8px rgba(14,159,110,.5)}
  .btn:hover{transform:translateY(-1px)}
  .ok{display:none;background:var(--soft);border:1px solid var(--green);color:var(--deep);border-radius:12px;
      padding:16px;margin-top:18px;font-size:.92rem}
  .err{color:#B3261E;font-size:.85rem;margin-top:8px;display:none}
  .note{font-size:.78rem;color:var(--muted);text-align:center;margin-top:16px}
</style>
</head>
<body>
<div class="card">
  <div class="logo"><span class="mark">✚</span>Rakho</div>
  <h1>Pro-তে আপগ্রেড করুন</h1>
  <p class="sub">__METHODS__ দিয়ে Send Money করুন, তারপর TrxID দিন।</p>

  <div class="amount"><span class="lbl">প্রতি মাস</span><span class="val">৳__PRICE__</span></div>

  <ol class="steps">
    <li><span class="n">1</span><span>আপনার bKash / Nagad অ্যাপ খুলুন</span></li>
    <li><span class="n">2</span><span><b>Send Money</b> নির্বাচন করুন</span></li>
    <li><span class="n">3</span><span>এই নম্বরে পাঠান: <span class="num">__NUMBER__</span></span></li>
    <li><span class="n">4</span><span>পরিমাণ: <span class="num">৳__PRICE__</span></span></li>
    <li><span class="n">5</span><span>পেমেন্টের পর পাওয়া <b>Transaction ID (TrxID)</b> নিচে দিন</span></li>
  </ol>

  <form id="payForm">
    <label for="trx">Transaction ID (TrxID)</label>
    <input type="text" id="trx" placeholder="যেমন: 9H7K2M4X1P" autocomplete="off" required>
    <button type="submit" class="btn" id="payBtn">ভেরিফাই করুন</button>
    <div class="err" id="errBox"></div>
  </form>

  <div class="ok" id="okBox">✓ ধন্যবাদ! পেমেন্ট যাচাই করে অল্প সময়ের মধ্যে আপনার Pro চালু হয়ে যাবে। কোনো সমস্যা হলে আমরা হোয়াটসঅ্যাপে যোগাযোগ করব।</div>

  <p class="note">পেমেন্ট যাচাই ম্যানুয়ালি নিশ্চিত করা হয় — নিরাপদ ও নির্ভরযোগ্য।</p>
</div>

<script>
(function(){
  var form=document.getElementById('payForm'),btn=document.getElementById('payBtn'),
      err=document.getElementById('errBox'),ok=document.getElementById('okBox');
  form.addEventListener('submit',function(e){
    e.preventDefault(); err.style.display='none';
    btn.disabled=true; btn.textContent='যাচাই হচ্ছে…';
    fetch('/api/v1/signup/pay/',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({token:'__TOKEN__',trx_id:document.getElementById('trx').value,plan:'pro'})
    }).then(function(r){return r.json().then(function(d){return{ok:r.ok,d:d};});})
    .then(function(res){
      if(res.ok){ form.style.display='none'; ok.style.display='block'; }
      else{ btn.disabled=false; btn.textContent='ভেরিফাই করুন';
            err.textContent=(res.d&&res.d.error)?res.d.error:'কিছু ভুল হয়েছে। আবার চেষ্টা করুন।'; err.style.display='block'; }
    }).catch(function(){ btn.disabled=false; btn.textContent='ভেরিফাই করুন';
      err.textContent='সার্ভারে পৌঁছানো যায়নি। আবার চেষ্টা করুন।'; err.style.display='block'; });
  });
})();
</script>
</body>
</html>""" \
        .replace("__NUMBER__", number) \
        .replace("__METHODS__", methods) \
        .replace("__PRICE__", str(price)) \
        .replace("__TOKEN__", token)
