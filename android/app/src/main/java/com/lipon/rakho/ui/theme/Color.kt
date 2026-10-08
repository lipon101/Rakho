package com.lipon.rakho.ui.theme

import androidx.compose.ui.graphics.Color

/*
 * Rakho colour tokens — the only file in the app that may contain a colour
 * literal. Screens read MaterialTheme.colorScheme or the status tokens below;
 * a hex value anywhere else is a bug (there is a unit test for the ratios,
 * ContrastTest, because every number here is a promise about legibility in a
 * shop doorway at midday).
 *
 * Brand rules, from the design brief:
 *   - Teal is the identity; blue is reserved for links / info / secondary.
 *   - Red is ONLY expired/danger; orange ONLY expiry status. Never decorative.
 *   - A status colour is always paired with a label and an icon, never colour
 *     alone (colour-blind users + sunlight).
 *   - Body text >= 4.5:1, key numbers >= 7:1.
 *
 * The one deliberate nuance: #0F9D8A with white text is only 3.4:1, so the
 * bright teal is the *accent* (Expiry Strip, icons, dividers) and any teal
 * surface carrying text is its dark variant #0B7A6B (5.2:1 with white).
 */

// ── Brand ──────────────────────────────────────────────────────────────────
/** Signature accent: Expiry Strip, icon tints, dividers. Never behind body text. */
val BrandTeal = Color(0xFF0F9D8A)
/** Interactive fills + headers: buttons, selected nav, top bars. White text = 5.2:1. */
val BrandTealDark = Color(0xFF0B7A6B)
/** Links, info, secondary actions only. White text = 4.9:1. */
val BrandBlue = Color(0xFF1E6FD9)
/** Blue text on the blue tinted container. 5.4:1 on BrandBlueContainer. */
val BrandBlueDark = Color(0xFF1A5CB5)

// ── Neutrals ───────────────────────────────────────────────────────────────
/** App background. */
val Background = Color(0xFFF7FAFA)
/** Cards sit on the background; text on white is 15.7:1. */
val CardSurface = Color(0xFFFFFFFF)
/** Card edges and muted fills — the brief's single "card/border" value. */
val CardBorder = Color(0xFFE4E9EC)
val SurfaceMuted = CardBorder
/** Interactive outlines (inputs, outlined buttons): 4.8:1 on white, so a field
 *  boundary stays visible in sunlight. Card edges don't need this; controls do
 *  (WCAG 1.4.11 non-text contrast). */
val BorderStrong = Color(0xFF6B7479)
/** Primary text. 14.2:1 on Background. */
val TextPrimary = Color(0xFF1F2933)
/** Secondary text: labels, hints. 6.9:1 on Background. */
val TextMuted = Color(0xFF4A5964)

// ── Status: semantic only, never decorative ────────────────────────────────
/** Stock that is fine. */
val StatusSafe = Color(0xFF2E9E5B)
val StatusSafeContainer = Color(0xFFE7F4EC)
/** Safe text on its tint — 4.8:1. */
val StatusSafeText = Color(0xFF1E7A46)

/** Expiring within the 90-day window (30–90 days in the brief's wording). */
val StatusNear = Color(0xFFF5A524)
val StatusNearContainer = Color(0xFFFDF1DE)
/** Amber is too light for white text (2.0:1); dark ink is 5.2:1. */
val StatusNearText = Color(0xFF8A5A00)

/** Expired, and only ever expired. */
val StatusExpired = Color(0xFFD93025)
val StatusExpiredContainer = Color(0xFFFCE9E7)
val StatusExpiredText = Color(0xFFB3261E)

// ── Teal/blue tints (cards, containers) ────────────────────────────────────
val BrandTealContainer = Color(0xFFE3F3F0)
/** Dark teal ink on BrandTealContainer — 8.2:1. */
val BrandTealContainerText = Color(0xFF0A4F45)
val BrandBlueContainer = Color(0xFFE6EFFC)

// ── Dark mode (kept compiling, not the shipping default) ───────────────────
// The brief says light-first: RakhoTheme defaults to light and the dark scheme
// below exists so the system toggle is a one-line change later — re-tokenised
// to the same brand, with none of the old neon cyan.
val DarkBackground = Color(0xFF101418)
val DarkSurface = Color(0xFF171C21)
val DarkSurfaceVariant = Color(0xFF1F262C)
val DarkSurfaceHigh = Color(0xFF1C2127)
val DarkTextPrimary = Color(0xFFE8EDEF)
val DarkTextMuted = Color(0xFF9FB0B8)
val DarkBrandTeal = Color(0xFF3FBFA9)
/** On DarkBrandTeal: 7.3:1. */
val DarkOnBrandTeal = Color(0xFF06231E)
val DarkBrandTealContainer = Color(0xFF0E4E45)
val DarkOnBrandTealContainer = Color(0xFFB7F0E5)
val DarkBrandBlue = Color(0xFF6FA6F0)
val DarkOnBrandBlue = Color(0xFF0A1B33)
val DarkBrandBlueContainer = Color(0xFF163A66)
val DarkOnBrandBlueContainer = Color(0xFFBBD7FA)
val DarkOutline = Color(0xFF6A757D)

/** Light surface step between white cards and the muted fill. */
val SurfaceRaised = Color(0xFFF2F5F6)
