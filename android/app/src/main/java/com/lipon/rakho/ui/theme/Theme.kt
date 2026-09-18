package com.lipon.rakho.ui.theme

import android.app.Activity
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.SideEffect
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.view.WindowCompat

private val BrandTeal = Color(0xFF0E7C66)
private val BrandTealDark = Color(0xFF065F4B)
private val BrandTealLight = Color(0xFF7FD8C0)
private val AccentAmber = Color(0xFFF59E0B)
private val DangerRed = Color(0xFFDC2626)
private val SurfaceLight = Color(0xFFF6F8F8)
private val SurfaceDark = Color(0xFF0B1512)
private val SurfaceVariantDark = Color(0xFF16241F)

private val LightColors = lightColorScheme(
    primary = BrandTeal,
    onPrimary = Color.White,
    primaryContainer = Color(0xFFCCF0E4),
    onPrimaryContainer = BrandTealDark,
    secondary = BrandTealDark,
    onSecondary = Color.White,
    tertiary = AccentAmber,
    onTertiary = Color(0xFF2B1B00),
    error = DangerRed,
    onError = Color.White,
    errorContainer = Color(0xFFFFDAD6),
    onErrorContainer = Color(0xFF410002),
    background = SurfaceLight,
    onBackground = Color(0xFF111C19),
    surface = Color.White,
    onSurface = Color(0xFF111C19),
    surfaceVariant = Color(0xFFE4EBE8),
    onSurfaceVariant = Color(0xFF44514C),
    outline = Color(0xFF74847E),
)

private val DarkColors = darkColorScheme(
    primary = BrandTealLight,
    onPrimary = Color(0xFF00382C),
    primaryContainer = BrandTealDark,
    onPrimaryContainer = Color(0xFFB8F0DE),
    secondary = Color(0xFF9FD4C4),
    onSecondary = Color(0xFF0B372D),
    tertiary = AccentAmber,
    onTertiary = Color(0xFF3A2600),
    error = Color(0xFFFFB4AB),
    onError = Color(0xFF690005),
    background = SurfaceDark,
    onBackground = Color(0xFFDCE5E1),
    surface = SurfaceVariantDark,
    onSurface = Color(0xFFDCE5E1),
    surfaceVariant = Color(0xFF26332E),
    onSurfaceVariant = Color(0xFFBCCAC4),
    outline = Color(0xFF889691),
)

/** Numeric-heavy UI: tight, legible, tabular-feeling typography. */
private val RakhoTypography = Typography(
    displaySmall = TextStyle(fontSize = 34.sp, fontWeight = FontWeight.Black, lineHeight = 38.sp),
    headlineMedium = TextStyle(fontSize = 26.sp, fontWeight = FontWeight.Bold, lineHeight = 32.sp),
    headlineSmall = TextStyle(fontSize = 22.sp, fontWeight = FontWeight.Bold, lineHeight = 28.sp),
    titleLarge = TextStyle(fontSize = 19.sp, fontWeight = FontWeight.SemiBold, lineHeight = 25.sp),
    titleMedium = TextStyle(fontSize = 16.sp, fontWeight = FontWeight.SemiBold, lineHeight = 22.sp),
    bodyLarge = TextStyle(fontSize = 16.sp, fontWeight = FontWeight.Normal, lineHeight = 23.sp),
    bodyMedium = TextStyle(fontSize = 14.sp, fontWeight = FontWeight.Normal, lineHeight = 20.sp),
    labelLarge = TextStyle(fontSize = 14.sp, fontWeight = FontWeight.SemiBold, lineHeight = 18.sp),
    labelMedium = TextStyle(fontSize = 12.sp, fontWeight = FontWeight.Medium, lineHeight = 16.sp),
    labelSmall = TextStyle(fontSize = 11.sp, fontWeight = FontWeight.Medium, lineHeight = 14.sp),
)

object Spacing {
    val xs = 4.dp
    val sm = 8.dp
    val md = 12.dp
    val lg = 16.dp
    val xl = 24.dp
    val xxl = 32.dp
}

object Radii {
    val card = 20.dp
    val chip = 999.dp
    val button = 16.dp
    val sheet = 28.dp
}

@Composable
fun RakhoTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
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
    MaterialTheme(
        colorScheme = colors,
        typography = RakhoTypography,
        content = content,
    )
}
