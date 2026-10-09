package com.lipon.rakho.ui.theme

import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import com.lipon.rakho.core.time.ExpiryStatus

/**
 * Status inks that follow the active scheme.
 *
 * The light palette's pale tints glare on a dark surface and the light-status
 * browns vanish on it, so every screen picks its status colours through these
 * helpers instead of grabbing a token directly. Same semantics in both
 * schemes: green safe, amber near-expiry, red expired — always label + icon
 * alongside colour.
 */

@Composable
fun statusSafeText(): Color =
    if (LocalIsDarkTheme.current) DarkStatusSafeText else StatusSafeText

@Composable
fun statusSafeContainer(): Color =
    if (LocalIsDarkTheme.current) DarkStatusSafeContainer else StatusSafeContainer

@Composable
fun statusNearText(): Color =
    if (LocalIsDarkTheme.current) DarkStatusNearText else StatusNearText

@Composable
fun statusNearContainer(): Color =
    if (LocalIsDarkTheme.current) DarkStatusNearContainer else StatusNearContainer

@Composable
fun statusExpiredText(): Color =
    if (LocalIsDarkTheme.current) DarkStatusExpiredText else StatusExpiredText

@Composable
fun statusExpiredContainer(): Color =
    if (LocalIsDarkTheme.current) DarkStatusExpiredContainer else StatusExpiredContainer

/** The chip pair (container, ink) for an expiry state, scheme-correct. */
@Composable
fun expiryInk(status: ExpiryStatus): Pair<Color, Color> = when (status) {
    ExpiryStatus.HEALTHY -> statusSafeContainer() to statusSafeText()
    ExpiryStatus.EXPIRING_SOON -> statusNearContainer() to statusNearText()
    // Today is the last day it can be sold — the shop reads that as danger,
    // same as expired, and both Stock and Dashboard already colour it so.
    ExpiryStatus.EXPIRED, ExpiryStatus.EXPIRES_TODAY ->
        statusExpiredContainer() to statusExpiredText()
}

/** The 4dp Expiry Strip ink for a status — graphic-only use, 3:1 floor met. */
@Composable
fun expiryStripColor(status: ExpiryStatus): Color = when (status) {
    ExpiryStatus.HEALTHY -> StatusSafe
    ExpiryStatus.EXPIRING_SOON -> StatusNear
    ExpiryStatus.EXPIRED, ExpiryStatus.EXPIRES_TODAY -> StatusExpired
}
