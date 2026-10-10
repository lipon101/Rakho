"""Public policy pages.

Google Play requires a reachable privacy policy for every published app, and
the Rakho Android app links to these two URLs from Settings. They are plain
HTML with no build step so they can never break a deploy.

These pages describe the product as it actually works, because a policy that is
merely plausible is a liability. The app is free and holds no payment data; it
signs shops in with Firebase Authentication and stores their records in Cloud
Firestore; and it does ship Google's Firebase Analytics and Crashlytics SDKs.
Each of those is a question the Play Data Safety form asks, so each is answered
here rather than glossed over.
"""

BRAND = "Rakho"
CONTACT_EMAIL = "support@rakho.app"
EFFECTIVE_DATE = "10 October 2026"

_STYLE = """
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #f6f8f8; color: #111c19; line-height: 1.65;
    padding: 32px 20px 64px;
  }
  main { max-width: 760px; margin: 0 auto; background: #fff; border-radius: 18px;
         padding: 40px 32px; box-shadow: 0 10px 30px rgba(11, 21, 18, 0.06); }
  h1 { font-size: 1.9rem; margin-bottom: 6px; color: #0e7c66; }
  .meta { color: #5b6b66; font-size: 0.85rem; margin-bottom: 28px; }
  h2 { font-size: 1.1rem; margin: 28px 0 8px; }
  p, li { font-size: 0.95rem; color: #24332e; }
  ul { padding-left: 22px; margin: 8px 0; }
  li { margin-bottom: 4px; }
  a { color: #0e7c66; }
  .note { background: #eef7f4; border-left: 4px solid #0e7c66; padding: 12px 16px;
          border-radius: 8px; margin: 18px 0; font-size: 0.9rem; }
  footer { max-width: 760px; margin: 20px auto 0; text-align: center;
           color: #7a8a85; font-size: 0.8rem; }
"""


def _page(title, body):
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} — {BRAND}</title>
<style>{_STYLE}</style>
</head>
<body>
<main>
{body}
</main>
<footer>{BRAND} &copy; 2026 &middot; Pharmacy inventory &amp; expiry management for Bangladesh</footer>
</body>
</html>"""


def privacy_policy():
    body = f"""
<h1>Privacy Policy</h1>
<p class="meta">Effective {EFFECTIVE_DATE} &middot; Applies to the {BRAND} Android app, the {BRAND} web console and the {BRAND} API.</p>

<p>{BRAND} helps pharmacies in Bangladesh keep stock, expiry dates, sales and customer credit
(baki) in order. This policy states exactly what is stored, where it is stored, who can read it,
and how to have it removed.</p>

<div class="note">
  <strong>In short:</strong> {BRAND} is <strong>completely free</strong> — it collects no payment
  data and stores no card or wallet details. Your shop's records live in your own account and are
  readable only by that account. We do not sell data, we run no advertising, and we do not collect
  your location, contacts, call logs, SMS or files.
</div>

<h2>The two parts of {BRAND}</h2>
<ul>
  <li><strong>The Android app</strong> is the shopkeeper's tool. It signs in with Firebase
      Authentication (email and password) and keeps the shop's data in Cloud Firestore, inside
      your own account.</li>
  <li><strong>The web console</strong> serves multi-branch owners and distributors. It runs on our
      own Django/PostgreSQL servers and holds organisations, members, invitations, branches,
      subscription status and API keys.</li>
</ul>
<p>Both are operated by {BRAND}, Bangladesh. One policy covers both.</p>

<h2>What we collect</h2>
<ul>
  <li><strong>Account details</strong> — your email address, a display name, and the password
      credential held by Firebase Authentication. Passwords are salted and hashed by Firebase;
      nobody at {BRAND} ever sees the plain value.</li>
  <li><strong>Pharmacy profile</strong> — shop name, address and phone number you enter in
      Settings.</li>
  <li><strong>The business records you create</strong> — medicines, batches, expiry dates,
      purchase costs, selling prices, stock movements, sales, expenses and your baki book.</li>
  <li><strong>Names and phone numbers of your customers</strong> — only what the pharmacy itself
      types in, so it can record who owes what and send its own reminder over WhatsApp. These are
      your business records; we use them for nothing else.</li>
  <li><strong>A device identifier</strong> — a random id generated on the phone, used to label
      sales made before an account exists and to make crash reports attributable. It is not a
      hardware serial and not an advertising id.</li>
  <li><strong>Diagnostics</strong> — crash reports and anonymous usage events, described under
      "Google Firebase" below.</li>
  <li><strong>Console records</strong> — for web accounts: organisation name, members and roles,
      invitation email addresses, branches, and API keys stored only as one-way hashes.</li>
