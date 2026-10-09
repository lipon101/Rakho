package com.lipon.rakho.feature.dashboard

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.IntrinsicSize
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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AddBusiness
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material.icons.filled.Inventory2
import androidx.compose.material.icons.filled.LocalPharmacy
import androidx.compose.material.icons.filled.Medication
import androidx.compose.material.icons.filled.PointOfSale
import androidx.compose.material.icons.filled.ProductionQuantityLimits
import androidx.compose.material.icons.filled.Schedule
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.TextButton
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
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.lipon.rakho.R
import com.lipon.rakho.core.model.StockFilter
import com.lipon.rakho.core.money.Money
import com.lipon.rakho.core.money.MoneyFormat
import com.lipon.rakho.core.time.DhakaTime
import com.lipon.rakho.core.time.ExpiryStatus
import com.lipon.rakho.core.time.ExpiryRules
import com.lipon.rakho.core.time.SalesRange
import com.lipon.rakho.core.time.SalesRanges
import com.lipon.rakho.data.repo.SyncPhase
import com.lipon.rakho.di.RakhoViewModelFactory
import com.lipon.rakho.ui.components.KpiTile
import com.lipon.rakho.ui.components.KpiTone
import com.lipon.rakho.feature.reports.salesRangeLabel
import com.lipon.rakho.ui.components.QuickActionCard
import com.lipon.rakho.ui.components.SectionHeader
import com.lipon.rakho.ui.components.SyncBanner
import com.lipon.rakho.ui.charts.DayBar
import com.lipon.rakho.ui.charts.WeeklyBars
import com.lipon.rakho.ui.theme.Radii
import com.lipon.rakho.ui.theme.Sizes
import com.lipon.rakho.ui.theme.Spacing
import com.lipon.rakho.ui.theme.expiryStripColor
import com.lipon.rakho.ui.theme.statusNearContainer
import com.lipon.rakho.ui.theme.statusNearText
import com.lipon.rakho.ui.theme.statusSafeText
import com.lipon.rakho.ui.theme.StatusExpired
import com.lipon.rakho.ui.theme.StatusNear
import androidx.compose.material.icons.filled.Handshake
import androidx.compose.material.icons.filled.LocalShipping
import androidx.compose.material.icons.filled.MoneyOff

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DashboardScreen(
    onSell: () -> Unit,
    onReceive: () -> Unit,
    onAddMedicine: () -> Unit,
    onOpenStock: (StockFilter?) -> Unit,
    onOpenDues: () -> Unit,
    onOpenSettings: () -> Unit,
    onOpenReports: () -> Unit = {},
    onOpenPurchaseHistory: () -> Unit = {},
    onOpenExpenses: () -> Unit = {},
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
                navigationIcon = {
                    // The pharmacy mark, not the shop's initial: a mortar and
                    // pestle reads as "chemist" at a glance and looks the same
                    // for every shop name — "M", "R" and a stray punctuation
                    // mark never do.
                    Box(
                        modifier = Modifier
                            .padding(start = Spacing.xs)
                            .size(36.dp)
                            .clip(CircleShape)
                            .background(MaterialTheme.colorScheme.primaryContainer),
                        contentAlignment = Alignment.Center,
                    ) {
                        Icon(
                            imageVector = Icons.Filled.LocalPharmacy,
                            contentDescription = null,
                            tint = MaterialTheme.colorScheme.onPrimaryContainer,
                            modifier = Modifier.size(20.dp),
                        )
                    }
                },
                actions = {
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
                // Sync is always live in the cloud build: the banner reports
                // queued writes whenever there are any.
                item { SyncBanner(state.sync) }

                item {
                    TodayHeroCard(
                        amount = MoneyFormat.format(state.stats.todaySales),
                        saleCount = state.stats.todaySaleCount,
                        profit = MoneyFormat.format(state.stats.todayProfit),
                        onClick = onOpenReports,
                    )
                }

                // A brand-new shop has nothing to show a pulse for. Replace
                // the empty charts with the three steps that make the app
                // useful — the quickest path from "just signed up" to "first
                // bill printed".
                if (state.stats.medicineCount == 0 && state.stats.todaySaleCount == 0) {
                    item {
                        FirstRunCard(
                            onAddMedicine = onAddMedicine,
                            onReceive = onReceive,
                            onSell = onSell,
                        )
                    }
                } else {
                    // Pulse: hourly by default, switchable to day/week/month/year
                    // from the card's own dropdown. Reports keeps the full studio.
                    item {
                        TodayPulseCard(
                            state = state,
                            selectedRange = state.pulseRange,
                            onRangeSelect = viewModel::onPulseRangeChange,
                            onOpenReports = onOpenReports,
                        )
                    }
                }

                item {
                    // Intrinsic min height plus fillMaxHeight: the taller
                    // tile in the pair sets the row and the shorter one
                    // stretches to meet it, so a caption on one card can never
                    // leave the two bottoming out on different lines.
                    Row(
                        modifier = Modifier.height(IntrinsicSize.Min),
                        horizontalArrangement = Arrangement.spacedBy(Spacing.md),
                    ) {
                        KpiTile(
                            label = stringResource(R.string.dashboard_stock_value),
                            value = MoneyFormat.format(state.stats.stockValue),
                            icon = Icons.Filled.Inventory2,
                            modifier = Modifier.weight(1f).fillMaxHeight(),
                            onClick = { onOpenStock(null) },
                        )
                        KpiTile(
                            label = stringResource(R.string.dashboard_medicines),
                            value = state.stats.medicineCount.toString(),
                            icon = Icons.Filled.Medication,
                            modifier = Modifier.weight(1f).fillMaxHeight(),
                            onClick = { onOpenStock(null) },
                        )
                    }
                }

                item {
                    Row(
                        modifier = Modifier.height(IntrinsicSize.Min),
                        horizontalArrangement = Arrangement.spacedBy(Spacing.md),
                    ) {
                        // Low stock and short-dated stock are both warnings,
                        // so both read amber — never the teal that used to
                        // make a low shelf look like a healthy one.
                        KpiTile(
                            label = stringResource(R.string.dashboard_low_stock),
                            value = state.stats.lowStockCount.toString(),
                            icon = Icons.Filled.ProductionQuantityLimits,
                            tone = if (state.stats.lowStockCount > 0) {
                                KpiTone.WARNING
                            } else {
                                KpiTone.NEUTRAL
                            },
                            modifier = Modifier.weight(1f).fillMaxHeight(),
                            onClick = { onOpenStock(StockFilter.LOW) },
                        )
                        KpiTile(
                            label = stringResource(R.string.dashboard_expiring_soon),
                            value = state.stats.expiringSoonCount.toString(),
                            icon = Icons.Filled.Schedule,
                            tone = if (state.stats.expiringSoonCount > 0) {
                                KpiTone.WARNING
                            } else {
                                KpiTone.NEUTRAL
                            },
                            hint = if (state.stats.expiringValue.isZero) {
                                null
                            } else {
                                MoneyFormat.format(state.stats.expiringValue)
                            },
                            modifier = Modifier.weight(1f).fillMaxHeight(),
                            onClick = { onOpenStock(StockFilter.EXPIRING) },
                        )
                    }
                }

                if (state.duesTotal.paisa > 0) {
                    item {
                        Card(
                            onClick = onOpenDues,
                            shape = RoundedCornerShape(Radii.card),
                            colors = CardDefaults.cardColors(
                                containerColor = MaterialTheme.colorScheme.tertiaryContainer,
                            ),
                            modifier = Modifier.fillMaxWidth(),
                        ) {
                            Row(
                                modifier = Modifier.padding(Spacing.lg),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Icon(
                                    Icons.Filled.Handshake,
                                    contentDescription = null,
                                    tint = MaterialTheme.colorScheme.onTertiaryContainer,
                                )
                                Column(
                                    modifier = Modifier
                                        .weight(1f)
                                        .padding(start = Spacing.md),
                                ) {
                                    Text(
                                        text = stringResource(R.string.dues_total_label),
                                        style = MaterialTheme.typography.labelMedium,
                                        color = MaterialTheme.colorScheme.onTertiaryContainer,
                                    )
                                    Text(
                                        text = MoneyFormat.format(state.duesTotal),
                                        style = MaterialTheme.typography.titleLarge,
                                        fontWeight = FontWeight.Bold,
                                        color = MaterialTheme.colorScheme.onTertiaryContainer,
                                    )
                                }
                                Text(
                                    text = stringResource(R.string.dues_customer_count, state.duesCount),
                                    style = MaterialTheme.typography.labelMedium,
                                    color = MaterialTheme.colorScheme.onTertiaryContainer,
                                )
                            }
                        }
                    }
                }

                item { SectionHeader(stringResource(R.string.dashboard_quick_actions)) }

                item {
                    Row(modifier = Modifier.fillMaxWidth().height(IntrinsicSize.Max), horizontalArrangement = Arrangement.spacedBy(Spacing.md)) {
                        QuickActionCard(
                            title = stringResource(R.string.action_sell),
                            subtitle = stringResource(R.string.action_sell_hint),
                            icon = Icons.Filled.PointOfSale,
                            onClick = onSell,
                            modifier = Modifier.weight(1f).fillMaxHeight(),
                        )
                        QuickActionCard(
                            title = stringResource(R.string.action_receive),
                            subtitle = stringResource(R.string.action_receive_hint),
                            icon = Icons.Filled.AddBusiness,
                            onClick = onReceive,
                            modifier = Modifier.weight(1f).fillMaxHeight(),
                        )
                    }
                }

                item {
                    Row(modifier = Modifier.fillMaxWidth().height(IntrinsicSize.Max), horizontalArrangement = Arrangement.spacedBy(Spacing.md)) {
                        QuickActionCard(
                            title = stringResource(R.string.action_add_medicine),
                            subtitle = stringResource(R.string.action_add_medicine_hint),
                            icon = Icons.Filled.Medication,
                            onClick = onAddMedicine,
                            modifier = Modifier.weight(1f).fillMaxHeight(),
                        )
                        QuickActionCard(
                            title = stringResource(R.string.stock_title),
                            subtitle = stringResource(R.string.action_expiry_hint),
                            icon = Icons.Filled.Schedule,
                            onClick = { onOpenStock(null) },
                            modifier = Modifier.weight(1f).fillMaxHeight(),
                        )
                    }
                }

                item {
                    Row(modifier = Modifier.fillMaxWidth().height(IntrinsicSize.Max), horizontalArrangement = Arrangement.spacedBy(Spacing.md)) {
                        QuickActionCard(
                            title = stringResource(R.string.purchases_title),
                            subtitle = stringResource(R.string.purchases_subtitle),
                            icon = Icons.Filled.LocalShipping,
                            onClick = onOpenPurchaseHistory,
                            modifier = Modifier.weight(1f).fillMaxHeight(),
                        )
                        QuickActionCard(
                            title = stringResource(R.string.expenses_title),
                            subtitle = stringResource(R.string.expenses_subtitle),
                            icon = Icons.Filled.MoneyOff,
                            onClick = onOpenExpenses,
                            modifier = Modifier.weight(1f).fillMaxHeight(),
                        )
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
                            icon = Icons.Filled.Warning,
                            strip = StatusExpired,
                            onClick = { onOpenStock(StockFilter.EXPIRED) },
                        )
                    }
                }

                if (state.alerts.lowStock.isNotEmpty()) {
                    item {
                        // Exact live detail: "5 medicines · 12 units left · Napa …".
                        val lowest = state.alerts.lowStock.minByOrNull { it.available }
                        AlertCard(
                            title = stringResource(R.string.dashboard_low_stock),
                            body = stringResource(
                                R.string.dashboard_low_stock_body,
                                state.alerts.lowStock.size,
                                state.alerts.lowStock.sumOf { it.available },
                            ) + (lowest?.let { " · ${it.name}" } ?: ""),
                            // Amber, not teal: running low is a warning, and
                            // green text on green never reads as one.
                            container = statusNearContainer(),
                            content = statusNearText(),
                            icon = Icons.Filled.ProductionQuantityLimits,
                            strip = StatusNear,
                            onClick = { onOpenStock(StockFilter.LOW) },
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
                            ) + " · " + MoneyFormat.format(alert.batch.stockValue),
                            container = if (status == ExpiryStatus.EXPIRES_TODAY) {
                                MaterialTheme.colorScheme.errorContainer
                            } else {
                                statusNearContainer()
                            },
                            content = if (status == ExpiryStatus.EXPIRES_TODAY) {
                                MaterialTheme.colorScheme.onErrorContainer
                            } else {
                                statusNearText()
                            },
                            icon = Icons.Filled.Schedule,
                            strip = expiryStripColor(status),
                            onClick = { onOpenStock(StockFilter.EXPIRING) },
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
private fun TodayHeroCard(
    amount: String,
    saleCount: Int,
    profit: String,
    onClick: () -> Unit = {},
) {
    Card(
        onClick = onClick,
        shape = RoundedCornerShape(Radii.card),
        colors = CardDefaults.cardColors(containerColor = Color.Transparent),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                // Flat brand fill — gradients are out by design (low-end GPUs,
                // no blur/blur-heavy decoration), and white text on it is 5.2:1.
                .background(MaterialTheme.colorScheme.primary)
                .padding(Spacing.xl),
        ) {
            Column {
                Text(
                    text = stringResource(R.string.dashboard_today_sales),
                    style = MaterialTheme.typography.labelLarge,
                    color = Color.White.copy(alpha = 0.85f),
                )
                Spacer(Modifier.height(Spacing.xs))
                Text(
                    text = amount,
                    style = MaterialTheme.typography.displaySmall,
                    color = Color.White,
                )
                Spacer(Modifier.height(Spacing.md))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        text = stringResource(R.string.dashboard_sale_count, saleCount),
                        style = MaterialTheme.typography.bodyMedium,
                        color = Color.White.copy(alpha = 0.92f),
                    )
                    Spacer(Modifier.width(Spacing.md))
                    Text(
                        text = "${stringResource(R.string.dashboard_today_profit)} $profit",
                        style = MaterialTheme.typography.bodyMedium,
                        color = Color.White.copy(alpha = 0.92f),
                    )
                }
            }
        }
    }
}

