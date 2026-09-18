package com.lipon.rakho.ui.charts

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.lipon.rakho.core.money.Money
import com.lipon.rakho.core.money.MoneyFormat
import com.lipon.rakho.ui.theme.Radii
import com.lipon.rakho.ui.theme.Spacing

/**
 * Small, honest chart kit for pharmacy numbers.
 *
 * Deliberately hand-drawn on Canvas: no charting library to pull in, full
 * control of the Sepia/Midnight themes, and every chart answers one question
 * a shop owner actually has — "how is the week going?", "where does the
 * money come from?", "who has owed the longest?"
 */

/** One day of sales, already bucketed by the caller in Dhaka time. */
data class DayBar(
    val label: String,
    val value: Money,
    val highlighted: Boolean = false,
)

/**
 * Vertical bars for the last N days. Highlighted (usually "today") bars are
 * solid; the rest are tinted, so the eye lands on now without a legend.
 */
@Composable
fun WeeklyBars(
    days: List<DayBar>,
    modifier: Modifier = Modifier,
    barColor: Color = MaterialTheme.colorScheme.primary,
    trackColor: Color = MaterialTheme.colorScheme.surfaceVariant,
    barTopRadius: Dp = 6.dp,
) {
    val maxPaisa = days.maxOfOrNull { it.value.paisa } ?: 0L
    val outline = trackColor

    Column(modifier = modifier.fillMaxWidth()) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(96.dp),
        ) {
            if (maxPaisa <= 0L) {
                // Empty shop: a calm baseline instead of a blank gap.
                Canvas(Modifier.fillMaxWidth().height(96.dp)) {
                    drawRoundRect(
                        color = outline,
                        topLeft = Offset(0f, size.height - 4.dp.toPx()),
                        size = Size(size.width, 4.dp.toPx()),
                        cornerRadius = CornerRadius(2.dp.toPx(), 2.dp.toPx()),
                    )
                }
            } else {
                Canvas(Modifier.fillMaxWidth().height(96.dp)) {
                    val slot = size.width / days.size.coerceAtLeast(1)
                    // 56% of the slot is bar, the rest is breathing room.
                    val barWidth = slot * 0.56f
                    val usableHeight = size.height - 4.dp.toPx()
                    days.forEachIndexed { index, day ->
                        val fraction = day.value.paisa.toFloat() / maxPaisa
                        val barHeight = (usableHeight * fraction).coerceAtLeast(4.dp.toPx())
                        val left = slot * index + (slot - barWidth) / 2f
                        val top = size.height - barHeight
                        drawRoundRect(
                            color = if (day.highlighted) barColor else barColor.copy(alpha = 0.38f),
                            topLeft = Offset(left, top),
                            size = Size(barWidth, barHeight),
                            cornerRadius = CornerRadius(
                                barTopRadius.toPx(),
                                barTopRadius.toPx(),
                            ),
                        )
                    }
                }
            }
        }
        Spacer(Modifier.height(Spacing.xs))
        Row(modifier = Modifier.fillMaxWidth()) {
            days.forEach { day ->
                Text(
                    text = day.label,
                    style = MaterialTheme.typography.labelSmall,
                    color = if (day.highlighted) {
                        MaterialTheme.colorScheme.primary
                    } else {
                        MaterialTheme.colorScheme.onSurfaceVariant
                    },
                    fontWeight = if (day.highlighted) FontWeight.Bold else FontWeight.Medium,
                    textAlign = TextAlign.Center,
                    maxLines = 1,
                    overflow = TextOverflow.Clip,
                    modifier = Modifier.weight(1f),
                )
            }
        }
    }
}

/** One colored slice of a composition bar. */
data class Segment(
    val label: String,
    val value: Money,
    val color: Color,
)

/**
 * Horizontal 100% stacked bar showing how a total is composed (payment mix,
 * dues aging). Zero-value segments collapse; a completely empty total renders
 * as a quiet track so the layout never jumps.
 */
@Composable
fun SegmentedBar(
    segments: List<Segment>,
    modifier: Modifier = Modifier,
    trackHeight: Dp = 12.dp,
    trackColor: Color = MaterialTheme.colorScheme.surfaceVariant,
) {
    val total = segments.sumOf { it.value.paisa }.coerceAtLeast(0L)
    Canvas(modifier = modifier.fillMaxWidth().height(trackHeight)) {
        if (total <= 0L) {
            drawRoundRect(
                color = trackColor,
                cornerRadius = CornerRadius(trackHeight.toPx() / 2, trackHeight.toPx() / 2),
            )
            return@Canvas
        }
        val gap = 2.dp.toPx()
        val drawable = size.width - gap * (segments.count { it.value.paisa > 0 } - 1)
        var x = 0f
        segments.forEach { segment ->
            if (segment.value.paisa > 0) {
                val w = drawable * segment.value.paisa / total
                drawRoundRect(
                    color = segment.color,
                    topLeft = Offset(x, 0f),
                    size = Size(w, size.height),
                    cornerRadius = CornerRadius(trackHeight.toPx() / 2, trackHeight.toPx() / 2),
                )
                x += w + gap
            }
        }
    }
}

/** One legend row for a [SegmentedBar]: colored dot, label, amount. */
@Composable
fun SegmentLegendRow(segment: Segment) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Box(
            modifier = Modifier
                .padding(end = Spacing.sm)
                .width(10.dp)
                .height(10.dp)
                .clip(CircleShape)
                .background(segment.color),
        )
        Text(
            text = segment.label,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.weight(1f),
        )
        Text(
            text = MoneyFormat.format(segment.value),
            style = MaterialTheme.typography.labelLarge,
            fontWeight = FontWeight.SemiBold,
        )
    }
}

/**
 * Relative-strength bar for ranked lists (top selling items). The largest
 * item sets 100%; everyone else compares against it — instantly scannable.
 */
@Composable
fun ShareBar(
    fraction: Float,
    color: Color,
    modifier: Modifier = Modifier,
    trackColor: Color = MaterialTheme.colorScheme.surfaceVariant,
    barHeight: Dp = 8.dp,
) {
    Box(
        modifier = modifier
            .fillMaxWidth()
            .height(barHeight)
            .clip(RoundedCornerShape(Radii.chip))
            .background(trackColor),
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth(fraction.coerceIn(0.02f, 1f))
                .height(barHeight)
                .clip(RoundedCornerShape(Radii.chip))
                .background(color),
        )
    }
}

/** Row of small tinted chips used for labels like "This week". */
@Composable
fun DeltaChip(text: String, positive: Boolean, modifier: Modifier = Modifier) {
    val container = if (positive) {
        MaterialTheme.colorScheme.secondaryContainer
    } else {
        MaterialTheme.colorScheme.errorContainer
    }
    val content = if (positive) {
        MaterialTheme.colorScheme.onSecondaryContainer
    } else {
        MaterialTheme.colorScheme.onErrorContainer
    }
    Box(
        modifier = modifier
            .clip(RoundedCornerShape(Radii.chip))
            .background(container)
            .padding(horizontal = Spacing.sm, vertical = 2.dp),
    ) {
        Text(
            text = text,
            style = MaterialTheme.typography.labelSmall,
            fontWeight = FontWeight.SemiBold,
            color = content,
        )
    }
}
