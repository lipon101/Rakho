package bd.rakho.pharmacy.ui.components

import androidx.compose.animation.animateContentSize
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.CircularProgressIndicator
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
import androidx.compose.ui.unit.dp
import bd.rakho.pharmacy.R
import bd.rakho.pharmacy.core.money.Money
import bd.rakho.pharmacy.core.money.MoneyFormat
import bd.rakho.pharmacy.core.time.DhakaTime
import bd.rakho.pharmacy.data.repo.SyncPhase
import bd.rakho.pharmacy.data.repo.SyncStatus
import bd.rakho.pharmacy.ui.theme.Radii
import bd.rakho.pharmacy.ui.theme.Spacing
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
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(
            text = title.uppercase(),
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        action?.invoke()
    }
}

/** Compact metric tile used across the dashboard and reports. */
@Composable
fun KpiTile(
    label: String,
    value: String,
    modifier: Modifier = Modifier,
    icon: ImageVector? = null,
    emphasize: Boolean = false,
    hint: String? = null,
) {
    val container = if (emphasize) {
        MaterialTheme.colorScheme.tertiaryContainer
    } else {
        MaterialTheme.colorScheme.surface
    }
    val content = if (emphasize) {
        MaterialTheme.colorScheme.onTertiaryContainer
    } else {
        MaterialTheme.colorScheme.onSurface
    }
    Surface(
        modifier = modifier,
        shape = RoundedCornerShape(Radii.card),
        color = container,
        tonalElevation = if (emphasize) 0.dp else 1.dp,
    ) {
        Column(modifier = Modifier.padding(Spacing.lg)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                if (icon != null) {
                    Icon(
                        imageVector = icon,
                        contentDescription = null,
                        tint = content.copy(alpha = 0.8f),
                        modifier = Modifier.size(16.dp),
                    )
                    Spacer(Modifier.width(Spacing.sm))
                }
                Text(
                    text = label,
                    style = MaterialTheme.typography.labelMedium,
                    color = content.copy(alpha = 0.8f),
                    maxLines = 1,
                )
            }
            Spacer(Modifier.height(Spacing.sm))
            Text(
                text = value,
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.Bold,
                color = content,
                maxLines = 1,
            )
            if (hint != null) {
                Spacer(Modifier.height(Spacing.xs))
                Text(
                    text = hint,
                    style = MaterialTheme.typography.labelSmall,
                    color = content.copy(alpha = 0.7f),
                    maxLines = 1,
                )
            }
        }
    }
}

/** Large tappable action used in the dashboard grid. */
@Composable
fun QuickActionCard(
    title: String,
    subtitle: String,
    glyph: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Surface(
        modifier = modifier,
        shape = RoundedCornerShape(Radii.card),
        color = MaterialTheme.colorScheme.surface,
        tonalElevation = 1.dp,
        onClick = onClick,
    ) {
        Column(modifier = Modifier.padding(Spacing.lg)) {
            Box(
                modifier = Modifier
                    .size(38.dp)
                    .clip(RoundedCornerShape(12.dp))
                    .background(MaterialTheme.colorScheme.primaryContainer),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    text = glyph,
                    style = MaterialTheme.typography.titleMedium,
                    color = MaterialTheme.colorScheme.onPrimaryContainer,
                )
            }
            Spacer(Modifier.height(Spacing.md))
            Text(
                text = title,
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.SemiBold,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Spacer(Modifier.height(Spacing.xs))
            Text(
                text = subtitle,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 2,
            )
        }
    }
}

/** Sync/offline banner: tells the pharmacist plainly whether work is saved. */
@Composable
fun SyncBanner(status: SyncStatus, modifier: Modifier = Modifier) {
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
        status.lastSyncAtMillis == 0L -> Triple(
            stringResource(R.string.dashboard_never_synced),
            MaterialTheme.colorScheme.surfaceVariant,
            MaterialTheme.colorScheme.onSurfaceVariant,
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
                    .clip(RoundedCornerShape(24.dp))
                    .background(MaterialTheme.colorScheme.surfaceVariant),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    imageVector = icon,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
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

@Composable
fun StatusPill(
    text: String,
    containerColor: Color,
    contentColor: Color,
    modifier: Modifier = Modifier,
) {
    Surface(
        modifier = modifier,
        shape = RoundedCornerShape(Radii.chip),
        color = containerColor,
    ) {
        Text(
            text = text,
            style = MaterialTheme.typography.labelSmall,
            color = contentColor,
            modifier = Modifier
                .padding(horizontal = Spacing.md, vertical = Spacing.xs)
                .animateContentSize(),
        )
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
