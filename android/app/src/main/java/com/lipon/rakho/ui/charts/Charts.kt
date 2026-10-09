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
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
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
 * Modern smooth-curve area chart: a flowing line with a soft gradient fill
 * underneath, a glowing dot on the latest value, and slim axis labels.
 * Used for the home pulse and every Reports range — one premium chart
 * language across the whole app, never bars.
 *
 * Long ranges thin their axis labels (every k-th shown, the newest always
 * shown) so 30 daily or 365 monthly buckets still read cleanly.
 */
@Composable
fun WeeklyBars(
    days: List<DayBar>,
    modifier: Modifier = Modifier,
    barColor: Color = MaterialTheme.colorScheme.primary,
    trackColor: Color = MaterialTheme.colorScheme.surfaceVariant,
    barTopRadius: Dp = 6.dp,
    maxLabels: Int = 5,
) {
    val maxPaisa = days.maxOfOrNull { it.value.paisa } ?: 0L
    val outline = trackColor
    // Always label the newest bucket; show at most maxLabels evenly spaced.
    val labelEvery = ((days.size - 1) / maxLabels).coerceAtLeast(1)
    val lineColor = barColor
    val fillTop = remember(barColor) { barColor.copy(alpha = 0.32f) }
    val fillBottom = remember(barColor) { barColor.copy(alpha = 0.02f) }

    Column(modifier = modifier.fillMaxWidth()) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(120.dp),
        ) {
            if (maxPaisa <= 0L) {
                // Empty shop: a calm baseline instead of a blank gap.
                Canvas(Modifier.fillMaxWidth().height(120.dp)) {
                    drawRoundRect(
                        color = outline,
                        topLeft = Offset(0f, size.height - 4.dp.toPx()),
                        size = Size(size.width, 4.dp.toPx()),
                        cornerRadius = CornerRadius(2.dp.toPx(), 2.dp.toPx()),
                    )
                }
            } else {
                Canvas(Modifier.fillMaxWidth().height(120.dp)) {
                    val count = days.size.coerceAtLeast(1)
                    // X spreads edge-to-edge; Y insets so the stroke never clips.
                    val padX = 6.dp.toPx()
                    val padTop = 10.dp.toPx()
                    val padBottom = 8.dp.toPx()
                    val usableW = (size.width - padX * 2).coerceAtLeast(1f)
                    val usableH = (size.height - padTop - padBottom).coerceAtLeast(1f)
                    fun xAt(index: Int): Float =
                        if (count == 1) padX + usableW / 2f
                        else padX + usableW * index / (count - 1)
                    fun yAt(paisa: Long): Float {
                        val fraction = paisa.toFloat() / maxPaisa
                        return padTop + usableH * (1f - fraction.coerceIn(0.04f, 1f))
                    }
                    val points = days.mapIndexed { index, day ->
                        Offset(xAt(index), yAt(day.value.paisa))
                    }
                    // Catmull-Rom → Bézier smoothing: a flowing curve, not zigzag.
                    val line = Path().apply {
                        if (points.isNotEmpty()) {
                            moveTo(points.first().x, points.first().y)
                            if (points.size == 1) {
                                lineTo(points.first().x + 1f, points.first().y)
                            } else {
                                for (i in 0 until points.size - 1) {
                                    val p0 = points.getOrElse(i - 1) { points[i] }
                                    val p1 = points[i]
                                    val p2 = points[i + 1]
                                    val p3 = points.getOrElse(i + 2) { p2 }
                                    val c1x = p1.x + (p2.x - p0.x) / 6f
                                    val c1y = p1.y + (p2.y - p0.y) / 6f
                                    val c2x = p2.x - (p3.x - p1.x) / 6f
                                    val c2y = p2.y - (p3.y - p1.y) / 6f
                                    cubicTo(c1x, c1y, c2x, c2y, p2.x, p2.y)
                                }
                            }
                        }
                    }
                    val baseline = size.height - 2.dp.toPx()
                    val fill = Path().apply {
                        addPath(line)
                        if (points.isNotEmpty()) {
                            lineTo(points.last().x, baseline)
                            lineTo(points.first().x, baseline)
                            close()
                        }
                    }
                    drawPath(
                        path = fill,
                        brush = Brush.verticalGradient(
                            colors = listOf(fillTop, fillBottom),
                            startY = padTop,
                            endY = baseline,
                        ),
                    )
                    drawPath(
                        path = line,
                        color = lineColor,
                        style = Stroke(width = 2.5.dp.toPx(), cap = StrokeCap.Round),
                    )
                    // Glowing dot on the latest value — the eye lands on now.
                    points.lastOrNull()?.let { last ->
                        drawCircle(
                            color = lineColor.copy(alpha = 0.22f),
                            radius = 8.dp.toPx(),
                            center = last,
                        )
                        drawCircle(color = lineColor, radius = 4.dp.toPx(), center = last)
                        drawCircle(
                            color = Color.White,
                            radius = 1.6.dp.toPx(),
                            center = last,
                        )
                    }
                }
            }
        }
        Spacer(Modifier.height(Spacing.xs))
        Row(modifier = Modifier.fillMaxWidth()) {
            days.forEachIndexed { index, day ->
                val showLabel = index == days.lastIndex || index % labelEvery == 0
                Text(
                    text = if (showLabel) day.label else "",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    fontWeight = FontWeight.Medium,
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
