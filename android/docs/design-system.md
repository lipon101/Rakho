# Rakho design system

Source of truth for the Android visual identity. Tokens live in code:
`ui/theme/Color.kt`, `Type.kt`, `Shape.kt`, `Contrast.kt`; `Theme.kt` only maps
them onto Material 3. A colour literal outside `Color.kt` is a bug.

## Brand palette

| Token | Value | Role | Contrast (measured) |
|---|---|---|---|
| `BrandTeal` | `#0F9D8A` | Signature accent: Expiry Strip, icon tints, dividers. Never behind body text. | 3.4:1 with white → graphics only |
| `BrandTealDark` | `#0B7A6B` | Interactive fills: buttons, selected nav, headers | **5.2:1** with white |
| `BrandBlue` | `#1E6FD9` | Links, info, secondary actions only | **4.9:1** with white |
| `Background` | `#F7FAFA` | App background | — |
| `CardSurface` | `#FFFFFF` | Cards | **15.7:1** for `TextPrimary` |
| `CardBorder` / `SurfaceMuted` | `#E4E9EC` | Card edges, muted fills (the brief's single card/border value) | decorative |
| `BorderStrong` | `#6B7479` | Interactive outlines (fields, outlined buttons) | **4.8:1** on white (WCAG 1.4.11) |
| `TextPrimary` | `#1F2933` | Body/primary text | **14.2:1** on background |
| `TextMuted` | `#4A5964` | Labels, hints | **6.9:1** on background |

Status colours are semantic only (never decorative) and always paired with a
label and an icon — colour-blind users and sunlight both demand it:

| Status | Fill | Tint container | Text on tint |
|---|---|---|---|
| Safe | `#2E9E5B` | `#E7F4EC` | `#1E7A46` (4.8:1) |
| Near expiry (≤90 days) | `#F5A524` | `#FDF1DE` | `#8A5A00` (5.2:1) |
| Expired | `#D93025` | `#FCE9E7` | `#B3261E` (5.7:1) |

Red is only ever expired/danger; orange only ever expiry status. Neither is
ever a primary or button colour.

**Why bright teal is not a button colour:** white on `#0F9D8A` measures
3.4:1 and button labels are 14sp, so text-bearing teal surfaces use `#0B7A6B`.
Every pair above is pinned by `ContrastTest` (unit test); changing a token
below its threshold fails the build.

## Scale

- Spacing: **4 / 8 / 12 / 16 / 24** (`Spacing.xs..xl`; `xxl` aliases 24).
- Radii: **cards 12, chips 8, buttons 12, sheets 16** (`Radii`).
- Controls: primary actions **56dp**, minimum touch target **48dp**,
  Expiry Strip **4dp** (`Sizes`).
- Type: one family, **Hind Siliguri** (Latin + Bangla in one font file, so
  mixed strings never switch typefaces). Nothing below **14sp**; body steps
  are 16/14/14-emphasis; key numbers use 32/26/22 bold.

## Fonts

`res/font/hind_siliguri_{regular,medium,semibold,bold}.ttf` are subset with
fontTools to the codepoints the app actually uses (verified: every character
in `values/strings.xml`, `values-bn/strings.xml` and all Kotlin sources is
present in each weight, plus full Basic Latin, Latin-1, Bengali, punctuation
and symbol ranges). OFL license: `assets/licenses/HindSiliguri-OFL.txt`.

Measured: 955KB uncompressed / **438KB in-APK compressed**, replacing 1.29MB
uncompressed / 655KB compressed across three families (Geist, Libre
Baskerville, Noto Sans Bengali).

## Migration state (honest current picture)

Step 0 changed tokens, fonts, and the dashboard hero (its hard-coded gradient
is now a flat brand fill). Until their own steps land, screens still:

- draw rows/cards without the Expiry Strip or status-chip pattern (steps 2–3);
- map expiry states onto generic Material containers instead of `Status*`
  tokens (near-expiry shows teal-tinted today, not amber — step 3);
- use 50/52/54dp buttons and inline `RoundedCornerShape` in places (steps 1,
  4); a few `maxLines = 1` labels now render at 14sp and need a glance on a
  real device (manual test list);
- use Material system glyphs rather than the new icon set (steps 1, 7).

Dark mode: defined, brand-consistent, no neon — but `RakhoTheme` defaults to
**light** per the brief (light-first). Switching to the system setting later
is a one-line change.

## Changing a colour safely

1. Edit the token in `Color.kt`.
2. Run `./gradlew :app:testDebugUnitTest` — `ContrastTest` reports the exact
   pair and measured ratio if the change breaks a promise.
3. Update the table in this file.
