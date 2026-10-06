package com.lipon.rakho.feature.dues

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
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Handshake
import androidx.compose.material.icons.filled.Person
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
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
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.lipon.rakho.R
import com.lipon.rakho.core.model.CustomerDue
import com.lipon.rakho.core.money.Money
import com.lipon.rakho.core.money.MoneyFormat
import com.lipon.rakho.di.RakhoViewModelFactory
import com.lipon.rakho.ui.charts.SegmentedBar
import com.lipon.rakho.ui.charts.Segment
import com.lipon.rakho.ui.components.EmptyState
import com.lipon.rakho.ui.components.SectionHeader
import com.lipon.rakho.ui.theme.Radii
import com.lipon.rakho.ui.theme.Spacing
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DuesScreen(
    onBack: () -> Unit,
    viewModel: DuesViewModel = viewModel(factory = RakhoViewModelFactory),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val snackbar = remember { SnackbarHostState() }
    val settledTemplate = stringResource(R.string.dues_settled_toast)

    LaunchedEffect(state.message) {
        when (val msg = state.message) {
            is DuesMessage.Settled -> {
                snackbar.showSnackbar(
                    settledTemplate.replace("%1\$s", msg.customer)
                        .replace("%2\$s", MoneyFormat.format(msg.amount)),
                )
                viewModel.consumeMessage()
            }
            is DuesMessage.Invalid -> {
                snackbar.showSnackbar(msg.reason)
                viewModel.consumeMessage()
            }
            null -> Unit
        }
    }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            TopAppBar(
                title = { Text(stringResource(R.string.dues_title)) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(
                            Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = stringResource(R.string.action_back),
                        )
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
                Card(
                    shape = RoundedCornerShape(Radii.card),
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.primaryContainer,
                    ),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Column(modifier = Modifier.padding(Spacing.xl)) {
                        Text(
                            text = stringResource(R.string.dues_total_label),
                            style = MaterialTheme.typography.labelLarge,
                            color = MaterialTheme.colorScheme.onPrimaryContainer.copy(alpha = 0.8f),
                        )
                        Text(
                            text = MoneyFormat.format(state.total),
                            style = MaterialTheme.typography.displaySmall,
                            fontWeight = FontWeight.Bold,
                            color = MaterialTheme.colorScheme.onPrimaryContainer,
                        )
                        Text(
                            text = stringResource(R.string.dues_customer_count, state.customerCount),
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onPrimaryContainer.copy(alpha = 0.85f),
                        )
                        if (state.total.paisa > 0) {
                            Spacer(Modifier.height(Spacing.lg))
                            Text(
                                text = stringResource(R.string.dues_aging),
                                style = MaterialTheme.typography.labelMedium,
                                color = MaterialTheme.colorScheme.onPrimaryContainer.copy(alpha = 0.8f),
                            )
                            Spacer(Modifier.height(Spacing.xs))
                            SegmentedBar(
                                segments = listOf(
                                    Segment(
                                        stringResource(R.string.dues_age_fresh),
                                        state.agingFresh,
                                        MaterialTheme.colorScheme.secondary,
                                    ),
                                    Segment(
                                        stringResource(R.string.dues_age_mid),
                                        state.agingMid,
                                        MaterialTheme.colorScheme.tertiary,
                                    ),
                                    Segment(
                                        stringResource(R.string.dues_age_old),
                                        state.agingOver30,
                                        MaterialTheme.colorScheme.error,
                                    ),
                                ),
                            )
                            Spacer(Modifier.height(Spacing.sm))
                            Row {
                                listOf(
                                    stringResource(R.string.dues_age_fresh) to state.agingFresh,
                                    stringResource(R.string.dues_age_mid) to state.agingMid,
                                    stringResource(R.string.dues_age_old) to state.agingOver30,
                                ).forEach { (label, amount) ->
                                    if (amount.paisa > 0) {
                                        Text(
                                            text = "$label · ${MoneyFormat.format(amount)}",
                                            style = MaterialTheme.typography.labelSmall,
                                            color = MaterialTheme.colorScheme.onPrimaryContainer
                                                .copy(alpha = 0.85f),
                                            modifier = Modifier.padding(end = Spacing.md),
                                        )
                                    }
                                }
                            }
                        }
                        if (state.hasOverdue) {
                            Spacer(Modifier.height(Spacing.md))
                            Text(
                                text = stringResource(R.string.dues_overdue_warning),
                                style = MaterialTheme.typography.bodySmall,
                                fontWeight = FontWeight.SemiBold,
                                color = MaterialTheme.colorScheme.onPrimaryContainer,
                            )
                        }
                    }
                }
            }

            if (state.customers.isEmpty() && !state.loading) {
                item {
                    EmptyState(
                        icon = Icons.Filled.Handshake,
                        title = stringResource(R.string.dues_empty_title),
                        body = stringResource(R.string.dues_empty_body),
                    )
                }
            } else {
                item { SectionHeader(stringResource(R.string.dues_by_customer)) }
                items(state.customers, key = { it.customer }) { due ->
                    DueRow(due = due, onSettle = { viewModel.openSettle(due) })
                }
            }
        }
    }

    state.settling?.let { customer ->
        SettleDialog(
            customer = customer,
            onDismiss = viewModel::dismissSettle,
            onConfirm = { amount -> viewModel.settle(customer, amount) },
        )
    }
}

