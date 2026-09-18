package bd.rakho.pharmacy.feature.dashboard

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.DateRange
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Star
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import bd.rakho.pharmacy.R
import bd.rakho.pharmacy.core.money.MoneyFormat
import bd.rakho.pharmacy.core.time.DhakaTime
import bd.rakho.pharmacy.core.time.ExpiryStatus
import bd.rakho.pharmacy.core.time.ExpiryRules
import bd.rakho.pharmacy.data.repo.SyncPhase
import bd.rakho.pharmacy.di.RakhoViewModelFactory
import bd.rakho.pharmacy.ui.components.KpiTile
import bd.rakho.pharmacy.ui.components.QuickActionCard
import bd.rakho.pharmacy.ui.components.SectionHeader
import bd.rakho.pharmacy.ui.components.SyncBanner
import bd.rakho.pharmacy.ui.theme.Radii
import bd.rakho.pharmacy.ui.theme.Spacing

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DashboardScreen(
    onSell: () -> Unit,
    onReceive: () -> Unit,
    onAddMedicine: () -> Unit,
    onOpenStock: () -> Unit,
    onOpenSettings: () -> Unit,
    onOpenSubscription: () -> Unit,
    viewModel: DashboardViewModel = viewModel(factory = RakhoViewModelFactory),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val today = DhakaTime.today()

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text(
                            text = state.shopName.ifBlank { stringResource(R.string.app_name) },
                            style = MaterialTheme.typography.titleLarge,
                            fontWeight = FontWeight.Bold,
                        )
                        Text(
                            text = stringResource(R.string.app_tagline),
                            style = MaterialTheme.typography.labelMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                },
                actions = {
                    if (state.showProUpsell) {
                        IconButton(onClick = onOpenSubscription) {
                            Icon(
                                imageVector = Icons.Filled.Star,
                                contentDescription = stringResource(R.string.sub_title),
                                tint = MaterialTheme.colorScheme.tertiary,
                            )
                        }
                    }
                    IconButton(onClick = onOpenSettings) {
                        Icon(
                            imageVector = Icons.Filled.Settings,
                            contentDescription = stringResource(R.string.settings_title),
                        )
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.surface,
                ),
            )
        },
    ) { padding ->
        PullToRefreshBox(
            isRefreshing = state.sync.phase == SyncPhase.SYNCING,
            onRefresh = viewModel::refresh,
            modifier = Modifier.fillMaxSize().padding(padding),
        ) {
            LazyColumn(
                contentPadding = PaddingValues(
                    start = Spacing.lg,
                    end = Spacing.lg,
                    top = Spacing.sm,
                    bottom = Spacing.xxl,
                ),
                verticalArrangement = Arrangement.spacedBy(Spacing.md),
            ) {
                item { SyncBanner(state.sync) }

                item {
                    TodayHeroCard(
                        amount = MoneyFormat.format(state.stats.todaySales),
                        saleCount = state.stats.todaySaleCount,
                        profit = MoneyFormat.format(state.stats.todayProfit),
                    )
                }

                item {
                    Row(horizontalArrangement = Arrangement.spacedBy(Spacing.md)) {
                        KpiTile(
                            label = stringResource(R.string.dashboard_stock_value),
                            value = MoneyFormat.format(state.stats.stockValue),
                            icon = Icons.Filled.Star,
                            modifier = Modifier.weight(1f),
                        )
                        KpiTile(
                            label = stringResource(R.string.dashboard_medicines),
                            value = state.stats.medicineCount.toString(),
                            icon = Icons.Filled.DateRange,
                            modifier = Modifier.weight(1f),
                        )
                    }
                }

                item {
                    Row(horizontalArrangement = Arrangement.spacedBy(Spacing.md)) {
                        KpiTile(
                            label = stringResource(R.string.dashboard_low_stock),
                            value = state.stats.lowStockCount.toString(),
                            icon = Icons.Filled.Warning,
                            emphasize = state.stats.lowStockCount > 0,
                            modifier = Modifier.weight(1f),
                        )
                        KpiTile(
                            label = stringResource(R.string.dashboard_expiring_soon),
                            value = state.stats.expiringSoonCount.toString(),
                            icon = Icons.Filled.Warning,
                            emphasize = state.stats.expiringSoonCount > 0,
                            modifier = Modifier.weight(1f),
                        )
                    }
                }

                item { SectionHeader(stringResource(R.string.dashboard_quick_actions)) }

                item {
                    Row(horizontalArrangement = Arrangement.spacedBy(Spacing.md)) {
                        QuickActionCard(
                            title = stringResource(R.string.action_sell),
                            subtitle = stringResource(R.string.pos_search_hint),
                            glyph = "\u09F3",
                            onClick = onSell,
                            modifier = Modifier.weight(1f),
                        )
                        QuickActionCard(
                            title = stringResource(R.string.action_receive),
                            subtitle = stringResource(R.string.action_receive_hint),
                            glyph = "+",
                            onClick = onReceive,
                            modifier = Modifier.weight(1f),
                        )
                    }
                }

                item {
                    Row(horizontalArrangement = Arrangement.spacedBy(Spacing.md)) {
                        QuickActionCard(
                            title = stringResource(R.string.action_add_medicine),
                            subtitle = stringResource(R.string.action_add_medicine_hint),
                            glyph = "\u2695",
                            onClick = onAddMedicine,
                            modifier = Modifier.weight(1f),
                        )
                        QuickActionCard(
                            title = stringResource(R.string.stock_title),
                            subtitle = stringResource(R.string.action_expiry_hint),
                            glyph = "\u23F3",
                            onClick = onOpenStock,
                            modifier = Modifier.weight(1f),
                        )
                    }
                }

                if (state.showProUpsell) {
                    item {
                        ProUpsellCard(onClick = onOpenSubscription)
                    }
                }

                item { SectionHeader(stringResource(R.string.dashboard_needs_attention)) }

                val expiredCount = state.stats.expiredCount
                if (expiredCount > 0) {
                    item {
                        AlertCard(
                            title = stringResource(R.string.dashboard_expired),
                            body = stringResource(R.string.dashboard_expired_body, expiredCount),
                            container = MaterialTheme.colorScheme.errorContainer,
                            content = MaterialTheme.colorScheme.onErrorContainer,
                            onClick = onOpenStock,
                        )
                    }
                }

                if (state.alerts.lowStock.isNotEmpty()) {
                    item {
                        AlertCard(
                            title = stringResource(R.string.dashboard_low_stock),
                            body = state.alerts.lowStock.take(3).joinToString(", ") { it.name },
                            container = MaterialTheme.colorScheme.tertiaryContainer,
                            content = MaterialTheme.colorScheme.onTertiaryContainer,
                            onClick = onOpenStock,
                        )
                    }
                }

                state.alerts.expiringSoon.take(3).forEach { alert ->
                    item(key = "exp-${alert.batch.id}") {
                        val status = ExpiryRules.status(alert.batch.expiryDate, today)
                        AlertCard(
                            title = alert.batch.medicineName,
                            body = when (status) {
                                ExpiryStatus.EXPIRES_TODAY -> stringResource(R.string.stock_expires_today)
                                else -> stringResource(
                                    R.string.stock_expires_in,
                                    alert.daysUntilExpiry.coerceAtLeast(0),
                                )
                            } + " · " + stringResource(
                                R.string.stock_units,
                                alert.batch.quantityAvailable,
                            ),
                            container = if (status == ExpiryStatus.EXPIRES_TODAY) {
                                MaterialTheme.colorScheme.errorContainer
                            } else {
                                MaterialTheme.colorScheme.surfaceVariant
                            },
                            content = if (status == ExpiryStatus.EXPIRES_TODAY) {
                                MaterialTheme.colorScheme.onErrorContainer
                            } else {
                                MaterialTheme.colorScheme.onSurfaceVariant
                            },
                            onClick = onOpenStock,
                        )
                    }
                }

                if (expiredCount == 0 &&
                    state.alerts.expiringSoon.isEmpty() &&
                    state.alerts.lowStock.isEmpty()
                ) {
                    item {
                        AlertCard(
                            title = stringResource(R.string.dashboard_all_good),
                            body = stringResource(R.string.dashboard_all_good_body),
                            container = MaterialTheme.colorScheme.surfaceVariant,
                            content = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun TodayHeroCard(amount: String, saleCount: Int, profit: String) {
    Card(
        shape = RoundedCornerShape(Radii.card),
        colors = CardDefaults.cardColors(containerColor = Color.Transparent),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .background(
                    Brush.linearGradient(
                        listOf(
                            MaterialTheme.colorScheme.primary,
                            MaterialTheme.colorScheme.primary.copy(alpha = 0.78f),
                        ),
                    ),
                )
                .padding(Spacing.xl),
        ) {
            Column {
                Text(
                    text = stringResource(R.string.dashboard_today_sales),
                    style = MaterialTheme.typography.labelLarge,
                    color = MaterialTheme.colorScheme.onPrimary.copy(alpha = 0.85f),
                )
                Spacer(Modifier.height(Spacing.xs))
                Text(
                    text = amount,
                    style = MaterialTheme.typography.displaySmall,
                    color = MaterialTheme.colorScheme.onPrimary,
                )
                Spacer(Modifier.height(Spacing.md))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        text = stringResource(R.string.dashboard_sale_count, saleCount),
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onPrimary.copy(alpha = 0.9f),
                    )
                    Spacer(Modifier.width(Spacing.md))
                    Text(
                        text = "${stringResource(R.string.dashboard_today_profit)} $profit",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onPrimary.copy(alpha = 0.9f),
                    )
                }
            }
        }
    }
}

@Composable
private fun ProUpsellCard(onClick: () -> Unit) {
    Surface(
        shape = RoundedCornerShape(Radii.card),
        color = MaterialTheme.colorScheme.primaryContainer,
        onClick = onClick,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(
            modifier = Modifier.padding(Spacing.lg),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(
                imageVector = Icons.Filled.Star,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onPrimaryContainer,
                modifier = Modifier.size(24.dp),
            )
            Spacer(Modifier.width(Spacing.md))
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = stringResource(R.string.sub_title),
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.SemiBold,
                    color = MaterialTheme.colorScheme.onPrimaryContainer,
                )
                Spacer(Modifier.height(Spacing.xs))
                Text(
                    text = stringResource(R.string.dashboard_pro_body),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onPrimaryContainer.copy(alpha = 0.85f),
                )
            }
            TextButton(onClick = onClick) {
                Text(
                    text = stringResource(R.string.dashboard_pro_cta),
                    color = MaterialTheme.colorScheme.onPrimaryContainer,
                    fontWeight = FontWeight.Bold,
                )
            }
        }
    }
}

@Composable
private fun AlertCard(
    title: String,
    body: String,
    container: Color,
    content: Color,
    onClick: () -> Unit = {},
) {
    Surface(
        shape = RoundedCornerShape(Radii.card),
        color = container,
        onClick = onClick,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(
            modifier = Modifier.padding(Spacing.lg),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = title,
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.SemiBold,
                    color = content,
                )
                Spacer(Modifier.height(Spacing.xs))
                Text(
                    text = body,
                    style = MaterialTheme.typography.bodySmall,
                    color = content.copy(alpha = 0.85f),
                )
            }
            TextButton(onClick = onClick) {
                Text(stringResource(R.string.action_view), color = content)
            }
        }
    }
}
