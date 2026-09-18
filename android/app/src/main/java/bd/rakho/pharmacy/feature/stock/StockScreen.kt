package bd.rakho.pharmacy.feature.stock

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import bd.rakho.pharmacy.R
import bd.rakho.pharmacy.core.model.StockFilter
import bd.rakho.pharmacy.core.money.MoneyFormat
import bd.rakho.pharmacy.core.time.DhakaTime
import bd.rakho.pharmacy.core.time.ExpiryStatus
import bd.rakho.pharmacy.di.RakhoViewModelFactory
import bd.rakho.pharmacy.ui.components.EmptyState
import bd.rakho.pharmacy.ui.components.StatusPill
import bd.rakho.pharmacy.ui.theme.Radii
import bd.rakho.pharmacy.ui.theme.Spacing

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun StockScreen(
    onReceive: () -> Unit,
    viewModel: StockViewModel = viewModel(factory = RakhoViewModelFactory),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val snackbar = remember { SnackbarHostState() }
    var writeOffTarget by remember { mutableStateOf<StockBatchRow?>(null) }

    val writtenOffText = stringResource(R.string.stock_written_off)
    val queuedText = stringResource(R.string.receive_queued)
    val errorText = stringResource(R.string.error_generic)

    LaunchedEffect(state.message) {
        when (state.message) {
            StockMessage.WrittenOff -> snackbar.showSnackbar(writtenOffText)
            StockMessage.WriteOffQueued -> snackbar.showSnackbar(queuedText)
            is StockMessage.Failed -> snackbar.showSnackbar(errorText)
            null -> Unit
        }
        if (state.message != null) viewModel.consumeMessage()
    }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = { TopAppBar(title = { Text(stringResource(R.string.stock_title)) }) },
        floatingActionButton = {
            Button(
                onClick = onReceive,
                shape = RoundedCornerShape(Radii.button),
                modifier = Modifier.padding(Spacing.lg),
            ) {
                Icon(Icons.Filled.Add, contentDescription = null)
                Spacer(Modifier.width(Spacing.sm))
                Text(
                    text = stringResource(R.string.action_receive),
                    fontWeight = FontWeight.Bold,
                )
            }
        },
    ) { padding ->
        Column(modifier = Modifier.fillMaxSize().padding(padding)) {
            OutlinedTextField(
                value = state.query,
                onValueChange = viewModel::onQueryChange,
                placeholder = { Text(stringResource(R.string.stock_search_hint)) },
                leadingIcon = { Icon(Icons.Filled.Search, contentDescription = null) },
                trailingIcon = {
                    if (state.query.isNotEmpty()) {
                        IconButton(onClick = { viewModel.onQueryChange("") }) {
                            Icon(Icons.Filled.Close, contentDescription = stringResource(R.string.cd_close))
                        }
                    }
                },
                singleLine = true,
                shape = RoundedCornerShape(Radii.button),
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = Spacing.lg, vertical = Spacing.sm),
            )

            Row(
                modifier = Modifier.padding(horizontal = Spacing.lg),
                horizontalArrangement = Arrangement.spacedBy(Spacing.sm),
            ) {
                FilterChip(
                    selected = state.filter == StockFilter.ALL,
                    onClick = { viewModel.onFilterChange(StockFilter.ALL) },
                    label = { Text(stringResource(R.string.stock_filter_all)) },
                )
                FilterChip(
                    selected = state.filter == StockFilter.EXPIRING,
                    onClick = { viewModel.onFilterChange(StockFilter.EXPIRING) },
                    label = { Text(stringResource(R.string.stock_filter_expiring)) },
                )
                FilterChip(
                    selected = state.filter == StockFilter.EXPIRED,
                    onClick = { viewModel.onFilterChange(StockFilter.EXPIRED) },
                    label = { Text(stringResource(R.string.stock_filter_expired)) },
                )
                FilterChip(
                    selected = state.filter == StockFilter.LOW,
                    onClick = { viewModel.onFilterChange(StockFilter.LOW) },
                    label = { Text(stringResource(R.string.stock_filter_low)) },
                )
            }

            Spacer(Modifier.height(Spacing.sm))
            Surface(
                color = MaterialTheme.colorScheme.surfaceVariant,
                shape = RoundedCornerShape(Radii.chip),
                modifier = Modifier.padding(horizontal = Spacing.lg),
            ) {
                Row(
                    modifier = Modifier.padding(horizontal = Spacing.lg, vertical = Spacing.sm),
                    horizontalArrangement = Arrangement.spacedBy(Spacing.lg),
                ) {
                    Text(
                        text = stringResource(R.string.stock_units, state.totalUnits),
                        style = MaterialTheme.typography.labelMedium,
                    )
                    Text(
                        text = MoneyFormat.format(state.totalValue),
                        style = MaterialTheme.typography.labelMedium,
                        fontWeight = FontWeight.SemiBold,
                    )
                }
            }

            if (state.groups.isEmpty()) {
                EmptyState(
                    title = stringResource(R.string.stock_empty),
                    body = stringResource(R.string.action_receive_hint),
                    icon = Icons.AutoMirrored.Filled.List,
                )
            } else {
                LazyColumn(
                    contentPadding = PaddingValues(
                        start = Spacing.lg,
                        end = Spacing.lg,
                        top = Spacing.md,
                        bottom = 96.dp,
                    ),
                    verticalArrangement = Arrangement.spacedBy(Spacing.md),
                ) {
                    items(state.groups, key = { it.medicine.id }) { group ->
                        StockGroupCard(
                            group = group,
                            onWriteOff = { writeOffTarget = it },
                        )
                    }
                }
            }
        }
    }

    writeOffTarget?.let { target ->
        AlertDialog(
            onDismissRequest = { writeOffTarget = null },
            title = { Text(stringResource(R.string.stock_write_off)) },
            text = {
                Text(
                    stringResource(
                        R.string.stock_write_off_confirm,
                        target.batch.batchNumber.ifBlank { "-" },
                    ),
                )
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        viewModel.writeOff(target.batch.id, "expired")
                        writeOffTarget = null
                    },
                ) {
                    Text(stringResource(R.string.action_confirm))
                }
            },
            dismissButton = {
                TextButton(onClick = { writeOffTarget = null }) {
                    Text(stringResource(R.string.action_cancel))
                }
            },
        )
    }
}

