package com.lipon.rakho.ui.theme

import android.app.Activity
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.SideEffect
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalView
import androidx.core.view.WindowCompat

/**
 * Rakho theme — brand: calm teal + trust blue on near-white, light-first.
 *
 * The palette, type and shape decisions all live in their own token files
 * (Color.kt, Type.kt, Shape.kt); this file only maps them onto Material 3
 * roles. Two mappings carry real constraints:
 *
 *  - `primary` is the DARK teal #0B7A6B, because white on the bright accent
 *    is 3.4:1 and button labels are 14sp. The bright #0F9D8A stays as
 *    `tertiary` (icons, strips) and in the status tokens.
 *  - `outline` is BorderStrong rather than the card border, so outlined
 *    fields keep a visible edge (WCAG 1.4.11); cards draw CardBorder in the
 *    components, not from `outline`.
 *
 * Dark mode is offered as a user preference (system / light / dark). The
 * [RakhoTheme] caller resolves the preference into [darkTheme]; everything
 * below the root reads it from [LocalIsDarkTheme], which status chips and
 * KPI tiles use to pick their dark-adapted ink pairs.
 */

/** Whether the current Rakho colour scheme is dark — set once by [RakhoTheme]. */
val LocalIsDarkTheme = androidx.compose.runtime.staticCompositionLocalOf { false }

private val LightColors = lightColorScheme(
    primary = BrandTealDark,
    onPrimary = Color.White,
    primaryContainer = BrandTealContainer,
    onPrimaryContainer = BrandTealContainerText,
    secondary = BrandBlue,
    onSecondary = Color.White,
    secondaryContainer = BrandBlueContainer,
    onSecondaryContainer = BrandBlueDark,
    tertiary = BrandTeal,
    onTertiary = DarkOnBrandTeal,
    tertiaryContainer = BrandTealContainer,
    onTertiaryContainer = BrandTealContainerText,
    error = StatusExpired,
    onError = Color.White,
    errorContainer = StatusExpiredContainer,
    onErrorContainer = StatusExpiredText,
    background = Background,
    onBackground = TextPrimary,
    surface = CardSurface,
    onSurface = TextPrimary,
    surfaceVariant = SurfaceMuted,
    onSurfaceVariant = TextMuted,
    surfaceContainerLowest = CardSurface,
    surfaceContainerLow = CardSurface,
    surfaceContainer = SurfaceRaised,
    surfaceContainerHigh = SurfaceMuted,
    surfaceContainerHighest = SurfaceMuted,
    outline = BorderStrong,
    outlineVariant = CardBorder,
)

private val DarkColors = darkColorScheme(
    primary = DarkBrandTeal,
    onPrimary = DarkOnBrandTeal,
    primaryContainer = DarkBrandTealContainer,
    onPrimaryContainer = DarkOnBrandTealContainer,
    secondary = DarkBrandBlue,
    onSecondary = DarkOnBrandBlue,
    secondaryContainer = DarkBrandBlueContainer,
    onSecondaryContainer = DarkOnBrandBlueContainer,
    tertiary = DarkBrandTeal,
    onTertiary = DarkOnBrandTeal,
    tertiaryContainer = DarkBrandTealContainer,
    onTertiaryContainer = DarkOnBrandTealContainer,
    error = DarkError,
    onError = DarkOnError,
    errorContainer = DarkErrorContainer,
    onErrorContainer = DarkOnErrorContainer,
    background = DarkBackground,
    onBackground = DarkTextPrimary,
    surface = DarkSurface,
    onSurface = DarkTextPrimary,
    surfaceVariant = DarkSurfaceVariant,
    onSurfaceVariant = DarkTextMuted,
    surfaceContainerLowest = DarkBackground,
    surfaceContainerLow = DarkBackground,
    surfaceContainer = DarkSurface,
    surfaceContainerHigh = DarkSurfaceHigh,
    surfaceContainerHighest = DarkSurfaceVariant,
    outline = DarkOutline,
    outlineVariant = DarkSurfaceVariant,
)

/** 12dp cards, 8dp chips — the same numbers as Radii, for bare M3 parts. */
private val RakhoShapes = Shapes(
    extraSmall = androidx.compose.foundation.shape.RoundedCornerShape(Radii.chip),
    small = androidx.compose.foundation.shape.RoundedCornerShape(Radii.chip),
    medium = androidx.compose.foundation.shape.RoundedCornerShape(Radii.card),
    large = androidx.compose.foundation.shape.RoundedCornerShape(Radii.card),
    extraLarge = androidx.compose.foundation.shape.RoundedCornerShape(Radii.sheet),
)

@Composable
fun RakhoTheme(
    darkTheme: Boolean = false,
    content: @Composable () -> Unit,
) {
    val colors = if (darkTheme) DarkColors else LightColors
    val view = LocalView.current
    if (!view.isInEditMode) {
        SideEffect {
            val window = (view.context as? Activity)?.window ?: return@SideEffect
            WindowCompat.getInsetsController(window, view).isAppearanceLightStatusBars = !darkTheme
        }
    }
    androidx.compose.runtime.CompositionLocalProvider(LocalIsDarkTheme provides darkTheme) {
        MaterialTheme(
            colorScheme = colors,
            typography = RakhoTypography,
            shapes = RakhoShapes,
            content = content,
        )
    }
}
