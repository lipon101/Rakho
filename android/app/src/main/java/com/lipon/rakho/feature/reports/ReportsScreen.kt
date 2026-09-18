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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Star
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
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
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.lipon.rakho.R
import com.lipon.rakho.core.money.MoneyFormat
import com.lipon.rakho.core.time.DhakaTime
import com.lipon.rakho.di.RakhoViewModelFactory
import com.lipon.rakho.ui.components.EmptyState
import com.lipon.rakho.ui.components.KpiTile
import com.lipon.rakho.ui.components.SectionHeader
import com.lipon.rakho.ui.theme.Radii
import com.lipon.rakho.ui.theme.Spacing
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
                Row(horizontalArrangement = Arrangement.spacedBy(Spacing.sm)) {
                    FilterChip(
                        selected = state.period == ReportPeriod.TODAY,
                        onClick = { viewModel.onPeriodChange(ReportPeriod.TODAY) },
                        label = { Text(stringResource(R.string.reports_today)) },
                    )
                    FilterChip(
                        selected = state.period == ReportPeriod.WEEK,
                        onClick = { viewModel.onPeriodChange(ReportPeriod.WEEK) },
                        label = { Text(stringResource(R.string.reports_week)) },
                    )
                    FilterChip(
                        selected = state.period == ReportPeriod.MONTH,
                        onClick = { viewModel.onPeriodChange(ReportPeriod.MONTH) },
                        label = { Text(stringResource(R.string.reports_month)) },
                    )
                }
            }

            item {
                Surface(
                    shape = RoundedCornerShape(Radii.card),
                    color = MaterialTheme.colorScheme.primaryContainer,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Column(modifier = Modifier.padding(Spacing.xl)) {
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
                        Spacer(Modifier.height(Spacing.sm))
                        Text(
                            text = stringResource(R.string.dashboard_sale_count, state.billCount),
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onPrimaryContainer.copy(alpha = 0.9f),
                        )
                    }
                }
            }

            item {
                Row(horizontalArrangement = Arrangement.spacedBy(Spacing.md)) {
                    KpiTile(
                        label = stringResource(R.string.reports_bills),
                        value = state.billCount.toString(),
                        icon = Icons.Filled.Star,
                        modifier = Modifier.weight(1f),
                    )
                    KpiTile(
                        label = stringResource(R.string.reports_items_sold),
                        value = state.itemCount.toString(),
                        icon = Icons.Filled.Star,
                        modifier = Modifier.weight(1f),
                    )
                }
            }

            item {
                KpiTile(
                    label = stringResource(R.string.reports_average_bill),
                    value = MoneyFormat.format(state.averageBill),
                    icon = Icons.Filled.Star,
                    modifier = Modifier.fillMaxWidth(),
                )
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
                    modifier = Modifier.fillMaxWidth().height(52.dp),
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
                        icon = Icons.Filled.Star,
                    )
                }
            } else {
                items(state.topItems, key = { it.name }) { item ->
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
                                    text = item.name,
                                    style = MaterialTheme.typography.bodyLarge,
                                    fontWeight = FontWeight.SemiBold,
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
                    }
                }
            }
        }
    }
}

/** Kept for callers that need the formatted report title. */
@Composable
fun reportPeriodLabel(period: ReportPeriod): String = stringResource(
    when (period) {
        ReportPeriod.TODAY -> R.string.reports_today
        ReportPeriod.WEEK -> R.string.reports_week
        ReportPeriod.MONTH -> R.string.reports_month
    },
)
