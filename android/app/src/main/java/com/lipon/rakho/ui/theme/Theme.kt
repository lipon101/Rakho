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
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.view.WindowCompat
import com.lipon.rakho.R

/**
 * Rakho brand system — "Sepia & Midnight".
 *
 * Light  (Sepia):    warm paper tones #FBF9F4/#FAF6F0/#EFE6DB with a
 *                    polished umber accent.
 * Dark   (Midnight): pure-black OLED #070809 with the #31F6E3 cyan accent —
 *                    maximum focus for long pharmacy shifts.
 *
 * Type: Geist Sans for UI/body (plus Noto Sans Bengali so বাংলা renders in
 * brand), Libre Baskerville for display/headlines to give the product an
 * editorial, trustworthy voice.
 */

// ---- Sepia (light) ---------------------------------------------------------
private val Paper = Color(0xFFFBF9F4)
private val PaperCard = Color(0xFFFAF6F0)
private val PaperVariant = Color(0xFFEFE6DB)
private val Umber = Color(0xFF8B5E34)
private val UmberDeep = Color(0xFF4A2F17)
private val InkUmber = Color(0xFF2D2016) // oklab(0.2555 0.0130 0.0229)
private val Taupe = Color(0xFF816C5A) // oklab(0.5461 0.0185 0.0336)
private val GoldLeaf = Color(0xFF8C6D1F)

// ---- Midnight (dark) -------------------------------------------------------
private val Oled = Color(0xFF070809)
private val OledRaised = Color(0xFF0D0F10)
private val OledVariant = Color(0xFF16191B)
private val Cyan = Color(0xFF31F6E3)
private val CyanDeep = Color(0xFF0F5C54)
private val NightInk = Color(0xFFE4E9E7)
private val NightTaupe = Color(0xFF9BA6A3)

// ---- Families --------------------------------------------------------------
val RakhoSans = FontFamily(
    Font(R.font.geist_regular, FontWeight.Normal),
    Font(R.font.geist_medium, FontWeight.Medium),
    Font(R.font.geist_semibold, FontWeight.SemiBold),
    Font(R.font.geist_bold, FontWeight.Bold),
    // Per-glyph fallback: Bengali text resolves here in brand, no system font.
    Font(R.font.noto_sans_bengali_variable, FontWeight.Normal),
)

val RakhoSerif = FontFamily(
    Font(R.font.libre_baskerville_variable, FontWeight.Normal),
)

private val LightColors = lightColorScheme(
    primary = Umber,
    onPrimary = Color.White,
    primaryContainer = Color(0xFFEBDCC9),
    onPrimaryContainer = UmberDeep,
    secondary = Color(0xFF6D5C4B),
    onSecondary = Color.White,
    secondaryContainer = Color(0xFFE7DBCC),
    onSecondaryContainer = Color(0xFF3E3225),
    tertiary = GoldLeaf,
    onTertiary = Color(0xFFFFF8E7),
    tertiaryContainer = Color(0xFFF0E3C0),
    onTertiaryContainer = Color(0xFF4B3A10),
    error = Color(0xFFB3261E),
    onError = Color.White,
    errorContainer = Color(0xFFFCDAD4),
    onErrorContainer = Color(0xFF5F1310),
    background = Paper,
    onBackground = InkUmber,
    surface = PaperCard,
    onSurface = InkUmber,
    surfaceVariant = PaperVariant,
    onSurfaceVariant = Taupe,
    surfaceContainerLowest = Color(0xFFFDFBF7),
    surfaceContainerLow = Color(0xFFF8F3EB),
    surfaceContainer = Color(0xFFF5EEE5),
    surfaceContainerHigh = Color(0xFFF2EAE0),
    surfaceContainerHighest = PaperVariant,
    outline = Color(0xFFB9A896),
    outlineVariant = Color(0xFFD8CCBC),
)

