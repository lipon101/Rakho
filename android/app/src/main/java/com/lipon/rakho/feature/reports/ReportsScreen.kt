package com.lipon.rakho.feature.reports

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Leaderboard
import androidx.compose.material.icons.filled.Payments
import androidx.compose.material.icons.filled.Receipt
import androidx.compose.material.icons.filled.ShoppingBag
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import com.lipon.rakho.ui.components.RakhoFilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.lipon.rakho.R
import com.lipon.rakho.core.money.MoneyFormat
import com.lipon.rakho.core.time.DhakaTime
import com.lipon.rakho.di.RakhoViewModelFactory
import com.lipon.rakho.ui.charts.DayBar
import com.lipon.rakho.ui.charts.DeltaChip
import com.lipon.rakho.ui.charts.ShareBar
import com.lipon.rakho.ui.charts.WeeklyBars
import com.lipon.rakho.ui.components.EmptyState
import com.lipon.rakho.ui.components.KpiTile
import com.lipon.rakho.ui.components.KpiTone
import com.lipon.rakho.ui.components.SalesRangePicker
import com.lipon.rakho.ui.components.SectionHeader
import com.lipon.rakho.ui.theme.Radii
import com.lipon.rakho.ui.theme.Sizes
import com.lipon.rakho.ui.theme.Spacing
import com.lipon.rakho.ui.theme.statusNearText
import com.lipon.rakho.ui.util.FileSharing
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ReportsScreen(
    viewModel: ReportsViewModel = viewModel(factory = RakhoViewModelFactory),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val snackbar = remember { SnackbarHostState() }
    val scope = rememberCoroutineScope()
    val shareTitle = stringResource(R.string.reports_share)
    val exportedText = stringResource(R.string.reports_exported)
    val errorText = stringResource(R.string.error_generic)

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = { TopAppBar(title = { Text(stringResource(R.string.reports_title)) }) },
    ) { padding ->
        LazyColumn(
            modifier = Modifier.fillMaxSize().padding(padding),
            contentPadding = PaddingValues(
                start = Spacing.lg,
                end = Spacing.lg,
                top = Spacing.sm,
                bottom = Spacing.xxl,
            ),
            verticalArrangement = Arrangement.spacedBy(Spacing.md),
        ) {
            item {
                SalesRangePicker(
                    selected = state.period,
                    onSelect = viewModel::onPeriodChange,
                )
            }

            // Hero: revenue + the one question owners always ask — "better or
            // worse than before?" The delta compares the same-length window.
            item {
                Surface(
                    shape = RoundedCornerShape(Radii.card),
                    color = MaterialTheme.colorScheme.primaryContainer,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Column(modifier = Modifier.padding(Spacing.xl)) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Column(modifier = Modifier.weight(1f)) {
                                Text(
                                    text = stringResource(R.string.reports_sales),
                                    style = MaterialTheme.typography.labelLarge,
                                    color = MaterialTheme.colorScheme.onPrimaryContainer.copy(alpha = 0.85f),
                                )
                                Spacer(Modifier.height(Spacing.xs))
                                Text(
                                    text = MoneyFormat.format(state.totalSales),
                                    style = MaterialTheme.typography.displaySmall,
                                    color = MaterialTheme.colorScheme.onPrimaryContainer,
                                )
                            }
                            val deltaPct = state.analytics.deltaPct
                            if (deltaPct != null) {
                                DeltaChip(
                                    text = formatDelta(deltaPct),
                                    positive = deltaPct >= 0,
                                )
                            }
                        }
                        Spacer(Modifier.height(Spacing.sm))
                        Text(
                            text = stringResource(R.string.dashboard_sale_count, state.billCount),
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onPrimaryContainer.copy(alpha = 0.9f),
                        )
                        val previousTotal = state.analytics.previousTotal
                        if (previousTotal != null && state.analytics.deltaPct == null) {
                            Text(
                                text = stringResource(
                                    R.string.reports_prev_period,
                                    MoneyFormat.format(previousTotal),
                                ),
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onPrimaryContainer.copy(alpha = 0.75f),
                            )
                        }
                    }
                }
            }

            item {
                Row(horizontalArrangement = Arrangement.spacedBy(Spacing.md)) {
                    KpiTile(
                        label = stringResource(R.string.reports_bills),
                        value = state.billCount.toString(),
                        icon = Icons.Filled.Receipt,
                        modifier = Modifier.weight(1f),
                    )
                    KpiTile(
                        label = stringResource(R.string.reports_items_sold),
                        value = state.itemCount.toString(),
                        icon = Icons.Filled.ShoppingBag,
                        modifier = Modifier.weight(1f),
                    )
                }
            }

            // True profit from FEFO costs — the money the shop actually kept.
            item {
                Row(horizontalArrangement = Arrangement.spacedBy(Spacing.md)) {
                    KpiTile(
                        label = stringResource(R.string.reports_profit),
                        value = MoneyFormat.format(state.analytics.profit),
                        icon = Icons.Filled.Payments,
                        tone = KpiTone.PROFIT,
                        modifier = Modifier.weight(1f),
                    )
                    KpiTile(
                        label = stringResource(R.string.reports_margin),
                        value = state.analytics.marginPct?.let { formatPct(it) } ?: "—",
                        icon = Icons.Filled.Leaderboard,
                        tone = KpiTone.PROFIT,
                        modifier = Modifier.weight(1f),
                    )
                }
            }

            item {
                KpiTile(
                    label = stringResource(R.string.reports_average_bill),
                    value = MoneyFormat.format(state.averageBill),
                    icon = Icons.Filled.Payments,
                    modifier = Modifier.fillMaxWidth(),
                )
            }

            item {
                Surface(
                    shape = RoundedCornerShape(Radii.card),
                    color = MaterialTheme.colorScheme.surface,
                    tonalElevation = 1.dp,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Column(modifier = Modifier.padding(Spacing.xl)) {
                        Text(
                            text = stringResource(R.string.reports_daily_trend),
                            style = MaterialTheme.typography.titleSmall,
                            fontWeight = FontWeight.SemiBold,
                        )
                        Spacer(Modifier.height(Spacing.lg))
                        WeeklyBars(
                            days = state.dailySeries.map { bucket ->
                                DayBar(
                                    label = bucket.label,
                                    value = bucket.total,
                                    highlighted = bucket.highlighted,
                                )
                            },
                        )
                    }
                }
            }

            // Payment split with % that always sums to 100 — cash vs bKash
            // vs Nagad at a glance, amounts exact to the paisa.
            if (state.analytics.paymentSlices.isNotEmpty()) {
                item { SectionHeader(stringResource(R.string.reports_payment_title)) }

                item {
                    Surface(
                        shape = RoundedCornerShape(Radii.card),
                        color = MaterialTheme.colorScheme.surface,
                        tonalElevation = 1.dp,
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Column(
                            modifier = Modifier.padding(Spacing.lg),
                            verticalArrangement = Arrangement.spacedBy(Spacing.sm),
                        ) {
                            state.analytics.paymentSlices.forEach { slice ->
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    Column(modifier = Modifier.weight(1f)) {
                                        Text(
                                            text = paymentLabel(slice.method),
                                            style = MaterialTheme.typography.bodyMedium,
                                            fontWeight = FontWeight.SemiBold,
                                            maxLines = 1,
                                            overflow = TextOverflow.Ellipsis,
                                        )
                                        Text(
                                            text = MoneyFormat.format(slice.amount),
                                            style = MaterialTheme.typography.labelSmall,
                                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                                        )
                                    }
                                    Text(
                                        text = "${slice.percent}%",
                                        style = MaterialTheme.typography.titleMedium,
                                        fontWeight = FontWeight.Bold,
                                        color = MaterialTheme.colorScheme.primary,
                                        modifier = Modifier.padding(horizontal = Spacing.sm),
                                    )
                                }
                                ShareBar(
                                    fraction = slice.percent / 100f,
                                    color = MaterialTheme.colorScheme.primary,
                                )
                            }
                        }
                    }
                }
            }

            item {
                Button(
                    onClick = {
                        val csv = viewModel.buildCsv()
                        val fileName = "rakho-sales-${DhakaTime.today()}.csv"
                        FileSharing.shareText(context, fileName, csv, chooserTitle = shareTitle)
                            .onSuccess { scope.launch { snackbar.showSnackbar(exportedText) } }
                            .onFailure { scope.launch { snackbar.showSnackbar(errorText) } }
                    },
                    shape = RoundedCornerShape(Radii.button),
                    modifier = Modifier.fillMaxWidth().height(Sizes.primaryButtonHeight),
                ) {
                    Text(
                        text = stringResource(R.string.reports_export_csv),
                        fontWeight = FontWeight.Bold,
                    )
                }
            }

            item { SectionHeader(stringResource(R.string.reports_top_items)) }

            if (state.topItems.isEmpty()) {
                item {
                    EmptyState(
                        title = stringResource(R.string.reports_empty),
                        body = stringResource(R.string.action_sell_hint),
                        icon = Icons.Filled.Leaderboard,
                    )
                }
            } else {
                val topAmount = state.topItems.maxOfOrNull { it.amount.paisa } ?: 1L
                itemsIndexed(state.topItems, key = { _, item -> item.name }) { index, item ->
                    Surface(
                        shape = RoundedCornerShape(Radii.card),
                        color = MaterialTheme.colorScheme.surface,
                        tonalElevation = 1.dp,
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Column(modifier = Modifier.padding(Spacing.lg)) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Text(
                                    text = "${index + 1}",
                                    style = MaterialTheme.typography.labelLarge,
                                    fontWeight = FontWeight.Bold,
                                    color = MaterialTheme.colorScheme.primary,
                                    modifier = Modifier.padding(end = Spacing.md),
                                )
                                Column(modifier = Modifier.weight(1f)) {
                                    Text(
                                        text = item.name,
                                        style = MaterialTheme.typography.bodyLarge,
                                        fontWeight = FontWeight.SemiBold,
                                        maxLines = 1,
                                        overflow = TextOverflow.Ellipsis,
                                    )
                                    Text(
                                        text = stringResource(R.string.stock_units, item.quantity),
                                        style = MaterialTheme.typography.labelSmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    )
                                }
                                Text(
                                    text = MoneyFormat.format(item.amount),
                                    style = MaterialTheme.typography.titleSmall,
                                    fontWeight = FontWeight.Bold,
                                )
                            }
                            Spacer(Modifier.height(Spacing.sm))
                            ShareBar(
                                fraction = item.amount.paisa.toFloat() / topAmount,
                                color = if (index == 0) {
                                    MaterialTheme.colorScheme.primary
                                } else {
                                    MaterialTheme.colorScheme.primary.copy(alpha = 0.45f)
                                },
                            )
                        }
                    }
                }
            }

            // Slow movers: stock on hand with zero sales in this range. Dead
            // capital the shop should discount, return or stop ordering.
            if (state.analytics.slowMovers.isNotEmpty()) {
                item { SectionHeader(stringResource(R.string.reports_slow_title)) }

                items(
                    state.analytics.slowMovers,
                    key = { it.medicineId },
                ) { mover ->
                    Surface(
                        shape = RoundedCornerShape(Radii.card),
                        color = MaterialTheme.colorScheme.surface,
                        tonalElevation = 1.dp,
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Row(
                            modifier = Modifier.padding(Spacing.lg),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Column(modifier = Modifier.weight(1f)) {
                                Text(
                                    text = mover.name,
                                    style = MaterialTheme.typography.bodyLarge,
                                    fontWeight = FontWeight.SemiBold,
                                    maxLines = 1,
                                    overflow = TextOverflow.Ellipsis,
                                )
                                Text(
                                    text = stringResource(
                                        R.string.reports_slow_body,
                                    ) + " · " + stringResource(
                                        R.string.stock_units,
                                        mover.unitsOnHand,
                                    ),
                                    style = MaterialTheme.typography.labelSmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                            Text(
                                text = MoneyFormat.format(mover.valueOnHand),
                                style = MaterialTheme.typography.titleSmall,
                                fontWeight = FontWeight.Bold,
                                color = statusNearText(),
                            )
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun paymentLabel(method: com.lipon.rakho.core.model.PaymentMethod): String =
    stringResource(
        when (method) {
            com.lipon.rakho.core.model.PaymentMethod.CASH -> R.string.pay_cash
            com.lipon.rakho.core.model.PaymentMethod.BKASH -> R.string.pay_bkash
            com.lipon.rakho.core.model.PaymentMethod.NAGAD -> R.string.pay_nagad
            com.lipon.rakho.core.model.PaymentMethod.CARD -> R.string.pay_card
            com.lipon.rakho.core.model.PaymentMethod.CREDIT -> R.string.pay_credit
        },
    )

/** Kept for callers that need the formatted report title. */
@Composable
fun reportPeriodLabel(period: ReportPeriod): String = stringResource(
    when (period) {
        ReportPeriod.TODAY -> R.string.reports_today
        ReportPeriod.WEEK -> R.string.reports_week
        ReportPeriod.MONTH -> R.string.reports_month
    },
)

/** Formatted title for the minimal sales range (reports). */
@Composable
fun salesRangeLabel(range: com.lipon.rakho.core.time.SalesRange): String = stringResource(
    when (range) {
        com.lipon.rakho.core.time.SalesRange.LAST_1H -> R.string.range_1h
        com.lipon.rakho.core.time.SalesRange.LAST_24H -> R.string.range_24h
        com.lipon.rakho.core.time.SalesRange.LAST_7D -> R.string.range_7d
        com.lipon.rakho.core.time.SalesRange.LAST_30D -> R.string.range_30d
        com.lipon.rakho.core.time.SalesRange.LAST_1Y -> R.string.range_1y
    },
)

/** "+12.5%" / "-3.0%" — one decimal, always signed, for the delta chip. */
private fun formatDelta(pct: Double): String {
    val rounded = kotlin.math.round(pct * 10) / 10.0
    val text = if (rounded == -0.0) "0.0" else rounded.toString()
    return (if (rounded >= 0) "+" else "") + text + "%"
}

/** "24.6%" — one decimal for the margin tile. */
private fun formatPct(pct: Double): String {
    val rounded = kotlin.math.round(pct * 10) / 10.0
    return "$rounded%"
}
