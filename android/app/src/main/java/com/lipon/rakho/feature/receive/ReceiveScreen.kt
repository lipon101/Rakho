package com.lipon.rakho.feature.receive

import androidx.compose.foundation.BorderStroke
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
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.DateRange
import androidx.compose.material3.Button
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.ExperimentalMaterial3Api
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
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.lipon.rakho.R
import com.lipon.rakho.core.model.Medicine
import com.lipon.rakho.core.time.DhakaTime
import com.lipon.rakho.di.RakhoViewModelFactory
import com.lipon.rakho.ui.components.SectionHeader
import com.lipon.rakho.ui.theme.Radii
import com.lipon.rakho.ui.theme.Spacing
import java.time.Instant

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ReceiveScreen(
    onSaved: () -> Unit,
    viewModel: ReceiveViewModel = viewModel(factory = RakhoViewModelFactory),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val snackbar = remember { SnackbarHostState() }
    var datePickerOpen by remember { mutableStateOf(false) }

    val savedText = stringResource(R.string.receive_saved)
    val queuedText = stringResource(R.string.receive_queued)
    val pastExpiryText = stringResource(R.string.receive_expiry_past)
    val priceBelowCostText = stringResource(R.string.receive_price_below_cost)
    val pickMedicineText = stringResource(R.string.receive_pick_medicine)
    val genericError = stringResource(R.string.error_generic)

    LaunchedEffect(state.message) {
        when (val message = state.message) {
            ReceiveMessage.Synced -> {
                snackbar.showSnackbar(savedText)
                viewModel.consumeMessage()
                onSaved()
            }
            ReceiveMessage.Queued -> {
                snackbar.showSnackbar(queuedText)
                viewModel.consumeMessage()
                onSaved()
            }
            is ReceiveMessage.Invalid -> {
                val text = when (message.reason) {
                    ReceiveValidation.PastExpiry, ReceiveValidation.BadExpiry -> pastExpiryText
                    ReceiveValidation.PriceBelowCost -> priceBelowCostText
                    ReceiveValidation.NoMedicine -> pickMedicineText
                    else -> genericError
                }
                snackbar.showSnackbar(text)
                viewModel.consumeMessage()
            }
            is ReceiveMessage.Failed -> {
                snackbar.showSnackbar(genericError)
                viewModel.consumeMessage()
            }
            null -> Unit
        }
    }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            TopAppBar(
                title = { Text(stringResource(R.string.receive_title)) },
                navigationIcon = {
                    IconButton(onClick = onSaved) {
                        Icon(Icons.Filled.Close, contentDescription = stringResource(R.string.cd_close))
                    }
                },
            )
        },
        bottomBar = {
            Surface(color = MaterialTheme.colorScheme.surface, tonalElevation = 3.dp) {
                Row(
                    modifier = Modifier.fillMaxWidth().padding(Spacing.lg),
                    horizontalArrangement = Arrangement.spacedBy(Spacing.md),
                ) {
                    TextButton(
                        onClick = viewModel::addLine,
                        modifier = Modifier.weight(1f),
                    ) {
                        Text(stringResource(R.string.receive_add_item))
                    }
                    Button(
                        onClick = viewModel::save,
                        enabled = state.canSave && !state.busy,
                        shape = RoundedCornerShape(Radii.button),
                        modifier = Modifier.weight(1f).height(52.dp),
                    ) {
                        Text(
                            text = stringResource(R.string.receive_save),
                            fontWeight = FontWeight.Bold,
                        )
                    }
                }
            }
        },
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
            if (state.itemLabels.isNotEmpty()) {
                item { SectionHeader(stringResource(R.string.receive_title)) }
                items(state.itemLabels.withIndex().toList(), key = { it.index }) { indexed ->
                    Surface(
                        shape = RoundedCornerShape(Radii.card),
                        color = MaterialTheme.colorScheme.surfaceVariant,
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Row(
                            modifier = Modifier.padding(Spacing.md),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Text(
                                text = indexed.value,
                                style = MaterialTheme.typography.bodySmall,
                                modifier = Modifier.weight(1f),
                            )
                            IconButton(onClick = { viewModel.removeLine(indexed.index) }) {
                                Icon(
                                    imageVector = Icons.Filled.Close,
                                    contentDescription = stringResource(R.string.cd_close),
                                )
                            }
                        }
                    }
                }
            }

            item { SectionHeader(stringResource(R.string.receive_medicine)) }

            item {
                OutlinedTextField(
                    value = state.draft.medicineName,
                    onValueChange = { value ->
                        viewModel.onDraftChange {
                            it.copy(medicineName = value, medicineId = "")
                        }
                    },
                    label = { Text(stringResource(R.string.receive_medicine)) },
                    placeholder = { Text(stringResource(R.string.add_medicine_hint)) },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
            }

            items(state.medicineMatches, key = { it.id }) { medicine ->
                MedicineSuggestion(medicine = medicine, onPick = viewModel::selectMedicine)
            }

            item {
                OutlinedTextField(
                    value = state.draft.batchNumber,
                    onValueChange = { value ->
                        viewModel.onDraftChange { it.copy(batchNumber = value) }
                    },
                    label = { Text(stringResource(R.string.receive_batch_number)) },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
            }

            item {
                // A tap target rather than a text field: expiry dates are picked,
                // never typed, so a typo can never mis-date a batch.
                Surface(
                    shape = RoundedCornerShape(Radii.button),
                    color = MaterialTheme.colorScheme.surface,
                    border = BorderStroke(1.dp, MaterialTheme.colorScheme.outline),
                    onClick = { datePickerOpen = true },
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Row(
                        modifier = Modifier.padding(Spacing.lg),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text(
                                text = stringResource(R.string.receive_expiry),
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                            Spacer(Modifier.height(Spacing.xs))
                            Text(
                                text = state.draft.expiryText.ifBlank {
                                    stringResource(R.string.receive_expiry_hint)
                                },
                                style = MaterialTheme.typography.bodyLarge,
                            )
                        }
                        Icon(
                            imageVector = Icons.Filled.DateRange,
                            contentDescription = stringResource(R.string.receive_expiry),
                            tint = MaterialTheme.colorScheme.primary,
                        )
                    }
                }
            }

            item {
                Row(horizontalArrangement = Arrangement.spacedBy(Spacing.md)) {
                    OutlinedTextField(
                        value = state.draft.quantityText,
                        onValueChange = { value ->
                            viewModel.onDraftChange {
                                it.copy(quantityText = value.filter { char -> char.isDigit() })
                            }
                        },
                        label = { Text(stringResource(R.string.receive_quantity)) },
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        modifier = Modifier.weight(1f),
                    )
                    OutlinedTextField(
                        value = state.draft.supplier,
                        onValueChange = { value -> viewModel.onDraftChange { it.copy(supplier = value) } },
                        label = { Text(stringResource(R.string.receive_supplier)) },
                        singleLine = true,
                        modifier = Modifier.weight(1f),
                    )
                }
            }

            item {
                Row(horizontalArrangement = Arrangement.spacedBy(Spacing.md)) {
                    OutlinedTextField(
                        value = state.draft.unitCostText,
                        onValueChange = { value ->
                            viewModel.onDraftChange { it.copy(unitCostText = value.filterDecimal()) }
                        },
                        label = { Text(stringResource(R.string.receive_unit_cost)) },
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                        modifier = Modifier.weight(1f),
                    )
                    OutlinedTextField(
                        value = state.draft.sellingPriceText,
                        onValueChange = { value ->
                            viewModel.onDraftChange { it.copy(sellingPriceText = value.filterDecimal()) }
                        },
                        label = { Text(stringResource(R.string.receive_selling_price)) },
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(
                            keyboardType = KeyboardType.Decimal,
                            imeAction = ImeAction.Done,
                        ),
                        modifier = Modifier.weight(1f),
                    )
                }
            }
        }
    }

    if (datePickerOpen) {
        val pickerState = rememberDatePickerState(
            initialSelectedDateMillis = System.currentTimeMillis(),
        )
        DatePickerDialog(
            onDismissRequest = { datePickerOpen = false },
            confirmButton = {
                TextButton(
                    onClick = {
                        pickerState.selectedDateMillis?.let { millis ->
                            val date = Instant.ofEpochMilli(millis)
                                .atZone(DhakaTime.ZONE)
                                .toLocalDate()
                            viewModel.onDraftChange { it.copy(expiryText = date.toString()) }
                        }
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
private fun MedicineSuggestion(medicine: Medicine, onPick: (Medicine) -> Unit) {
    Surface(
        shape = RoundedCornerShape(Radii.card),
        color = MaterialTheme.colorScheme.surfaceVariant,
        onClick = { onPick(medicine) },
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(
            modifier = Modifier.padding(Spacing.md),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = medicine.displayName,
                    style = MaterialTheme.typography.bodyMedium,
                    fontWeight = FontWeight.SemiBold,
                )
                if (medicine.genericName.isNotBlank()) {
                    Text(
                        text = medicine.genericName,
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            Spacer(Modifier.width(Spacing.sm))
            Text(
                text = medicine.availableQuantity.toString(),
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

/** Digits and a single decimal point only — no keyboards tricks, no crashes. */
private fun String.filterDecimal(): String {
    val cleaned = filter { it.isDigit() || it == '.' }
    val firstDot = cleaned.indexOf('.')
    if (firstDot < 0) return cleaned.take(9)
    val head = cleaned.substring(0, firstDot + 1)
    val tail = cleaned.substring(firstDot + 1).filter { it.isDigit() }.take(2)
    return (head + tail).take(9)
}