/**
 * "Is today normal?" — a compact hourly pulse strip plus today's true
 * profit. Home's cockpit view of the day; the multi-range business analysis
 * lives only in Reports, so the two tabs never show the same chart twice.
 */
@Composable
private fun TodayPulseCard(
    state: DashboardUiState,
    selectedRange: SalesRange,
    onRangeSelect: (SalesRange) -> Unit,
    onOpenReports: () -> Unit,
) {
    var menuOpen by remember { mutableStateOf(false) }
    // TEMP PREVIEW ONLY — remove before release: when the range has no
    // sales, draw the curve shape with clearly fake sample values so the
    // design can be judged. Nothing here touches the ledger or profit.
    val isPreview = state.pulseBuckets.all { it.total.isZero }
    val bars = if (isPreview) {
        previewPulse()
    } else {
        state.pulseBuckets.map { bucket ->
            DayBar(
                label = SalesRanges.smartAxisLabel(bucket.label, selectedRange),
                value = bucket.total,
                highlighted = bucket.highlighted,
            )
        }
    }
    val pulseMax = bars.maxOfOrNull { it.value.paisa } ?: 0L

    Surface(
        shape = RoundedCornerShape(Radii.card),
        color = MaterialTheme.colorScheme.surface,
        tonalElevation = 1.dp,
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onOpenReports),
    ) {
        Column(modifier = Modifier.padding(Spacing.xl)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = stringResource(R.string.dashboard_today_pulse),
                        style = MaterialTheme.typography.titleSmall,
                        fontWeight = FontWeight.SemiBold,
                    )
                    Text(
                        text = MoneyFormat.format(state.pulseTotal),
                        style = MaterialTheme.typography.headlineSmall,
                        fontWeight = FontWeight.Bold,
                    )
                }
                if (state.todayProfitTrue != null) {
                    Column(horizontalAlignment = Alignment.End) {
                        Text(
                            text = MoneyFormat.format(state.todayProfitTrue),
                            style = MaterialTheme.typography.titleMedium,
                            fontWeight = FontWeight.Bold,
                            color = statusSafeText(),
                        )
                        Text(
                            text = stringResource(R.string.dashboard_today_profit),
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
                Box {
                    TextButton(onClick = { menuOpen = true }) {
                        Text(
                            text = salesRangeLabel(selectedRange),
                            style = MaterialTheme.typography.labelLarge,
                            fontWeight = FontWeight.SemiBold,
                            color = MaterialTheme.colorScheme.primary,
                        )
                        Icon(
                            imageVector = Icons.Filled.ArrowDropDown,
                            contentDescription = stringResource(R.string.dashboard_pulse_range),
                            tint = MaterialTheme.colorScheme.primary,
                            modifier = Modifier.size(18.dp),
                        )
                    }
                    DropdownMenu(
                        expanded = menuOpen,
                        onDismissRequest = { menuOpen = false },
                    ) {
                        PulseRangeOption(
                            label = stringResource(R.string.range_24h),
                            selected = selectedRange == SalesRange.LAST_24H,
                            onClick = {
                                menuOpen = false
                                onRangeSelect(SalesRange.LAST_24H)
                            },
                        )
                        PulseRangeOption(
                            label = stringResource(R.string.range_7d),
                            selected = selectedRange == SalesRange.LAST_7D,
                            onClick = {
                                menuOpen = false
                                onRangeSelect(SalesRange.LAST_7D)
                            },
                        )
                        PulseRangeOption(
                            label = stringResource(R.string.range_30d),
                            selected = selectedRange == SalesRange.LAST_30D,
                            onClick = {
                                menuOpen = false
                                onRangeSelect(SalesRange.LAST_30D)
                            },
                        )
                        PulseRangeOption(
                            label = stringResource(R.string.range_1y),
                            selected = selectedRange == SalesRange.LAST_1Y,
                            onClick = {
                                menuOpen = false
                                onRangeSelect(SalesRange.LAST_1Y)
                            },
                        )
                    }
                }
            }
            if (pulseMax > 0L) {
                Spacer(Modifier.height(Spacing.md))
                WeeklyBars(days = bars)
            } else {
                Spacer(Modifier.height(Spacing.sm))
                Text(
                    text = stringResource(R.string.dashboard_pulse_empty),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            if (state.todayMarginPct != null) {
                Spacer(Modifier.height(Spacing.sm))
                Text(
                    text = stringResource(
                        R.string.dashboard_margin_today,
                        formatMargin(state.todayMarginPct),
                    ),
                    style = MaterialTheme.typography.labelMedium,
                    color = statusSafeText(),
                    fontWeight = FontWeight.SemiBold,
                )
            }
        }
    }
}

/** One checkable row inside the pulse range dropdown. */
@Composable
private fun PulseRangeOption(label: String, selected: Boolean, onClick: () -> Unit) {
    DropdownMenuItem(
        text = {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    text = label,
                    fontWeight = if (selected) FontWeight.Bold else FontWeight.Normal,
                    modifier = Modifier.weight(1f),
                )
                if (selected) {
                    Icon(
                        imageVector = Icons.Filled.Check,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.primary,
                        modifier = Modifier.size(18.dp),
                    )
                }
            }
        },
        onClick = onClick,
        contentPadding = PaddingValues(horizontal = Spacing.lg, vertical = Spacing.xs),
    )
}

