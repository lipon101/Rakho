package com.lipon.rakho.ui.components

import androidx.compose.animation.animateContentSize
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Schedule
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.lipon.rakho.R
import com.lipon.rakho.core.money.Money
import com.lipon.rakho.core.money.MoneyFormat
import com.lipon.rakho.core.time.DhakaTime
import com.lipon.rakho.core.time.ExpiryStatus
import com.lipon.rakho.data.repo.SyncPhase
import com.lipon.rakho.data.repo.SyncStatus
import com.lipon.rakho.ui.theme.Radii
import com.lipon.rakho.ui.theme.Sizes
import com.lipon.rakho.ui.theme.Spacing
import com.lipon.rakho.ui.theme.expiryInk
import com.lipon.rakho.ui.theme.expiryStripColor
import com.lipon.rakho.ui.theme.statusExpiredText
import com.lipon.rakho.ui.theme.statusNearText
import com.lipon.rakho.ui.theme.statusSafeText
import java.time.Instant
import java.time.format.DateTimeFormatter

/** "Today 14:32" / "18 Sep 09:05" — always in Dhaka time, like the shop's clock. */
@Composable
private fun relativeSyncTime(millis: Long): String {
    val dateTime = Instant.ofEpochMilli(millis).atZone(DhakaTime.ZONE)
    val today = DhakaTime.today()
    val date = dateTime.toLocalDate()
    val time = dateTime.format(DateTimeFormatter.ofPattern("HH:mm"))
    return if (date == today) {
        stringResource(R.string.sync_time_today, time)
    } else {
        "${date.format(DateTimeFormatter.ofPattern("dd MMM"))}, $time"
    }
}

@Composable
fun MoneyText(
    money: Money,
    modifier: Modifier = Modifier,
    style: androidx.compose.ui.text.TextStyle = MaterialTheme.typography.titleLarge,
    color: Color = MaterialTheme.colorScheme.onSurface,
    withDecimals: Boolean = true,
) {
    Text(
        text = MoneyFormat.format(money, withDecimals = withDecimals),
        modifier = modifier,
        style = style,
        color = color,
    )
}