@Composable
private fun StockGroupCard(group: StockGroup, onWriteOff: (StockBatchRow) -> Unit) {
    Surface(
        shape = RoundedCornerShape(Radii.card),
        color = MaterialTheme.colorScheme.surface,
        tonalElevation = 1.dp,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(modifier = Modifier.padding(Spacing.lg)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = group.medicine.displayName,
                        style = MaterialTheme.typography.titleSmall,
                        fontWeight = FontWeight.SemiBold,
                    )
                    if (group.medicine.genericName.isNotBlank()) {
                        Text(
                            text = group.medicine.genericName,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
                Column(horizontalAlignment = Alignment.End) {
                    Text(
                        text = stringResource(R.string.stock_units, group.totalUnits),
                        style = MaterialTheme.typography.titleSmall,
                        fontWeight = FontWeight.Bold,
                    )
                    Text(
                        text = MoneyFormat.format(group.totalValue),
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }

            if (group.isLow) {
                Spacer(Modifier.height(Spacing.sm))
                StatusPill(
                    text = stringResource(R.string.dashboard_low_stock),
                    containerColor = MaterialTheme.colorScheme.tertiaryContainer,
                    contentColor = MaterialTheme.colorScheme.onTertiaryContainer,
                )
            }

            Spacer(Modifier.height(Spacing.md))
            group.batches.forEach { row ->
                BatchRow(row = row, onWriteOff = { onWriteOff(row) })
            }
        }
    }
}

@Composable
private fun BatchRow(row: StockBatchRow, onWriteOff: () -> Unit) {
    val label = when {
        row.status == ExpiryStatus.EXPIRED ->
            stringResource(R.string.stock_expired_days, -row.daysUntilExpiry)
        row.daysUntilExpiry == 0L -> stringResource(R.string.stock_expires_today)
        else -> stringResource(R.string.stock_expires_in, row.daysUntilExpiry)
    }
    val container = when (row.status) {
        ExpiryStatus.EXPIRED -> MaterialTheme.colorScheme.errorContainer
        ExpiryStatus.EXPIRES_TODAY -> MaterialTheme.colorScheme.errorContainer
        ExpiryStatus.EXPIRING_SOON -> MaterialTheme.colorScheme.tertiaryContainer
        ExpiryStatus.HEALTHY -> MaterialTheme.colorScheme.surfaceVariant
    }
    val content = when (row.status) {
        ExpiryStatus.EXPIRED, ExpiryStatus.EXPIRES_TODAY -> MaterialTheme.colorScheme.onErrorContainer
        ExpiryStatus.EXPIRING_SOON -> MaterialTheme.colorScheme.onTertiaryContainer
        ExpiryStatus.HEALTHY -> MaterialTheme.colorScheme.onSurfaceVariant
    }

    Row(
        modifier = Modifier.fillMaxWidth().padding(vertical = Spacing.xs),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = stringResource(R.string.stock_batch) + " " +
                    row.batch.batchNumber.ifBlank { "-" } +
                    " · " + DhakaTime.format(row.batch.expiryDate),
                style = MaterialTheme.typography.bodySmall,
            )
            Spacer(Modifier.height(Spacing.xs))
            Row(verticalAlignment = Alignment.CenterVertically) {
                StatusPill(text = label, containerColor = container, contentColor = content)
                Spacer(Modifier.width(Spacing.sm))
                Text(
                    text = stringResource(R.string.stock_units, row.batch.quantityAvailable),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        if (row.batch.quantityAvailable > 0 && row.status != ExpiryStatus.HEALTHY) {
            TextButton(onClick = onWriteOff) {
                Text(stringResource(R.string.stock_write_off))
            }
        }
    }
}
