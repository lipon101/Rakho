package com.lipon.rakho.ui.theme

import androidx.compose.ui.graphics.Color
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Pins the contrast promises documented in Color.kt and docs/design-system.md.
 *
 * Each assertion carries the pair and the measured ratio, so a failing colour
 * edit says exactly what broke. Thresholds are the brief's: 4.5:1 for body
 * text, 7:1 for key numbers, 3:1 for non-text UI (WCAG 1.4.11).
 */
class ContrastTest {

    private fun assertRatio(label: String, foreground: Color, background: Color, minimum: Double) {
        val ratio = contrastRatio(foreground, background)
        assertTrue(
            "$label must be at least ${minimum}:1 but measured ${"%.2f".format(ratio)}:1",
            ratio >= minimum,
        )
    }

    @Test
    fun `text on brand fills`() {
        assertRatio("white on primary #0B7A6B", Color.White, BrandTealDark, 4.5)
        assertRatio("white on secondary #1E6FD9", Color.White, BrandBlue, 4.5)
        assertRatio("dark ink on bright teal #0F9D8A", DarkOnBrandTeal, BrandTeal, 4.5)
        assertRatio("primary text on teal container", BrandTealContainerText, BrandTealContainer, 4.5)
        assertRatio("blue dark on blue container", BrandBlueDark, BrandBlueContainer, 4.5)
    }

    @Test
    fun `body text on app surfaces`() {
        assertRatio("TextPrimary on Background", TextPrimary, Background, 4.5)
        assertRatio("TextPrimary on CardSurface", TextPrimary, CardSurface, 4.5)
        assertRatio("TextMuted on Background", TextMuted, Background, 4.5)
        assertRatio("TextMuted on SurfaceMuted", TextMuted, SurfaceMuted, 4.5)
    }

    @Test
    fun `key numbers reach seven to one`() {
        assertRatio("key number on Background", TextPrimary, Background, 7.0)
        assertRatio("key number on CardSurface", TextPrimary, CardSurface, 7.0)
    }

    @Test
    fun `status colours pair label with tint`() {
        assertRatio("safe text on safe tint", StatusSafeText, StatusSafeContainer, 4.5)
        assertRatio("near-expiry text on near tint", StatusNearText, StatusNearContainer, 4.5)
        assertRatio("expired text on expired tint", StatusExpiredText, StatusExpiredContainer, 4.5)
        assertRatio("white on expired fill (strip/badge)", Color.White, StatusExpired, 4.5)
        assertRatio("ink directly on amber", TextPrimary, StatusNear, 4.5)
    }

    @Test
    fun `non text ui keeps three to one`() {
        assertRatio("Expiry Strip teal vs card", BrandTeal, CardSurface, 3.0)
        assertRatio("interactive outline vs card", BorderStrong, CardSurface, 3.0)
        assertRatio("status safe strip vs card", StatusSafe, CardSurface, 3.0)
        assertRatio("status expired strip vs card", StatusExpired, CardSurface, 3.0)
    }

    @Test
    fun `dark scheme stays legible`() {
        assertRatio("dark primary text on dark background", DarkTextPrimary, DarkBackground, 4.5)
        assertRatio("dark muted on dark surface", DarkTextMuted, DarkSurfaceVariant, 4.5)
        assertRatio("ink on dark brand teal", DarkOnBrandTeal, DarkBrandTeal, 4.5)
    }
}