</ul>

<h2>What we never collect</h2>
<ul>
  <li><strong>Payment data of any kind.</strong> The app has no purchases and no subscriptions, so
      there is no card number, wallet credential or Google Play purchase token to store.</li>
  <li>Location, contacts, call logs, SMS or files. The camera is used only if you choose to scan a
      barcode, and the frame is analysed on the device — it is never uploaded.</li>
  <li>Advertising identifiers. The app contains no advertising SDK and no ad tracking.</li>
  <li>Patient health records. {BRAND} records that a shop sold something, not who took which
      medicine.</li>
</ul>

<h2>Why it is used</h2>
<ul>
  <li>To run the service: your stock, expiry warnings, billing, baki ledger, sync between your
      devices, and reports.</li>
  <li>To keep your account secure, and to let you delete it.</li>
  <li>To find crashes and learn which features are used, so the app improves.</li>
  <li>To provide support when you contact us.</li>
</ul>

<h2>Google Firebase</h2>
<p>The Android app uses Google Firebase services. This is the disclosure the Play Data Safety form
asks for, stated plainly instead of hidden behind the word "analytics":</p>
<ul>
  <li><strong>Firebase Authentication and Cloud Firestore</strong> hold your account and your
      shop's data.</li>
  <li><strong>Firebase Crashlytics</strong> records crash reports — stack trace, device model,
      app version and your account's anonymous id — so a crash a shop hits can be found and
      fixed.</li>
  <li><strong>Firebase Analytics</strong> records product events such as "a sale was recorded" or
      "an account was created", with counts and a payment <em>method type</em>. It never receives
      an amount, a medicine name or a customer name.</li>
</ul>
<p>Google processes these under its own terms on our instruction, for app diagnostics and product
improvement.</p>

<h2>Where the data lives, and who can read it</h2>
<p>App data sits in Cloud Firestore, in your account's own area of it. Firestore security rules
allow a document to be read or written <strong>only by the signed-in account that owns it</strong>:
there is no shared collection and no public path. A working copy also sits in a private on-device
cache so the app keeps running through load-shedding, and queued writes replay to your account
when the network returns.</p>
<p>Console data sits on managed servers in the region the deployment uses. Beyond your own devices
and staff logins, only you can read your records.</p>

<h2>Retention and deletion</h2>
<ul>
  <li><strong>Instant, self-service.</strong> In the app: <em>Settings → Delete account and
      data</em>. It deletes every Firestore document your account owns and then deletes the
      authentication account itself, in one action, on the spot — no email round trip and no
      waiting period, because data you can watch go is worth more than a promise.</li>
  <li><strong>By request.</strong> Email
      <a href="mailto:{CONTACT_EMAIL}">{CONTACT_EMAIL}</a> from any address and we will delete the
      pharmacy and its associated records.</li>
  <li><strong>Backups.</strong> Server backups and Firestore point-in-time retention expire on
      their own schedule, within 90 days of deletion.</li>
  <li><strong>On-device copy.</strong> Signing out ends that device's access; deleting the account
      clears the records its cache held.</li>
</ul>

<h2>Your choices</h2>
<ul>
  <li><strong>Export:</strong> Reports → Export CSV gives you a copy of your sales in a format
      Excel opens, which you can keep anywhere.</li>
  <li><strong>Notifications:</strong> Settings → Expiry reminders turns the daily alerts off;
      nothing else changes.</li>
  <li><strong>Language:</strong> the app runs in Bangla or English.</li>
  <li><strong>Console keys:</strong> if you use the web console you can rotate or revoke an API key
      at any time; the old one stops working immediately.</li>