/** "24.6%" — one decimal for the home margin line. */
private fun formatMargin(pct: Double): String {
    val rounded = kotlin.math.round(pct * 10) / 10.0
    return "$rounded%"
}

/**
 * TEMP PREVIEW ONLY — clearly fake hourly sample values (9 AM–8 PM shop
 * rhythm) so the curve design can be judged with no sales yet. On-screen
 * only: never saved, never counted in profit or CSV. DELETE before release.
 */
private fun previewPulse(): List<DayBar> {
    val sample = listOf(
        "9 AM" to 450_00L, "10 AM" to 820_00L, "11 AM" to 640_00L,
        "12 PM" to 1_150_00L, "1 PM" to 980_00L, "2 PM" to 720_00L,
        "3 PM" to 890_00L, "4 PM" to 1_320_00L, "5 PM" to 1_580_00L,
        "6 PM" to 1_240_00L, "7 PM" to 960_00L, "8 PM" to 540_00L,
    )
    return sample.mapIndexed { index, (label, paisa) ->
        DayBar(
            label = label,
            value = com.lipon.rakho.core.money.Money(paisa),
            highlighted = index == sample.lastIndex,
        )
    }
}

/**
 * The three-step start for a freshly signed-up shop. Numbered, tappable,
 * and gone the moment there is a medicine or a sale — it never nags.
 */