@Composable
fun SectionHeader(
    title: String,
    modifier: Modifier = Modifier,
    action: (@Composable () -> Unit)? = null,
) {
    Row(
        modifier = modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        // A brand rule at the head and a hairline running to the action. A bare
        // title floating above a list read as unfinished, and because this
        // component fronts every list in the app, that flatness was the house
        // style rather than one screen's problem.
        Box(
            modifier = Modifier
                .size(width = 4.dp, height = 16.dp)
                .clip(RoundedCornerShape(2.dp))
                .background(MaterialTheme.colorScheme.primary),
        )
        Spacer(Modifier.width(Spacing.sm))
        Text(
            text = title,
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.SemiBold,
            color = MaterialTheme.colorScheme.onSurface,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        Spacer(Modifier.width(Spacing.md))
        HorizontalDivider(
            modifier = Modifier.weight(1f),
            thickness = 1.dp,
            color = MaterialTheme.colorScheme.outlineVariant,
        )
        if (action != null) {
            Spacer(Modifier.width(Spacing.md))
            action()
        }
    }
}

/**
 * What a number means, not just how important it is.
 *
 * The old boolean pushed anything highlighted into the teal tertiary
 * container, which painted "2 low stock" green — a shop reads green as
 * "fine", so low stock silently looked healthy. Semantics now come from the
 * design system's status palette: amber for "needs a look", red for
 * "already wrong", and neutral for facts that are simply facts.
 */
enum class KpiTone { NEUTRAL, WARNING, DANGER, PROFIT }

/** Compact metric tile used across the dashboard and reports. */
@Composable
fun KpiTile(
    label: String,
    value: String,
    modifier: Modifier = Modifier,
    icon: ImageVector? = null,
    tone: KpiTone = KpiTone.NEUTRAL,
    hint: String? = null,
    /** When set, the whole tile becomes a tap target (dashboard KPIs deep-link). */
    onClick: (() -> Unit)? = null,
) {
    // One white card for every metric. The state lives in the ink, not in a
    // filled background: a pale amber slab stretched across half the dashboard
    // read as an alert box rather than as a number. Equal height inside a row
    // is the caller's job (see the IntrinsicSize rows on the dashboard), so a
    // tile without a footnote stays compact instead of carrying dead space.
    val labelInk = when (tone) {
        KpiTone.NEUTRAL -> MaterialTheme.colorScheme.onSurfaceVariant
        KpiTone.WARNING -> statusNearText()
        KpiTone.DANGER -> statusExpiredText()
        KpiTone.PROFIT -> statusSafeText()
    }
    Surface(
        modifier = modifier.then(
            if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier,
        ),
        shape = RoundedCornerShape(Radii.card),
        color = MaterialTheme.colorScheme.surface,
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
    ) {
        Column(modifier = Modifier.padding(Spacing.lg)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                if (icon != null) {
                    Icon(
                        imageVector = icon,
                        contentDescription = null,
                        tint = labelInk,
                        modifier = Modifier.size(16.dp),
                    )
                    Spacer(Modifier.width(Spacing.sm))
                }
                Text(
                    text = label,
                    style = MaterialTheme.typography.labelMedium,
                    color = labelInk,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f),
                )
                if (onClick != null) {
                    Icon(
                        imageVector = Icons.Filled.ChevronRight,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.outline,
                        modifier = Modifier.size(16.dp),
                    )
                }
            }
            Spacer(Modifier.height(Spacing.sm))
            // The number stays on the highest-contrast ink in the system: a key
            // figure is a promise of 7:1 and status colours only reach ~6:1.
            Text(
                text = value,
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.Bold,
                color = MaterialTheme.colorScheme.onSurface,
                maxLines = 1,
            )
            if (hint != null) {
                Spacer(Modifier.height(Spacing.xs))
                Text(
                    text = hint,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
    }
}

/**
 * Large tappable action used in the dashboard grid.
 *
 * Every tile is styled identically: same tinted glyph chip, same card, same
 * border. A solid-primary lead tile was tried and pulled — one deep-green
 * glyph sitting among three tinted ones read as a different component, not as
 * a statement of priority. Hierarchy comes from position instead: the primary
 * action is always first in reading order.
 */
@Composable
fun QuickActionCard(
    title: String,
    subtitle: String,
    icon: ImageVector,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Surface(
        modifier = modifier.height(Sizes.quickActionHeight),
        shape = RoundedCornerShape(Radii.card),
        color = MaterialTheme.colorScheme.surface,
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
        onClick = onClick,
    ) {
        Column(
            modifier = Modifier.padding(Spacing.lg),
            verticalArrangement = Arrangement.Center,
        ) {
            Box(
                modifier = Modifier
                    .size(40.dp)
                    .clip(RoundedCornerShape(Radii.card))
                    .background(MaterialTheme.colorScheme.primaryContainer),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    imageVector = icon,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.onPrimaryContainer,
                    modifier = Modifier.size(22.dp),
                )
            }
            Spacer(Modifier.height(Spacing.sm))
            Text(
                text = title,
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.SemiBold,
                color = MaterialTheme.colorScheme.onSurface,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                text = subtitle,
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

/**
 * The app's one filter-chip look: quiet at rest, brand-tinted when selected.
 * Material's default selected state is secondary (blue), which fought the
 * teal identity on four screens — this wrapper ends that split.
 */
@Composable
fun RakhoFilterChip(
    selected: Boolean,
    onClick: () -> Unit,
    label: String,
    modifier: Modifier = Modifier,
) {
    FilterChip(
        selected = selected,
        onClick = onClick,
        modifier = modifier,
        label = { Text(label) },
        colors = FilterChipDefaults.filterChipColors(
            containerColor = MaterialTheme.colorScheme.surface,
            labelColor = MaterialTheme.colorScheme.onSurfaceVariant,
            selectedContainerColor = MaterialTheme.colorScheme.primaryContainer,
            selectedLabelColor = MaterialTheme.colorScheme.onPrimaryContainer,
        ),
    )
}

/** Sync/offline banner: tells the pharmacist plainly whether work is saved. */
@Composable
fun SyncBanner(status: SyncStatus, modifier: Modifier = Modifier) {
    // First boot has no sync history — show nothing rather than a "not
    // synced" banner that raises a question with no answer.
    if (status.phase != SyncPhase.SYNCING &&
        status.phase != SyncPhase.OFFLINE &&
        status.phase != SyncPhase.ERROR &&
        status.lastSyncAtMillis == 0L
    ) {
        return
    }
    val (label, container, content) = when {
        status.phase == SyncPhase.SYNCING -> Triple(
            stringResource(R.string.dashboard_syncing),
            MaterialTheme.colorScheme.surfaceVariant,
            MaterialTheme.colorScheme.onSurfaceVariant,
        )
        status.phase == SyncPhase.OFFLINE -> Triple(
            stringResource(R.string.dashboard_offline),
            MaterialTheme.colorScheme.tertiaryContainer,
            MaterialTheme.colorScheme.onTertiaryContainer,
        )
        status.phase == SyncPhase.ERROR -> Triple(
            stringResource(R.string.dashboard_sync_failed),
            MaterialTheme.colorScheme.errorContainer,
            MaterialTheme.colorScheme.onErrorContainer,
        )
        else -> Triple(
            stringResource(
                R.string.dashboard_last_synced,
                relativeSyncTime(status.lastSyncAtMillis),
            ),
            MaterialTheme.colorScheme.surfaceVariant,
            MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
    Surface(
        modifier = modifier.fillMaxWidth(),
        shape = RoundedCornerShape(Radii.chip),
        color = container,
    ) {
        Row(
            modifier = Modifier.padding(horizontal = Spacing.lg, vertical = Spacing.sm),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Text(
                text = label,
                style = MaterialTheme.typography.labelMedium,
                color = content,
            )
            if (status.pendingCount > 0) {
                Text(
                    text = stringResource(R.string.settings_pending_ops, status.pendingCount),
                    style = MaterialTheme.typography.labelMedium,
                    color = content,
                    fontWeight = FontWeight.SemiBold,
                )
            }
        }
    }
}

@Composable
fun StatCard(
    label: String,
    value: String,
    modifier: Modifier = Modifier,
    icon: ImageVector? = null,
    accent: Color = MaterialTheme.colorScheme.primary,
) {
    Surface(
        modifier = modifier,
        shape = RoundedCornerShape(Radii.card),
        color = MaterialTheme.colorScheme.surface,
        tonalElevation = 1.dp,
    ) {
        Column(modifier = Modifier.padding(Spacing.lg)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                if (icon != null) {
                    Icon(
                        imageVector = icon,
                        contentDescription = null,
                        tint = accent,
                        modifier = Modifier.size(18.dp),
                    )
                    Spacer(Modifier.width(Spacing.sm))
                }
                Text(
                    text = label,
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Spacer(Modifier.height(Spacing.sm))
            Text(
                text = value,
                style = MaterialTheme.typography.headlineSmall,
                color = MaterialTheme.colorScheme.onSurface,
                fontWeight = FontWeight.Bold,
            )
        }
    }
}

@Composable
fun EmptyState(
    title: String,
    body: String,
    icon: ImageVector? = null,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(Spacing.xl),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        if (icon != null) {
            Box(
                modifier = Modifier
                    .size(72.dp)
                    .clip(RoundedCornerShape(Radii.badge))
                    .background(MaterialTheme.colorScheme.primaryContainer),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    imageVector = icon,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.onPrimaryContainer,
                    modifier = Modifier.size(32.dp),
                )
            }
            Spacer(Modifier.height(Spacing.lg))
        }
        Text(
            text = title,
            style = MaterialTheme.typography.titleMedium,
            textAlign = TextAlign.Center,
            color = MaterialTheme.colorScheme.onSurface,
        )
        Spacer(Modifier.height(Spacing.xs))
        Text(
            text = body,
            style = MaterialTheme.typography.bodyMedium,
            textAlign = TextAlign.Center,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
fun ErrorState(
    message: String,
    onRetry: (() -> Unit)? = null,
    retryLabel: String,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier.fillMaxWidth().padding(Spacing.xl),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(
            text = message,
            style = MaterialTheme.typography.bodyLarge,
            color = MaterialTheme.colorScheme.error,
            textAlign = TextAlign.Center,
        )
        if (onRetry != null) {
            Spacer(Modifier.height(Spacing.sm))
            TextButton(onClick = onRetry) { Text(retryLabel) }
        }
    }
}

@Composable
fun LoadingState(modifier: Modifier = Modifier) {
    Box(modifier = modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        CircularProgressIndicator()
    }
}

/**
 * The signature Expiry Strip: a 4dp brand bar down the left edge of a
 * medicine row, so stock reads at a glance while scrolling.
 */
@Composable
fun ExpiryStrip(modifier: Modifier = Modifier) {
    Box(
        modifier = modifier
            .width(Sizes.expiryStripWidth)
            .fillMaxHeight()
            .background(MaterialTheme.colorScheme.tertiary),
    )
}

/**
 * The Expiry Strip in the status it marks: green safe, amber near-expiry,
 * red expired or expiring today. The label + icon come from
 * [ExpiryStatusPill] beside it, so colour is never the only signal.
 */
@Composable
fun StatusExpiryStrip(status: ExpiryStatus, modifier: Modifier = Modifier) {
    Box(
        modifier = modifier
            .width(Sizes.expiryStripWidth)
            .fillMaxHeight()
            .background(expiryStripColor(status)),
    )
}

/**
 * The one expiry chip: same label rules, same palette, same icon pairing on
 * Stock, POS, Dashboard and Dues. A status label is never colour alone.
 */
@Composable
fun ExpiryStatusPill(
    status: ExpiryStatus,
    daysUntilExpiry: Long,
    modifier: Modifier = Modifier,
) {
    val label = when {
        status == ExpiryStatus.EXPIRED ->
            stringResource(R.string.stock_expired_days, -daysUntilExpiry)
        daysUntilExpiry == 0L -> stringResource(R.string.stock_expires_today)
        else -> stringResource(R.string.stock_expires_in, daysUntilExpiry)
    }
    val (container, content) = expiryInk(status)
    val icon = when (status) {
        ExpiryStatus.EXPIRED, ExpiryStatus.EXPIRES_TODAY -> Icons.Filled.Warning
        ExpiryStatus.EXPIRING_SOON -> Icons.Filled.Schedule
        ExpiryStatus.HEALTHY -> Icons.Filled.CheckCircle
    }
    StatusPill(
        text = label,
        containerColor = container,
        contentColor = content,
        modifier = modifier,
        icon = icon,
    )
}

/**
 * Status chip. The design system's rule is that a status colour is never the
 * only signal, so the tint always travels with a written label and an icon.
 */
@Composable
fun StatusPill(
    text: String,
    containerColor: Color,
    contentColor: Color,
    modifier: Modifier = Modifier,
    icon: ImageVector? = null,
) {
    Surface(
        modifier = modifier,
        shape = RoundedCornerShape(Radii.chip),
        color = containerColor,
    ) {
        Row(
            modifier = Modifier
                .padding(horizontal = Spacing.md, vertical = Spacing.xs)
                .animateContentSize(),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (icon != null) {
                Icon(
                    imageVector = icon,
                    contentDescription = null,
                    tint = contentColor,
                    modifier = Modifier.size(16.dp),
                )
                Spacer(Modifier.width(Spacing.xs))
            }
            Text(
                text = text,
                style = MaterialTheme.typography.labelSmall,
                color = contentColor,
                // Always one line. A squeezed pill used to break its label
                // one character per line ("22 / da / ys / lef / t"); ellipsis
                // is ugly but legible, and legible wins at a crowded counter.
                maxLines = 1,
                softWrap = false,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

@Composable
fun KeyValueRow(
    label: String,
    value: String,
    modifier: Modifier = Modifier,
    valueColor: Color = MaterialTheme.colorScheme.onSurface,
) {
    Row(
        modifier = modifier.fillMaxWidth().padding(vertical = Spacing.xs),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Text(
            text = value,
            style = MaterialTheme.typography.bodyMedium,
            fontWeight = FontWeight.SemiBold,
            color = valueColor,
        )
    }
}
/**
 * One surface holding a run of related rows — the spine of a settings screen.
 *
 * Rows share a card instead of floating as individual tiles, so a screen with
 * eight options reads as three calm groups rather than eight little boxes.
 */
@Composable
fun GroupCard(
    modifier: Modifier = Modifier,
    color: Color = MaterialTheme.colorScheme.surface,
    content: @Composable ColumnScope.() -> Unit,
) {
    Surface(
        modifier = modifier.fillMaxWidth(),
        shape = RoundedCornerShape(Radii.card),
        color = color,
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
    ) {
        Column(content = content)
    }
}

/** Hairline between rows inside a [GroupCard], inset to line up with row text. */
@Composable
fun GroupDivider(startIndent: Dp = Spacing.xl) {
    HorizontalDivider(
        modifier = Modifier.padding(start = startIndent),
        color = MaterialTheme.colorScheme.outlineVariant,
    )
}

/** Compact heading above a [GroupCard]; 14sp is the floor, so this is it. */
@Composable
fun SectionLabel(text: String, modifier: Modifier = Modifier) {
    Text(
        text = text,
        style = MaterialTheme.typography.labelMedium,
        letterSpacing = 0.6.sp,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        maxLines = 1,
        overflow = TextOverflow.Ellipsis,
        modifier = modifier.fillMaxWidth().padding(top = Spacing.sm, bottom = Spacing.xs),
    )
}

/**
 * The settings row: icon tile, one-line title, optional one-line subtitle,
 * then a trailing control (or a chevron when the row is tappable).
 *
 * Subtitles are single line and ellipsised on purpose — a settings screen is
 * scanned, not read, and wrapping rows are what made the old one feel noisy.
 */
@Composable
fun SettingsRow(
    title: String,
    modifier: Modifier = Modifier,
    icon: ImageVector? = null,
    subtitle: String? = null,
    onClick: (() -> Unit)? = null,
    trailing: @Composable (() -> Unit)? = null,
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier)
            .padding(Spacing.lg),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (icon != null) {
            Box(
                modifier = Modifier
                    .size(36.dp)
                    .clip(RoundedCornerShape(Radii.chip))
                    .background(MaterialTheme.colorScheme.primaryContainer),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    imageVector = icon,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.onPrimaryContainer,
                    modifier = Modifier.size(18.dp),
                )
            }
            Spacer(Modifier.width(Spacing.md))
        }
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = title,
                style = MaterialTheme.typography.bodyLarge,
                fontWeight = FontWeight.Medium,
                color = MaterialTheme.colorScheme.onSurface,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            if (subtitle != null) {
                Text(
                    text = subtitle,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
        when {
            trailing != null -> {
                Spacer(Modifier.width(Spacing.sm))
                trailing()
            }
            onClick != null -> {
                Spacer(Modifier.width(Spacing.sm))
                Icon(
                    imageVector = Icons.Filled.ChevronRight,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.outline,
                )
            }
        }
    }
}

/**
 * The one search field for the whole app — New Sale, Stock, Receive and Add
 * medicine all share it, so the search bar is the same compact, responsive
 * premium control everywhere instead of four different-sized text fields.
 *
 * Fixed 52dp height with a soft filled container (never the tall outlined
 * box), search glyph, single-line input with Search IME action, and a
 * one-tap clear button that appears the moment there is text.
 */
@Composable
fun RakhoSearchField(
    value: String,
    onValueChange: (String) -> Unit,
    hint: String,
    modifier: Modifier = Modifier,
) {
    androidx.compose.material3.TextField(
        value = value,
        onValueChange = onValueChange,
        modifier = modifier
            .fillMaxWidth()
            .height(52.dp)
            .clip(RoundedCornerShape(14.dp)),
        placeholder = {
            Text(
                text = hint,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                style = MaterialTheme.typography.bodyMedium,
            )
        },
        leadingIcon = {
            Icon(
                imageVector = Icons.Filled.Search,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.size(20.dp),
            )
        },
        trailingIcon = {
            if (value.isNotEmpty()) {
                androidx.compose.material3.IconButton(onClick = { onValueChange("") }) {
                    Icon(
                        imageVector = Icons.Filled.Close,
                        contentDescription = stringResource(R.string.cd_close),
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.size(20.dp),
                    )
                }
            }
        },
        singleLine = true,
        textStyle = MaterialTheme.typography.bodyMedium,
        shape = RoundedCornerShape(14.dp),
        colors = androidx.compose.material3.TextFieldDefaults.colors(
            focusedContainerColor = MaterialTheme.colorScheme.surfaceContainerHigh,
            unfocusedContainerColor = MaterialTheme.colorScheme.surfaceContainerHigh,
            disabledContainerColor = MaterialTheme.colorScheme.surfaceContainerHigh,
            focusedIndicatorColor = Color.Transparent,
            unfocusedIndicatorColor = Color.Transparent,
            disabledIndicatorColor = Color.Transparent,
        ),
        keyboardOptions = androidx.compose.foundation.text.KeyboardOptions(
            imeAction = androidx.compose.ui.text.input.ImeAction.Search,
        ),
    )
}

/**
 * Minimal premium range switch: 1H · 24H · 7D · 30D · 1Y in one slim
 * segmented bar. The active segment wears the brand fill with a springy
 * press; the rest sit quietly on the glass bar — no chips, no clutter.
 */
@Composable
fun SalesRangePicker(
    selected: com.lipon.rakho.core.time.SalesRange,
    onSelect: (com.lipon.rakho.core.time.SalesRange) -> Unit,
    modifier: Modifier = Modifier,
) {
    val ranges = listOf(
        com.lipon.rakho.core.time.SalesRange.LAST_1H to stringResource(R.string.range_1h),
        com.lipon.rakho.core.time.SalesRange.LAST_24H to stringResource(R.string.range_24h),
        com.lipon.rakho.core.time.SalesRange.LAST_7D to stringResource(R.string.range_7d),
        com.lipon.rakho.core.time.SalesRange.LAST_30D to stringResource(R.string.range_30d),
        com.lipon.rakho.core.time.SalesRange.LAST_1Y to stringResource(R.string.range_1y),
    )
    Surface(
        shape = RoundedCornerShape(16.dp),
        color = MaterialTheme.colorScheme.surfaceContainerHigh,
        modifier = modifier.fillMaxWidth(),
    ) {
        Row(
            modifier = Modifier.padding(4.dp),
            horizontalArrangement = Arrangement.spacedBy(2.dp),
        ) {
            ranges.forEach { (range, label) ->
                val isSelected = range == selected
                Box(
                    modifier = Modifier
                        .weight(1f)
                        .clip(RoundedCornerShape(12.dp))
                        .background(
                            if (isSelected) {
                                MaterialTheme.colorScheme.primary
                            } else {
                                Color.Transparent
                            },
                        )
                        .clickable(onClick = { onSelect(range) })
                        .padding(vertical = 8.dp),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(
                        text = label,
                        style = MaterialTheme.typography.labelLarge,
                        fontWeight = if (isSelected) FontWeight.Bold else FontWeight.Medium,
                        color = if (isSelected) {
                            MaterialTheme.colorScheme.onPrimary
                        } else {
                            MaterialTheme.colorScheme.onSurfaceVariant
                        },
                        maxLines = 1,
                    )
                }
            }
        }
    }
}

