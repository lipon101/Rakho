package com.lipon.rakho.ui.theme

import androidx.compose.material3.Typography
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp
import com.lipon.rakho.R

/*
 * Typography tokens.
 *
 * One family does both scripts: Hind Siliguri ships Latin and Bangla in the
 * same font, so a mixed string ("৳ ১,২০০ · Save 20%") never falls back to a
 * second typeface. The four weights are subset to the glyphs the app actually
 * uses (see docs/design-system.md) — 955KB down from 1.29MB of three families.
 *
 * Scale rules:
 *   - Nothing is smaller than 14sp. Sunlight and older shopkeepers, both.
 *   - Body copy has three steps: 16 / 14 / 14-emphasis — no 11 or 12sp text.
 *   - Key numbers (Today's Risk, money) use display/headline sizes, bold.
 */

val RakhoSans = FontFamily(
    Font(R.font.hind_siliguri_regular, FontWeight.Normal),
    Font(R.font.hind_siliguri_medium, FontWeight.Medium),
    Font(R.font.hind_siliguri_semibold, FontWeight.SemiBold),
    Font(R.font.hind_siliguri_bold, FontWeight.Bold),
)

val RakhoTypography = Typography(
    // Large bold numbers: Today's Risk, hero amounts.
    displaySmall = TextStyle(
        fontFamily = RakhoSans,
        fontSize = 32.sp,
        fontWeight = FontWeight.Bold,
        lineHeight = 38.sp,
    ),
    headlineMedium = TextStyle(
        fontFamily = RakhoSans,
        fontSize = 26.sp,
        fontWeight = FontWeight.Bold,
        lineHeight = 32.sp,
    ),
    headlineSmall = TextStyle(
        fontFamily = RakhoSans,
        fontSize = 22.sp,
        fontWeight = FontWeight.Bold,
        lineHeight = 28.sp,
    ),
    titleLarge = TextStyle(
        fontFamily = RakhoSans,
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
        fontSize = 14.sp,
        fontWeight = FontWeight.Normal,
        lineHeight = 19.sp,
    ),
    labelLarge = TextStyle(
        fontFamily = RakhoSans,
        fontSize = 14.sp,
        fontWeight = FontWeight.SemiBold,
        lineHeight = 18.sp,
    ),
    labelMedium = TextStyle(
        fontFamily = RakhoSans,
        fontSize = 14.sp,
        fontWeight = FontWeight.Medium,
        lineHeight = 18.sp,
    ),
    labelSmall = TextStyle(
        fontFamily = RakhoSans,
        fontSize = 14.sp,
        fontWeight = FontWeight.Medium,
        lineHeight = 18.sp,
    ),
)
