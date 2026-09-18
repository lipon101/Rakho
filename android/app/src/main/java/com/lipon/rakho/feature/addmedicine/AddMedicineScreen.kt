package com.lipon.rakho.feature.addmedicine

import androidx.compose.foundation.layout.Arrangement
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
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
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
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
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
import com.lipon.rakho.core.model.CatalogItem
import com.lipon.rakho.di.RakhoViewModelFactory
import com.lipon.rakho.ui.components.SectionHeader
import com.lipon.rakho.ui.theme.Radii
import com.lipon.rakho.ui.theme.Spacing

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AddMedicineScreen(
    onSaved: () -> Unit,
    viewModel: AddMedicineViewModel = viewModel(factory = RakhoViewModelFactory),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val snackbar = remember { SnackbarHostState() }

    val savedText = stringResource(R.string.add_medicine_saved)
    val queuedText = stringResource(R.string.receive_queued)
    val priceRequired = stringResource(R.string.add_medicine_price)
    val nameRequired = stringResource(R.string.add_medicine_hint)
    val genericError = stringResource(R.string.error_generic)

    LaunchedEffect(state.message) {
        when (val message = state.message) {
            is AddMedicineMessage.Saved -> {
                snackbar.showSnackbar(if (message.queued) queuedText else savedText)
                viewModel.consumeMessage()
                onSaved()
            }
            AddMedicineMessage.PriceRequired -> {
                snackbar.showSnackbar(priceRequired)
                viewModel.consumeMessage()
            }
            AddMedicineMessage.NameRequired -> {
                snackbar.showSnackbar(nameRequired)
                viewModel.consumeMessage()
            }
            is AddMedicineMessage.Failed -> {
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
                title = { Text(stringResource(R.string.add_medicine_title)) },
                navigationIcon = {
                    IconButton(onClick = onSaved) {
                        Icon(Icons.Filled.Close, contentDescription = stringResource(R.string.cd_close))
                    }
                },
            )
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
            item {
                OutlinedTextField(
                    value = state.query,
                    onValueChange = viewModel::onQueryChange,
                    label = { Text(stringResource(R.string.add_medicine_search)) },
                    placeholder = { Text(stringResource(R.string.add_medicine_hint)) },
                    leadingIcon = { Icon(Icons.Filled.Search, contentDescription = null) },
                    trailingIcon = {
                        if (state.searching) {
                            CircularProgressIndicator(
                                modifier = Modifier.size(18.dp),
                                strokeWidth = 2.dp,
                            )
                        } else if (state.selected != null) {
                            IconButton(onClick = viewModel::clearSelection) {
                                Icon(
                                    imageVector = Icons.Filled.Close,
                                    contentDescription = stringResource(R.string.cd_close),
                                )
                            }
                        }
                    },
                    singleLine = true,
                    shape = RoundedCornerShape(Radii.button),
                    modifier = Modifier.fillMaxWidth(),
                )
            }

            if (state.searching && state.results.isEmpty()) {
                item {
                    Text(
                        text = stringResource(R.string.add_medicine_searching),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }

            items(state.results, key = { it.id }) { item ->
                CatalogRow(item = item, onPick = viewModel::select)
            }

            if (!state.searching &&
                state.results.isEmpty() &&
                state.query.trim().length >= 2 &&
                state.selected == null &&
                !state.manualMode
            ) {
                item {
                    Column {
                        Text(
                            text = stringResource(R.string.add_medicine_no_results, state.query),
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        TextButton(onClick = { viewModel.enableManualMode(true) }) {
                            Text(stringResource(R.string.add_medicine_manual))
                        }
                    }
                }
            }

            if (state.selected != null || state.manualMode) {
                item { SectionHeader(stringResource(R.string.add_medicine_title)) }

                if (state.manualMode) {
                    item {
                        OutlinedTextField(
                            value = state.manualName,
                            onValueChange = { viewModel.onManualChange(name = it) },
                            label = { Text(stringResource(R.string.receive_medicine)) },
                            singleLine = true,
                            modifier = Modifier.fillMaxWidth(),
                        )
                    }
                    item {
                        OutlinedTextField(
                            value = state.manualGeneric,
                            onValueChange = { viewModel.onManualChange(generic = it) },
                            label = { Text(stringResource(R.string.add_medicine_generic)) },
                            singleLine = true,
                            modifier = Modifier.fillMaxWidth(),
                        )
                    }
                    item {
                        Row(horizontalArrangement = Arrangement.spacedBy(Spacing.md)) {
                            OutlinedTextField(
                                value = state.manualStrength,
                                onValueChange = { viewModel.onManualChange(strength = it) },
                                label = { Text(stringResource(R.string.add_medicine_strength)) },
                                singleLine = true,
                                modifier = Modifier.weight(1f),
                            )
                            OutlinedTextField(
                                value = state.manualDosageForm,
                                onValueChange = { viewModel.onManualChange(dosageForm = it) },
                                label = { Text(stringResource(R.string.add_medicine_form)) },
                                singleLine = true,
                                modifier = Modifier.weight(1f),
                            )
                        }
                    }
                } else {
                    item {
                        Surface(
                            shape = RoundedCornerShape(Radii.card),
                            color = MaterialTheme.colorScheme.primaryContainer,
                            modifier = Modifier.fillMaxWidth(),
                        ) {
                            Column(modifier = Modifier.padding(Spacing.lg)) {
                                Text(
                                    text = state.selected?.displayName.orEmpty(),
                                    style = MaterialTheme.typography.titleSmall,
                                    fontWeight = FontWeight.Bold,
                                    color = MaterialTheme.colorScheme.onPrimaryContainer,
                                )
                                Text(
                                    text = listOfNotNull(
                                        state.selected?.genericName,
                                        state.selected?.dosageForm,
                                        state.selected?.manufacturerName,
                                    ).filter { it.isNotBlank() }.joinToString(" · "),
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onPrimaryContainer.copy(alpha = 0.9f),
                                )
                            }
                        }
                    }
                }

                item {
                    Row(horizontalArrangement = Arrangement.spacedBy(Spacing.md)) {
                        OutlinedTextField(
                            value = state.priceText,
                            onValueChange = viewModel::onPriceChange,
                            label = { Text(stringResource(R.string.add_medicine_price)) },
                            singleLine = true,
                            keyboardOptions = KeyboardOptions(
                                keyboardType = KeyboardType.Decimal,
                                imeAction = ImeAction.Next,
                            ),
                            modifier = Modifier.weight(1f),
                        )
                        OutlinedTextField(
                            value = state.thresholdText,
                            onValueChange = viewModel::onThresholdChange,
                            label = { Text(stringResource(R.string.add_medicine_threshold)) },
                            singleLine = true,
                            keyboardOptions = KeyboardOptions(
                                keyboardType = KeyboardType.Number,
                                imeAction = ImeAction.Done,
                            ),
                            modifier = Modifier.weight(1f),
                        )
                    }
                }

                item {
                    Button(
                        onClick = viewModel::save,
                        enabled = state.canSave && !state.busy,
                        shape = RoundedCornerShape(Radii.button),
                        modifier = Modifier.fillMaxWidth().height(52.dp),
                    ) {
                        Text(
                            text = stringResource(R.string.add_medicine_save),
                            fontWeight = FontWeight.Bold,
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun CatalogRow(item: CatalogItem, onPick: (CatalogItem) -> Unit) {
    Surface(
        shape = RoundedCornerShape(Radii.card),
        color = MaterialTheme.colorScheme.surface,
        tonalElevation = 1.dp,
        onClick = { onPick(item) },
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(
            modifier = Modifier.padding(Spacing.lg),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = item.displayName,
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.SemiBold,
                )
                Spacer(Modifier.height(Spacing.xs))
                Text(
                    text = listOf(item.genericName, item.dosageForm)
                        .filter { it.isNotBlank() }
                        .joinToString(" · "),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                if (item.manufacturerName.isNotBlank()) {
                    Text(
                        text = item.manufacturerName,
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            Spacer(Modifier.width(Spacing.sm))
            Text(
                text = "+",
                style = MaterialTheme.typography.titleLarge,
                color = MaterialTheme.colorScheme.primary,
                fontWeight = FontWeight.Bold,
            )
        }
    }
}