</ul>

<h2>Children</h2>
<p>{BRAND} is a business tool for licensed pharmacies and is not directed at children under 13. We
do not knowingly collect data from children.</p>

<h2>Security</h2>
<p>All traffic is encrypted in transit (HTTPS). Firestore access is owner-only by security rule,
console credentials are hashed, and production access is limited. No system is perfectly secure —
if you believe something is wrong, tell us and we will act.</p>

<h2>Changes</h2>
<p>If this policy changes in a way that affects you, we update this page and state the new
effective date here before the change takes effect.</p>

<h2>Contact</h2>
<p>{BRAND} &middot; Bangladesh &middot;
<a href="mailto:{CONTACT_EMAIL}">{CONTACT_EMAIL}</a></p>
"""
    return _page("Privacy Policy", body)


def terms_of_service():
    body = f"""
<h1>Terms of Service</h1>
<p class="meta">Effective {EFFECTIVE_DATE} &middot; These terms govern your use of {BRAND}.</p>

<h2>1. What {BRAND} is</h2>
<p>{BRAND} is software for managing pharmacy inventory, expiry dates, sales and customer credit.
It is a record-keeping tool. It does not give medical advice, it does not dispense medicine, and it
does not replace the pharmacist's own professional judgement or the requirements of the Directorate
General of Drug Administration (DGDA) and other Bangladeshi authorities.</p>

<h2>2. Price: it is free</h2>
<p>{BRAND} is <strong>free to use, with no subscription, no in-app purchase and no renewal</strong>.
Every feature — offline operation, cloud sync across your devices, the medicine catalogue search,
the baki book and reminders, reports and CSV export — is included at no cost. Because no money
changes hands, there is no price to accept, no auto-renewal to cancel and no refund policy to
read. If a paid tier is ever introduced, it will be announced here first, and features an account
already relies on will not be taken away from it.</p>

<h2>3. Your account</h2>
<ul>
  <li>You create your own account with an email address and password, inside the app.</li>
  <li>You are responsible for keeping your credentials safe and for everything done through your
      account. If you lose access, contact us and we will verify you before restoring it.</li>
  <li>Provide accurate pharmacy details, and use the service lawfully.</li>
  <li>You are responsible for the accuracy of the stock, prices, sales and credit entries you
      record. {BRAND} cannot verify what a pharmacy types in, and its reports are only as true as
      that data.</li>
</ul>

<h2>4. Your data</h2>
<p>Your pharmacy records remain yours. You can export your sales at any time, and you can delete
your account and all of its data yourself, instantly, from <em>Settings → Delete account and
data</em>. How we handle data is described in our <a href="/privacy/">Privacy Policy</a>, which
forms part of these terms.</p>

<h2>5. Acceptable use</h2>
<p>Do not attempt to break into the service or another shop's account, do not resell access without
a written agreement, do not upload unlawful content, and do not use {BRAND} in a way that breaks
Bangladeshi law or the rules of the pharmacy regulator.</p>

<h2>6. Availability</h2>
<p>We work to keep {BRAND} available and the app fully usable offline, but the service is provided
"as it is", without a warranty of uninterrupted availability. Planned maintenance and outages can
happen. The app is built to keep selling through a dropped connection and to catch up by itself —
but keep your own records for any period in which you cannot reach the service.</p>

<h2>7. Liability</h2>
<p>To the extent permitted by law, and because the service is provided free of charge, our total
liability for any claim relating to it is limited. We are in any case not liable for lost profit,
or for losses caused by data entered incorrectly.</p>

<h2>8. Changes and termination</h2>
<p>We may update these terms and will publish the new effective date here. You can stop using
{BRAND} at any time and delete your account in the same action; we may suspend an account that
breaks these terms or that is used fraudulently, after telling you where practicable.</p>

<h2>9. Governing law</h2>
<p>These terms are governed by the laws of the People's Republic of Bangladesh, and the courts of
Dhaka have jurisdiction over any dispute.</p>

<h2>10. Contact</h2>
<p><a href="mailto:{CONTACT_EMAIL}">{CONTACT_EMAIL}</a></p>
"""
    return _page("Terms of Service", body)