@Composable
private fun DueRow(due: CustomerDue, onSettle: () -> Unit) {
    Card(
        onClick = onSettle,
        shape = RoundedCornerShape(Radii.card),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(
            modifier = Modifier.padding(Spacing.lg),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(
                Icons.Filled.Person,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(0.dp))
            Column(
                modifier = Modifier.weight(1f).padding(start = Spacing.md),
            ) {
                Text(
                    text = due.customer,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                )
                Text(
                    text = dueSinceLabel(due.dueSinceMillis),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Column(horizontalAlignment = Alignment.End) {
                Text(
                    text = MoneyFormat.format(due.amount),
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold,
                    color = if (due.amount.paisa < 0) {
                        MaterialTheme.colorScheme.secondary
                    } else {
                        MaterialTheme.colorScheme.error
                    },
                )
                TextButton(onClick = onSettle, enabled = due.amount.paisa > 0) {
                    Text(stringResource(R.string.dues_receive))
                }
            }
        }
    }
}

@Composable
private fun SettleDialog(
    customer: CustomerDue,
    onDismiss: () -> Unit,
    onConfirm: (Money) -> Unit,
) {
    var text by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.dues_receive_from, customer.customer)) },
        text = {
            Column {
                Text(
                    text = stringResource(
                        R.string.dues_current_balance,
                        MoneyFormat.format(customer.amount),
                    ),
                    style = MaterialTheme.typography.bodyMedium,
                )
                Spacer(Modifier.height(Spacing.md))
                OutlinedTextField(
                    value = text,
                    onValueChange = { text = it.filter { ch -> ch.isDigit() || ch == '.' } },
                    label = { Text(stringResource(R.string.dues_amount_received)) },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                    modifier = Modifier.fillMaxWidth(),
                )
            }
        },
        confirmButton = {
            Button(
                onClick = {
                    Money.parseOrNull(text)?.let(onConfirm)
                },
                enabled = text.isNotBlank(),
            ) {
                Text(stringResource(R.string.dues_confirm_payment))
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text(stringResource(R.string.action_cancel)) }
        },
    )
}

@Composable
private fun dueSinceLabel(millis: Long): String {
    val date = Instant.ofEpochMilli(millis).atZone(ZoneId.systemDefault()).toLocalDate()
    return stringResource(R.string.dues_since, com.lipon.rakho.core.time.DhakaTime.formatShort(date))
}