@Composable
private fun FirstRunCard(
    onAddMedicine: () -> Unit,
    onReceive: () -> Unit,
    onSell: () -> Unit,
) {
    Surface(
        shape = RoundedCornerShape(Radii.card),
        color = MaterialTheme.colorScheme.primaryContainer,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(modifier = Modifier.padding(Spacing.lg)) {
            Text(
                text = stringResource(R.string.firstrun_title),
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold,
                color = MaterialTheme.colorScheme.onPrimaryContainer,
            )
            Spacer(Modifier.height(Spacing.xs))
            Text(
                text = stringResource(R.string.firstrun_note),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onPrimaryContainer.copy(alpha = 0.85f),
            )
            Spacer(Modifier.height(Spacing.md))
            val steps = listOf(
                stringResource(R.string.firstrun_step1) to onAddMedicine,
                stringResource(R.string.firstrun_step2) to onReceive,
                stringResource(R.string.firstrun_step3) to onSell,
            )
            steps.forEachIndexed { index, (label, action) ->
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(Radii.chip))
                        .clickable(onClick = action)
                        .padding(vertical = Spacing.sm),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Box(
                        modifier = Modifier
                            .size(28.dp)
                            .clip(CircleShape)
                            .background(MaterialTheme.colorScheme.primary),
                        contentAlignment = Alignment.Center,
                    ) {
                        Text(
                            text = (index + 1).toString(),
                            style = MaterialTheme.typography.labelLarge,
                            fontWeight = FontWeight.Bold,
                            color = MaterialTheme.colorScheme.onPrimary,
                        )
                    }
                    Spacer(Modifier.width(Spacing.md))
                    Text(
                        text = label,
                        style = MaterialTheme.typography.bodyMedium,
                        fontWeight = FontWeight.Medium,
                        color = MaterialTheme.colorScheme.onPrimaryContainer,
                        modifier = Modifier.weight(1f),
                    )
                    Icon(
                        imageVector = Icons.Filled.ChevronRight,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.onPrimaryContainer.copy(alpha = 0.7f),
                    )
                }
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
    icon: ImageVector? = null,
    /** 4dp Expiry Strip down the left edge — the Stock glance-pattern here. */
    strip: Color? = null,
    onClick: (() -> Unit)? = null,
) {
    Surface(
        shape = RoundedCornerShape(Radii.card),
        color = container,
        modifier = Modifier
            .fillMaxWidth()
            .then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier),
    ) {
        Row(modifier = Modifier.fillMaxWidth()) {
            if (strip != null) {
                Box(
                    modifier = Modifier
                        .width(Sizes.expiryStripWidth)
                        .fillMaxHeight()
                        .background(strip),
                )
            }
        Row(
            modifier = Modifier.weight(1f).padding(Spacing.lg),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (icon != null) {
                Box(
                    modifier = Modifier
                        .size(40.dp)
                        .clip(RoundedCornerShape(Radii.chip))
                        .background(content.copy(alpha = 0.14f)),
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(
                        imageVector = icon,
                        contentDescription = null,
                        tint = content,
                        modifier = Modifier.size(22.dp),
                    )
                }
                Spacer(Modifier.width(Spacing.md))
            }
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
            if (onClick != null) {
                Icon(
                    imageVector = Icons.Filled.ChevronRight,
                    contentDescription = null,
                    tint = content.copy(alpha = 0.7f),
                )
            }
        }
        }
    }
}
