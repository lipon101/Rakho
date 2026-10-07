"""Public policy pages.

Google Play requires a reachable privacy policy for every published app, and
the Rakho Android app links to these two URLs from Settings. They are plain
HTML with no build step so they can never break a deploy.
"""

BRAND = "Rakho"
CONTACT_EMAIL = "support@rakho.app"
EFFECTIVE_DATE = "18 September 2026"

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
<p class="meta">Effective {EFFECTIVE_DATE} &middot; Applies to the {BRAND} Android app, the {BRAND} web app and the {BRAND} API.</p>

<p>{BRAND} helps pharmacies in Bangladesh keep stock, expiry dates and sales in order.
This policy explains exactly what we store, why, and how you can have it removed.</p>

<div class="note">
  <strong>In short:</strong> we store the pharmacy's own business records and the phone number
  you choose to enter. We do not sell data, we do not run advertising trackers, and we do not
  collect location, contacts, photos or your personal files.
</div>

<h2>What we collect</h2>
<ul>
  <li><strong>Pharmacy account details</strong> — pharmacy name, address and phone number that
      you (or your distributor) enter when the account is created or later edited in Settings.</li>
  <li><strong>Inventory and sales records</strong> — medicines, batches, expiry dates, purchase
      costs, selling prices, stock movements and sales you record in the app.</li>
  <li><strong>API key</strong> — a key that identifies your pharmacy to our servers. It is stored
      on your device and sent with each request; we keep only a one-way hash of it on the server.</li>
  <li><strong>Subscription status</strong> — which plan your pharmacy is on and when it renews.</li>
  <li><strong>Basic technical data</strong> — timestamps and error information needed to operate
      the service securely.</li>
</ul>

<h2>What we never collect</h2>
<ul>
  <li>Your location, contacts, camera roll, call logs, SMS or files. Camera permission is used
      only if you choose to scan a barcode, and the image is processed on the device.</li>
  <li>Patient or customer records beyond what the pharmacy itself chooses to type into a
      sale note.</li>
  <li>Advertising identifiers: the app contains no advertising or third-party analytics SDKs.</li>
</ul>

<h2>Why we use it</h2>
<ul>
  <li>To run the service: showing your stock, alerting you about expiring batches, syncing
      between your devices, and producing reports.</li>
  <li>To verify and manage your subscription.</li>
  <li>To provide support when you contact us.</li>
</ul>

<h2>Payments</h2>
<ul>
  <li><strong>In-app subscriptions</strong> are processed by <strong>Google Play Billing</strong>.
      Google handles the payment and gives us a purchase token and subscription status —
      we never see or store your card or mobile-wallet credentials.</li>
  <li><strong>Web or B2B payments</strong> are processed by Bangladeshi payment providers
      (bKash, Nagad, Rocket, upay or bank transfer). Those providers receive only the
      information needed to complete the transaction.</li>
</ul>

<h2>Where the data lives</h2>
<p>Data is stored on servers in the region you deploy to (currently Singapore/Oregon managed
Postgres) and in an on-device database on each phone or tablet that uses your account, so the
app keeps working without internet and syncs when a connection returns.</p>

<h2>Who can see it</h2>
<p>Only your pharmacy, through the API key issued to you. We do not sell, rent or share your
records with third parties, except where the law requires it or where a processor
(hosting, payment) needs it to run the service under confidentiality.</p>

<h2>How long we keep it</h2>
<p>For as long as your pharmacy account is active. Deleting your account removes the pharmacy,
its inventory, sales and subscription records from production within 30 days, with the
remainder expiring from backups within 90 days.</p>

<h2>Your choices</h2>
<ul>
  <li><strong>Delete your account:</strong> in the app, go to <em>Settings → Delete account</em>,
      or email <a href="mailto:{CONTACT_EMAIL}">{CONTACT_EMAIL}</a> from any address and we will
      delete the pharmacy and all associated records.</li>
  <li><strong>Export your data:</strong> Reports → Export CSV produces a copy of your sales;
      your pharmacy can also request a full export by email.</li>
  <li><strong>Disconnect a device:</strong> Settings → Disconnect removes the API key and cached
      data from that device immediately.</li>
  <li><strong>Revoke a key:</strong> ask us to rotate your pharmacy key; the old one stops
      working at once.</li>
</ul>

<h2>Children</h2>
<p>{BRAND} is a business tool for pharmacies and is not directed at children under 13.
We do not knowingly collect data from children.</p>

<h2>Security</h2>
<p>Traffic is encrypted in transit (HTTPS). API keys are stored hashed, databases are not
exposed publicly, and access to production is limited. No system is perfectly secure, so
please tell us immediately if you suspect a problem.</p>

<h2>Changes</h2>
<p>If this policy changes in a way that affects you, we will update this page and note the new
effective date before the change takes effect.</p>

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
<p>{BRAND} is software for managing pharmacy inventory, expiry dates and sales. It is a record
keeping tool: it does not give medical advice and it does not replace the pharmacist's own
professional judgement or the requirements of the Directorate General of Drug Administration
(DGDA) and other Bangladeshi authorities.</p>

<h2>2. Your account</h2>
<ul>
  <li>Your pharmacy is responsible for keeping its API key confidential and for everything
      done with that key.</li>
  <li>You must provide accurate pharmacy details and use the service lawfully.</li>
  <li>You are responsible for the accuracy of the stock, prices and sales you enter. {BRAND}
      cannot verify what a pharmacy records.</li>
</ul>

<h2>3. Subscriptions and payment</h2>
<ul>
  <li>{BRAND} offers a free plan and paid plans (Pro, Business). Prices are shown in the app
      before purchase, in BDT where applicable.</li>
  <li>In-app subscriptions are billed by Google Play and renew automatically until cancelled.
      You can cancel at any time in <em>Google Play → Subscriptions</em>; access continues until
      the end of the paid period.</li>
  <li>Purchases made through our website or through a distributor are governed by the
      invoice you receive and are billed by the payment provider used (bKash, Nagad, Rocket,
      upay or bank transfer).</li>
  <li>Refunds for Google Play purchases follow Google's refund policy. For web or B2B
      payments, contact us within 14 days of purchase.</li>
</ul>

<h2>4. Acceptable use</h2>
<p>Do not attempt to break into the service, resell access without a written agreement, upload
unlawful content, or use {BRAND} in a way that breaks Bangladeshi law or the rules of the
pharmacy regulator.</p>

<h2>5. Availability</h2>
<p>We work to keep {BRAND} available and the app usable offline, but the service is provided
"as is" without a warranty of uninterrupted availability. Scheduled maintenance and outages
can happen; keep your own records for any period where you cannot access the service.</p>

<h2>6. Liability</h2>
<p>To the extent permitted by law, our total liability for any claim relating to the service is
limited to the amount you paid us in the twelve months before the claim. We are not liable for
lost profit or for losses caused by data you entered incorrectly.</p>

<h2>7. Your data</h2>
<p>Your pharmacy records remain yours. We handle them as described in our Privacy Policy. You
can export your data and ask for deletion at any time.</p>

<h2>8. Changes and termination</h2>
<p>We may update these terms and will publish the new effective date here. You can stop using
{BRAND} at any time; we may suspend an account that breaks these terms or that is used
fraudulently, after telling you where practicable.</p>

<h2>9. Governing law</h2>
<p>These terms are governed by the laws of the People's Republic of Bangladesh, and the courts
of Dhaka have jurisdiction over any dispute.</p>

<h2>10. Contact</h2>
<p><a href="mailto:{CONTACT_EMAIL}">{CONTACT_EMAIL}</a></p>
"""
    return _page("Terms of Service", body)
