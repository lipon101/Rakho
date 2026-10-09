# Firebase setup — the app's entire backend

Rakho is Firebase-only: **Firebase Auth** signs the shopkeeper in, **Cloud
Firestore** is the single database (medicines, batches, sales, dues, purchases,
expenses, customers, profile), and **Crashlytics + Analytics** watch the app
run. There is no API key, no server to babysit, and nothing to pay for on the
Spark (free) plan at pharmacy scale.

Everything below is a one-time setup. After step 5 nothing in the Kotlin
source needs to change.

---

## What is already wired

| Piece | Where | What it does |
|---|---|---|
| Dependencies | `gradle/libs.versions.toml` | Firebase BoM `34.1.0` — Auth, Firestore, Crashlytics, Analytics |
| Conditional plugins | `app/build.gradle.kts` | Applies `google-services` + `crashlytics` **only** when `app/google-services.json` exists, so a clone without credentials still builds |
| Offline persistence | `core/cloud/CloudServices.kt` | Enables Firestore **disk cache** before any read/write — counter sales work with no network and replay once when it returns |
| Data layer | `data/firebase/FirestoreRepository.kt` | All reads/writes under `pharmacies/{uid}/…`, batched writes with `FieldValue.increment` |
| Shared listeners | `data/firebase/FirestoreData.kt` | **One** snapshot listener per collection serves the whole app (free-quota discipline) |
| Auth gate | `ui/nav/RakhoNav.kt` | Reactive: sign-in/sign-out rebuilds the entire navigation graph |
| Account | `feature/settings/` | Sign out; "Delete account and data" wipes every Firestore doc + the auth account on the spot |
| Monitoring | `CloudServices.identify/track` | Crashlytics user id + `sign_up`, `login`, `sale_recorded` analytics |

## Step 1 — Create the project

<https://console.firebase.google.com/> → **Add project** (e.g. `rakho-app`).
Turn Google Analytics **on** (Crashlytics needs it). Stay on the **Spark**
(free) plan — nothing in this app requires Blaze.

## Step 2 — Register both application IDs

| Build | Application ID |
|---|---|
| Release | `com.lipon.rakho` |
| Debug (Android Studio) | `com.lipon.rakho.debug` |

Create two Android app entries. The debug suffix comes from
`applicationIdSuffix` in `app/build.gradle.kts`; registering only the release
ID fails with `No matching client found for package name`.

## Step 3 — Drop in the config

Download `google-services.json` to `android/app/google-services.json`. It is
git-ignored (`**/google-services.json`); CI injects it from a repository
secret. The next build applies the plugins automatically.

## Step 4 — Enable the products

1. **Authentication → Sign-in method → Email/Password → Enable.** That is the
   only provider the app uses.
   *Phone OTP is deliberately not enabled:* turning it on in the console
   requires upgrading to the paid Blaze plan, which breaks the lifetime-free
   rule. The sign-in code keeps a phone scaffold for later, but nothing ships
   that can hit a paywall.
2. **Firestore Database → Create database** — start in **production mode**
   and apply the rules from step 5 immediately. Region: `asia-south1` (Mumbai)
   is closest to Bangladesh.
3. **Crashlytics → Enable** (the Gradle plugin is already applied).
4. **Analytics** is on from project creation.

## Step 5 — Firestore security rules (paste as-is)

Every document lives under `pharmacies/{uid}` where `uid` is the shop's own
Auth uid, so the rule is simply: *you can only touch your own subtree.*

```
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    match /pharmacies/{uid}/{document=**} {
      allow read, write: if request.auth != null && request.auth.uid == uid;
    }
  }
}
```

No collection is public, no role logic is needed, and an account deletion
(`Settings → Delete account`) can wipe exactly what it owns.

**Lock the API key down too** (Google Cloud console → APIs & Credentials):
application restriction = Android apps with both package names + their SHA-1
fingerprints; API restriction = Firebase APIs only. The key ships inside the
APK by design and grants no data access without a signed-in account, but an
unrestricted key lets strangers burn your free quota.

## Step 6 — Build and verify

```bash
cd android
./gradlew :app:assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

Checklist:

1. The app opens on **Sign in** — create an account with email + password.
2. The dashboard loads; **Settings** shows the signed-in email.
3. Add a medicine, sell one line. In the Firebase console, **Firestore →
   `pharmacies/{uid}/…`** must show the documents.
4. Airplane mode → another sale → "Saving" banner → reconnect → the write
   replays by itself and the banner settles to **Synced**.
5. Second device, same account → the shop's data appears within seconds.
6. **Settings → Delete account and data** → Firestore subtree is emptied and
   the auth account is gone.

## Data model (for the console browser)

```
pharmacies/{uid}
  profile                  — name, phone, address, currency
  medicines/{id}           — brand, generic, strength, price (paisa), stock total
  batches/{id}             — expiry, costs, quantityAvailable (decremented per sale)
  sales/{id}               — invoice, lines with FEFO allocations, payment, discount
  dues/{id}                — append-only credit ledger (+due / −payment), keyed by name
  purchases/{id}           — supplier, items, receivedAt
  expenses/{id}            — category, amount paisa, note
  customers/{id}           — name, phone — the baki reminder phone book
```

Money is always integer **paisa** (`*Paisa` fields), dates are ISO strings or
epoch millis. The client derives dashboard, alerts and dues aging — no
server-side aggregation, which keeps reads inside the free quota.

## Free-plan discipline (why this never hits a wall)

- One shared listener per collection, not per screen (`FirestoreData`).
- Read-modify-write uses `Source.CACHE`; the server is never polled.
- Dashboard/alerts/dues math runs on device from data already in memory.
- Analytics events are a handful per day; Crashlytics is free at this scale.
- WhatsApp baki reminders cost nothing: the message is composed on-device and
  handed to WhatsApp through a share intent — no SMS gateway, no API.

## Privacy & terms pages

`Settings → Support` still links to pages hosted on the **old** Django
backend (`rakho-api.onrender.com`). Before that backend is taken down, copy
the two pages to **Firebase Hosting** (free tier) and update `PRIVACY_URL` /
`TERMS_URL` in `feature/settings/SettingsScreen.kt`. Play Store listing links
must move at the same time.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `No matching client found for package name …` | That application ID is not registered — step 2, both. |
| Sign-up fails with "invalid email address" on old devices | Firebase requires `firebase-auth` Play services integrity; check the device has Google Play services. |
| Writes never sync | Firestore rules not applied (step 5), or the device is offline — the queue is durable, it flushes on reconnect. |
| Second device shows old data | Firestore listeners reconnect within seconds; pull to refresh. |
| Build fails "google-services.json is missing" | Something applied the plugin unconditionally; `app/build.gradle.kts` decides, alone. |
