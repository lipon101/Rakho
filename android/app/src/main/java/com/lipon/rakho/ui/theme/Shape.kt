package com.lipon.rakho.ui.theme

import androidx.compose.ui.unit.dp

/*
 * Spacing, radius and control-size tokens.
 *
 * Scale from the brief: 4 / 8 / 12 / 16 / 24. Radii: 12 for cards, 8 for
 * chips. Controls: primary actions 56dp tall, every touch target >= 48dp.
 * The previous theme shipped 20dp cards, pill chips and 50/52/54dp buttons
 * depending on the screen — this file is what ends that.
 */

object Spacing {
    val xs = 4.dp
    val sm = 8.dp
    val md = 12.dp
    val lg = 16.dp
    val xl = 24.dp
    /** Alias of the top of the scale; screens already call this for bottom
     *  padding, and the brief's scale deliberately ends at 24. */
    val xxl = 24.dp
}

object Radii {
    val card = 12.dp
    val chip = 8.dp
    val button = 12.dp
    val sheet = 16.dp
}

object Sizes {
    /** Primary actions: one thumb, no aiming. */
    val primaryButtonHeight = 56.dp
    /** Floor for anything tappable. */
    val minTouchTarget = 48.dp
    /** The signature Expiry Strip down each medicine row's left edge. */
    val expiryStripWidth = 4.dp
}
