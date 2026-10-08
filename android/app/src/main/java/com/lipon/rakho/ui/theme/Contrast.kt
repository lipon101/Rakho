package com.lipon.rakho.ui.theme

import androidx.compose.ui.graphics.Color
import kotlin.math.max
import kotlin.math.min

/*
 * WCAG 2.1 contrast maths, kept as pure functions so ContrastTest can pin
 * every documented token pair. If a colour edit would make a label unreadable
 * in sunlight, the build fails instead of shipping.
 *
 * https://www.w3.org/TR/WCAG21/#relative-luminance
 * https://www.w3.org/TR/WCAG21/#contrast-ratio
 */

/** WCAG relative luminance of an sRGB colour. */
fun relativeLuminance(color: Color): Double {
    fun linearize(channel: Float): Double {
        val c = channel.toDouble()
        return if (c <= 0.03928) c / 12.92 else Math.pow((c + 0.055) / 1.055, 2.4)
    }
    return 0.2126 * linearize(color.red) +
        0.7152 * linearize(color.green) +
        0.0722 * linearize(color.blue)
}

/** Contrast ratio between two colours: 1.0 (identical) .. 21.0 (black/white). */
fun contrastRatio(a: Color, b: Color): Double {
    val la = relativeLuminance(a)
    val lb = relativeLuminance(b)
    val lighter = max(la, lb)
    val darker = min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)
}
