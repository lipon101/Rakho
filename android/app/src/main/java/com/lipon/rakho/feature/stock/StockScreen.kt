package com.lipon.rakho.feature.stock

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
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.DateRange
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Inventory2
import androidx.compose.material.icons.filled.QrCodeScanner
import androidx.compose.material.icons.filled.Schedule
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.OutlinedButton
import com.lipon.rakho.ui.components.RakhoFilterChip
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
import androidx.compose.material3.rememberDatePickerState
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
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.lipon.rakho.R
import com.lipon.rakho.core.model.Medicine
import com.lipon.rakho.core.model.StockFilter
import com.lipon.rakho.core.money.Money
import com.lipon.rakho.core.money.MoneyFormat
import com.lipon.rakho.core.time.DhakaTime
import com.lipon.rakho.core.time.ExpiryStatus
import com.lipon.rakho.data.repo.UpdateBatchRequest
import com.lipon.rakho.data.repo.UpdateMedicineRequest
import com.lipon.rakho.di.RakhoViewModelFactory
import com.lipon.rakho.ui.components.EmptyState
import com.lipon.rakho.ui.components.ExpiryStrip
import com.lipon.rakho.ui.components.RakhoSearchField
import com.lipon.rakho.ui.components.ExpiryStatusPill
import com.lipon.rakho.ui.components.StatusPill
import com.lipon.rakho.ui.theme.Radii
import com.lipon.rakho.ui.theme.Spacing
import com.lipon.rakho.ui.theme.statusNearContainer
import com.lipon.rakho.ui.theme.statusNearText

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun StockScreen(
    onReceive: () -> Unit,
    onScanBarcode: () -> Unit = {},
    initialFilter: StockFilter = StockFilter.ALL,
    viewModel: StockViewModel = viewModel(factory = RakhoViewModelFactory),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val snackbar = remember { SnackbarHostState() }
    var writeOffTarget by remember { mutableStateOf<StockBatchRow?>(null) }

    val writtenOffText = stringResource(R.string.stock_written_off)
    val queuedText = stringResource(R.string.receive_queued)
    val errorText = stringResource(R.string.error_generic)
    val medicineSavedText = stringResource(R.string.stock_medicine_saved)
    val batchSavedText = stringResource(R.string.stock_batch_saved)
    val editQueuedText = stringResource(R.string.common_edit_queued)

    // Edit targets come from collected state so the dialogs recompose reactively
    // (reading a StateFlow.value during composition would not subscribe).
    val editingMedicine = state.editingMedicine
    val editingBatch = state.editingBatch

    // A dashboard alert card lands here with its filter pre-applied, so the
    // tap always shows the actual expiring/low stock — never the full list.
    LaunchedEffect(initialFilter) {
        if (initialFilter != StockFilter.ALL) {
            viewModel.onFilterChange(initialFilter)
        }
    }

    LaunchedEffect(state.message) {
        when (state.message) {
            StockMessage.WrittenOff -> snackbar.showSnackbar(writtenOffText)
            StockMessage.WriteOffQueued -> snackbar.showSnackbar(queuedText)
            StockMessage.MedicineSaved -> snackbar.showSnackbar(medicineSavedText)
            StockMessage.BatchSaved -> snackbar.showSnackbar(batchSavedText)
            StockMessage.EditQueued -> snackbar.showSnackbar(editQueuedText)
            is StockMessage.Failed -> snackbar.showSnackbar(errorText)
            null -> Unit
        }
        if (state.message != null) viewModel.consumeMessage()
    }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = { TopAppBar(
            title = { Text(stringResource(R.string.stock_title)) },
            actions = {
                IconButton(onClick = onScanBarcode) {
                    Icon(
                        imageVector = Icons.Filled.QrCodeScanner,
                        contentDescription = "Scan Barcode",
                    )
                }
            },
        ) },
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
            Box(
                modifier = Modifier.padding(horizontal = Spacing.lg, vertical = Spacing.sm),
            ) {
                RakhoSearchField(
                    value = state.query,
                    onValueChange = viewModel::onQueryChange,
                    hint = stringResource(R.string.stock_search_hint),
                )
            }

            Row(
                modifier = Modifier.padding(horizontal = Spacing.lg),
                horizontalArrangement = Arrangement.spacedBy(Spacing.sm),
            ) {
                RakhoFilterChip(
                    selected = state.filter == StockFilter.ALL,
                    onClick = { viewModel.onFilterChange(StockFilter.ALL) },
                    label = stringResource(R.string.stock_filter_all),
                )
                RakhoFilterChip(
                    selected = state.filter == StockFilter.EXPIRING,
                    onClick = { viewModel.onFilterChange(StockFilter.EXPIRING) },
                    label = stockFilterLabel(
                        base = stringResource(R.string.stock_filter_expiring),
                        count = state.counts.expiring,
                    ),
                )
                RakhoFilterChip(
                    selected = state.filter == StockFilter.EXPIRED,
                    onClick = { viewModel.onFilterChange(StockFilter.EXPIRED) },
                    label = stockFilterLabel(
                        base = stringResource(R.string.stock_filter_expired),
                        count = state.counts.expired,
                    ),
                )
                RakhoFilterChip(
                    selected = state.filter == StockFilter.LOW,
                    onClick = { viewModel.onFilterChange(StockFilter.LOW) },
                    label = stockFilterLabel(
                        base = stringResource(R.string.stock_filter_low),
                        count = state.counts.low,
                    ),
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
                    if (state.isFiltered) {
                        Text(
                            text = stringResource(
                                R.string.stock_of_total,
                                state.groupCount,
                                state.totalGroupCount,
                            ),
                            style = MaterialTheme.typography.labelMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
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
                            onEditMedicine = viewModel::openEditMedicine,
                            onEditBatch = viewModel::openEditBatch,
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

    editingMedicine?.let { medicine ->
        EditMedicineDialog(
            medicine = medicine,
            onDismiss = viewModel::dismissEdit,
            onSave = viewModel::updateMedicine,
        )
    }

    editingBatch?.let { row ->
        EditBatchDialog(
            row = row,
            onDismiss = viewModel::dismissEdit,
            onSave = viewModel::updateBatch,
        )
    }
}

@Composable
private fun stockFilterLabel(base: String, count: Int): String =
    if (count > 0) "$base · $count" else base

@Composable
private fun EditMedicineDialog(
    medicine: Medicine,
    onDismiss: () -> Unit,
    onSave: (UpdateMedicineRequest) -> Unit,
) {
    var brand by remember(medicine.id) { mutableStateOf(medicine.brandName) }
    var generic by remember(medicine.id) { mutableStateOf(medicine.genericName) }
    var strength by remember(medicine.id) { mutableStateOf(medicine.strength) }
    var price by remember(medicine.id) { mutableStateOf(medicine.defaultSellingPrice.toBigDecimal().toPlainString()) }
    var threshold by remember(medicine.id) { mutableStateOf(medicine.lowStockThreshold.toString()) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.stock_edit_medicine)) },
        text = {
            Column(
                modifier = Modifier.verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(Spacing.sm),
            ) {
                OutlinedTextField(
                    value = brand,
                    onValueChange = { brand = it },
                    label = { Text(stringResource(R.string.stock_brand_name)) },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                OutlinedTextField(
                    value = generic,
                    onValueChange = { generic = it },
                    label = { Text(stringResource(R.string.add_medicine_generic)) },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                OutlinedTextField(
                    value = strength,
                    onValueChange = { strength = it },
                    label = { Text(stringResource(R.string.add_medicine_strength)) },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Row(horizontalArrangement = Arrangement.spacedBy(Spacing.sm)) {
                    OutlinedTextField(
                        value = price,
                        onValueChange = { price = it.filter { ch -> ch.isDigit() || ch == '.' } },
                        label = { Text(stringResource(R.string.add_medicine_price)) },
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                        modifier = Modifier.weight(1f),
                    )
                    OutlinedTextField(
                        value = threshold,
                        onValueChange = { threshold = it.filter { ch -> ch.isDigit() }.take(4) },
                        label = { Text(stringResource(R.string.add_medicine_threshold)) },
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        modifier = Modifier.weight(1f),
                    )
                }
            }
        },
        confirmButton = {
            TextButton(
                onClick = {
                    onSave(
                        UpdateMedicineRequest(
                            brandName = brand.trim().ifBlank { null },
                            genericName = generic.trim(),
                            strength = strength.trim(),
                            barcode = medicine.barcode,
                            defaultSellingPrice = Money.parseOrNull(price)?.toBigDecimal()?.toPlainString(),
                            lowStockThreshold = threshold.toIntOrNull()?.coerceIn(1, 9999),
                        ),
                    )
                },
            ) {
                Text(stringResource(R.string.action_save))
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text(stringResource(R.string.action_cancel)) }
        },
    )
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun EditBatchDialog(
    row: StockBatchRow,
    onDismiss: () -> Unit,
    onSave: (UpdateBatchRequest) -> Unit,
) {
    val batch = row.batch
    var batchNumber by remember(batch.id) { mutableStateOf(batch.batchNumber) }
    var expiryMillis by remember(batch.id) {
        mutableStateOf(batch.expiryDate.atStartOfDay(DhakaTime.ZONE).toInstant().toEpochMilli())
    }
    var unitCost by remember(batch.id) { mutableStateOf(batch.unitCost.toBigDecimal().toPlainString()) }
    var sellingPrice by remember(batch.id) { mutableStateOf(batch.sellingPrice.toBigDecimal().toPlainString()) }
    var quantity by remember(batch.id) { mutableStateOf(batch.quantityAvailable.toString()) }
    var datePickerOpen by remember { mutableStateOf(false) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.stock_edit_batch)) },
        text = {
            Column(
                modifier = Modifier.verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(Spacing.sm),
            ) {
                OutlinedTextField(
                    value = batchNumber,
                    onValueChange = { batchNumber = it },
                    label = { Text(stringResource(R.string.receive_batch_number)) },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                // Expiry is picked, never typed: a typo can't mis-date a batch.
                OutlinedButton(
                    onClick = { datePickerOpen = true },
                    shape = RoundedCornerShape(Radii.button),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Icon(Icons.Filled.DateRange, contentDescription = null)
                    Spacer(Modifier.width(Spacing.sm))
                    Text(DhakaTime.format(java.time.Instant.ofEpochMilli(expiryMillis).atZone(DhakaTime.ZONE).toLocalDate()))
                }
                Row(horizontalArrangement = Arrangement.spacedBy(Spacing.sm)) {
                    OutlinedTextField(
                        value = unitCost,
                        onValueChange = { unitCost = it.filter { ch -> ch.isDigit() || ch == '.' } },
                        label = { Text(stringResource(R.string.receive_unit_cost)) },
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                        modifier = Modifier.weight(1f),
                    )
                    OutlinedTextField(
                        value = sellingPrice,
                        onValueChange = { sellingPrice = it.filter { ch -> ch.isDigit() || ch == '.' } },
                        label = { Text(stringResource(R.string.receive_selling_price)) },
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                        modifier = Modifier.weight(1f),
                    )
                }
                OutlinedTextField(
                    value = quantity,
                    onValueChange = { quantity = it.filter { ch -> ch.isDigit() }.take(6) },
                    label = { Text(stringResource(R.string.stock_counted_quantity)) },
                    supportingText = {
                        Text(stringResource(R.string.stock_counted_hint, batch.quantityAvailable))
                    },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    modifier = Modifier.fillMaxWidth(),
                )
            }
        },
        confirmButton = {
            TextButton(
                onClick = {
                    onSave(
                        UpdateBatchRequest(
                            batchNumber = batchNumber.trim().ifBlank { null },
                            expiryDate = java.time.Instant.ofEpochMilli(expiryMillis)
                                .atZone(DhakaTime.ZONE).toLocalDate().toString(),
                            unitCost = Money.parseOrNull(unitCost)?.toBigDecimal()?.toPlainString(),
                            sellingPrice = Money.parseOrNull(sellingPrice)?.toBigDecimal()?.toPlainString(),
                            quantityAvailable = quantity.toIntOrNull(),
                        ),
                    )
                },
            ) {
                Text(stringResource(R.string.action_save))
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text(stringResource(R.string.action_cancel)) }
        },
    )

    if (datePickerOpen) {
        val pickerState = rememberDatePickerState(initialSelectedDateMillis = expiryMillis)
        DatePickerDialog(
            onDismissRequest = { datePickerOpen = false },
            confirmButton = {
                TextButton(
                    onClick = {
                        pickerState.selectedDateMillis?.let { expiryMillis = it }
                        datePickerOpen = false
                    },
                ) {
                    Text(stringResource(R.string.action_ok))
                }
            },
            dismissButton = {
                TextButton(onClick = { datePickerOpen = false }) {
                    Text(stringResource(R.string.action_cancel))
                }
            },
        ) {
            DatePicker(state = pickerState)
        }
    }
}

@Composable
private fun StockGroupCard(
    group: StockGroup,
    onWriteOff: (StockBatchRow) -> Unit,
    onEditMedicine: (Medicine) -> Unit,
    onEditBatch: (StockBatchRow) -> Unit,
) {
    Surface(
        shape = RoundedCornerShape(Radii.card),
        color = MaterialTheme.colorScheme.surface,
        tonalElevation = 1.dp,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(modifier = Modifier.fillMaxWidth()) {
            ExpiryStrip()
            Column(modifier = Modifier.weight(1f).padding(Spacing.lg)) {
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
                    Spacer(Modifier.width(Spacing.xs))
                    IconButton(onClick = { onEditMedicine(group.medicine) }) {
                        Icon(
                            imageVector = Icons.Filled.Edit,
                            contentDescription = stringResource(R.string.stock_edit_medicine),
                            tint = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }

                if (group.isLow) {
                    Spacer(Modifier.height(Spacing.sm))
                    StatusPill(
                        text = stringResource(R.string.dashboard_low_stock),
                        // Amber: running low needs attention. Teal read as
                        // "healthy stock", which is the opposite of the point.
                        containerColor = statusNearContainer(),
                        contentColor = statusNearText(),
                        icon = Icons.Filled.Inventory2,
                    )
                }

                Spacer(Modifier.height(Spacing.md))
                group.batches.forEach { row ->
                    BatchRow(
                        row = row,
                        onWriteOff = { onWriteOff(row) },
                        onEdit = { onEditBatch(row) },
                    )
                }
            }
        }
    }
}

@Composable
private fun BatchRow(row: StockBatchRow, onWriteOff: () -> Unit, onEdit: () -> Unit) {
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
                // The app-wide chip: same label rules and palette as POS,
                // Dashboard and Dues.
                ExpiryStatusPill(status = row.status, daysUntilExpiry = row.daysUntilExpiry)
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
        IconButton(onClick = onEdit) {
            Icon(
                imageVector = Icons.Filled.Edit,
                contentDescription = stringResource(R.string.stock_edit_batch),
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}