private val DarkColors = darkColorScheme(
    primary = Cyan,
    onPrimary = Color(0xFF003B36),
    primaryContainer = CyanDeep,
    onPrimaryContainer = Color(0xFFB9FFF6),
    secondary = Color(0xFF7FE8DC),
    onSecondary = Color(0xFF003733),
    secondaryContainer = Color(0xFF0E4F49),
    onSecondaryContainer = Color(0xFFB0F0E8),
    tertiary = Color(0xFFFFC26B),
    onTertiary = Color(0xFF442D00),
    tertiaryContainer = Color(0xFF4A3410),
    onTertiaryContainer = Color(0xFFFFDFA8),
    error = Color(0xFFFFB4AB),
    onError = Color(0xFF690005),
    errorContainer = Color(0xFF93000A),
    onErrorContainer = Color(0xFFFFDAD6),
    background = Oled,
    onBackground = NightInk,
    surface = OledRaised,
    onSurface = NightInk,
    surfaceVariant = OledVariant,
    onSurfaceVariant = NightTaupe,
    surfaceContainerLowest = Oled,
    surfaceContainerLow = Color(0xFF0B0D0E),
    surfaceContainer = Color(0xFF101314),
    surfaceContainerHigh = Color(0xFF15181A),
    surfaceContainerHighest = Color(0xFF1B1F21),
    outline = Color(0xFF5A6562),
    outlineVariant = Color(0xFF333B39),
)

/** Display voice in serif, everything else in Geist with Bengali fallback. */
private val RakhoTypography = Typography(
    displaySmall = TextStyle(
        fontFamily = RakhoSerif,
        fontSize = 34.sp,
        fontWeight = FontWeight.Bold,
        lineHeight = 40.sp,
    ),
    headlineMedium = TextStyle(
        fontFamily = RakhoSerif,
        fontSize = 26.sp,
        fontWeight = FontWeight.Bold,
        lineHeight = 33.sp,
    ),
    headlineSmall = TextStyle(
        fontFamily = RakhoSerif,
        fontSize = 22.sp,
        fontWeight = FontWeight.Bold,
        lineHeight = 28.sp,
    ),
    titleLarge = TextStyle(
        fontFamily = RakhoSerif,
        fontSize = 20.sp,
        fontWeight = FontWeight.Bold,
        lineHeight = 26.sp,
    ),
    titleMedium = TextStyle(
        fontFamily = RakhoSans,
        fontSize = 16.sp,
        fontWeight = FontWeight.SemiBold,
        lineHeight = 22.sp,
    ),
    titleSmall = TextStyle(
        fontFamily = RakhoSans,
        fontSize = 14.sp,
        fontWeight = FontWeight.SemiBold,
        lineHeight = 19.sp,
    ),
    bodyLarge = TextStyle(
        fontFamily = RakhoSans,
        fontSize = 16.sp,
        fontWeight = FontWeight.Normal,
        lineHeight = 23.sp,
    ),
    bodyMedium = TextStyle(
        fontFamily = RakhoSans,
        fontSize = 14.sp,
        fontWeight = FontWeight.Normal,
        lineHeight = 20.sp,
    ),
    bodySmall = TextStyle(
        fontFamily = RakhoSans,
        fontSize = 12.sp,
        fontWeight = FontWeight.Normal,
        lineHeight = 17.sp,
    ),
    labelLarge = TextStyle(
        fontFamily = RakhoSans,
        fontSize = 14.sp,
        fontWeight = FontWeight.SemiBold,
        lineHeight = 18.sp,
    ),
    labelMedium = TextStyle(
        fontFamily = RakhoSans,
        fontSize = 12.sp,
        fontWeight = FontWeight.Medium,
        lineHeight = 16.sp,
    ),
    labelSmall = TextStyle(
        fontFamily = RakhoSans,
        fontSize = 11.sp,
        fontWeight = FontWeight.Medium,
        lineHeight = 14.sp,
    ),
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
