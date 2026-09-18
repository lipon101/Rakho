package com.lipon.rakho.feature.pos

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.rememberModalBottomSheetState
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
import com.lipon.rakho.core.model.PaymentMethod
import com.lipon.rakho.core.money.MoneyFormat
import com.lipon.rakho.core.time.DhakaTime
import com.lipon.rakho.core.time.ExpiryRules
import com.lipon.rakho.di.RakhoViewModelFactory
import com.lipon.rakho.ui.components.EmptyState
import com.lipon.rakho.ui.components.KeyValueRow
import com.lipon.rakho.ui.components.SectionHeader
import com.lipon.rakho.ui.components.StatusPill
import com.lipon.rakho.ui.theme.Radii
import com.lipon.rakho.ui.theme.Spacing

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PosScreen(
    onDone: () -> Unit,
    viewModel: PosViewModel = viewModel(factory = RakhoViewModelFactory),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val snackbar = remember { SnackbarHostState() }
    var sheetOpen by remember { mutableStateOf(false) }
    val sheetState = rememberModalBottomSheetState()

    val recordedText = stringResource(R.string.pos_sale_recorded)
    val queuedText = stringResource(R.string.pos_sale_queued)
    val insufficientText = stringResource(R.string.pos_insufficient_stock)
    val customerRequiredText = stringResource(R.string.pos_customer_required)
    val genericError = stringResource(R.string.error_generic)

    LaunchedEffect(state.message) {
        when (val message = state.message) {
            is PosMessage.Recorded -> {
                sheetOpen = false
                snackbar.showSnackbar("$recordedText · ${message.invoice}")
                viewModel.consumeMessage()
            }
            PosMessage.Queued -> {
                sheetOpen = false
                snackbar.showSnackbar(queuedText)
                viewModel.consumeMessage()
            }
            PosMessage.CustomerRequired -> {
                snackbar.showSnackbar(customerRequiredText)
                viewModel.consumeMessage()
            }
            PosMessage.InsufficientStock -> {
                snackbar.showSnackbar(insufficientText)
                viewModel.consumeMessage()
            }
            is PosMessage.Failed -> {
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
                title = { Text(stringResource(R.string.action_sell)) },
                navigationIcon = {
                    IconButton(onClick = onDone) {
                        Icon(Icons.Filled.Close, contentDescription = stringResource(R.string.cd_close))
                    }
                },
            )
        },
        bottomBar = {
            if (state.cart.isNotEmpty()) {
                CartBar(
                    itemCount = state.itemCount,
                    total = MoneyFormat.format(state.totals.total),
                    onCheckout = { sheetOpen = true },
                )
            }
        },
    ) { padding ->
        Column(modifier = Modifier.fillMaxSize().padding(padding).imePadding()) {
            OutlinedTextField(
                value = state.query,
                onValueChange = viewModel::onQueryChange,
                placeholder = { Text(stringResource(R.string.pos_search_hint)) },
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

            if (state.cart.isNotEmpty()) {
                CartLines(
                    lines = state.cart.map { it.medicineName to it.quantity },
                    onIncrease = { name ->
                        state.cart.firstOrNull { it.medicineName == name }?.let {
                            viewModel.add(it.medicineId)
                        }
                    },
                    onRemove = { name ->
                        state.cart.firstOrNull { it.medicineName == name }?.let {
                            viewModel.remove(it.medicineId)
                        }
                    },
                )
                HorizontalDivider(modifier = Modifier.padding(horizontal = Spacing.lg))
            }

            if (state.items.isEmpty()) {
                EmptyState(
                    title = stringResource(R.string.pos_cart_empty),
                    body = stringResource(R.string.add_medicine_hint),
                    icon = Icons.Filled.Search,
                )
            } else {
                LazyColumn(
                    contentPadding = PaddingValues(
                        start = Spacing.lg,
                        end = Spacing.lg,
                        top = Spacing.sm,
                        bottom = Spacing.xxl,
                    ),
                    verticalArrangement = Arrangement.spacedBy(Spacing.sm),
                ) {
                    items(state.items, key = { it.medicine.id }) { item ->
                        MedicineRow(
                            item = item,
                            onAdd = { viewModel.add(item.medicine.id) },
                        )
                    }
                }
            }
        }
    }

    if (sheetOpen) {
        ModalBottomSheet(
            onDismissRequest = { sheetOpen = false },
            sheetState = sheetState,
            shape = RoundedCornerShape(topStart = Radii.sheet, topEnd = Radii.sheet),
        ) {
            CheckoutSheet(
                state = state,
                onPaymentChange = viewModel::onPaymentChange,
                onDiscountChange = viewModel::onDiscountChange,
                onReceivedChange = viewModel::onReceivedChange,
                onCustomerChange = viewModel::onCustomerChange,
                onConfirm = viewModel::checkout,
                onClear = {
                    viewModel.clearCart()
                    sheetOpen = false
                },
            )
        }
    }
}

@Composable
private fun MedicineRow(item: PosItem, onAdd: () -> Unit) {
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
                    text = item.medicine.displayName,
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.SemiBold,
                )
                Spacer(Modifier.height(Spacing.xs))
                Text(
                    text = listOf(item.medicine.genericName, item.medicine.dosageForm)
                        .filter { it.isNotBlank() }
                        .joinToString(" · "),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(Spacing.sm))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    StatusPill(
                        text = if (item.isOutOfStock) {
                            stringResource(R.string.pos_out_of_stock)
                        } else {
                            stringResource(R.string.stock_units, item.sellableAvailable)
                        },
                        containerColor = if (item.isOutOfStock) {
                            MaterialTheme.colorScheme.errorContainer
                        } else {
                            MaterialTheme.colorScheme.surfaceVariant
                        },
                        contentColor = if (item.isOutOfStock) {
                            MaterialTheme.colorScheme.onErrorContainer
                        } else {
                            MaterialTheme.colorScheme.onSurfaceVariant
                        },
                    )
                    item.nearestExpiry?.let { expiry ->
                        Spacer(Modifier.width(Spacing.sm))
                        val days = ExpiryRules.daysUntil(expiry, DhakaTime.today())
                        StatusPill(
                            text = stringResource(R.string.stock_expires_in, days),
                            containerColor = MaterialTheme.colorScheme.tertiaryContainer,
                            contentColor = MaterialTheme.colorScheme.onTertiaryContainer,
                        )
                    }
                }
            }
            Spacer(Modifier.width(Spacing.md))
            Column(horizontalAlignment = Alignment.End) {
                Text(
                    text = MoneyFormat.format(item.price),
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.Bold,
                )
                Spacer(Modifier.height(Spacing.xs))
                IconButton(onClick = onAdd, enabled = !item.isOutOfStock) {
                    Icon(
                        imageVector = Icons.Filled.Add,
                        contentDescription = stringResource(R.string.cd_add),
                        tint = if (item.isOutOfStock) {
                            MaterialTheme.colorScheme.onSurfaceVariant
                        } else {
                            MaterialTheme.colorScheme.primary
                        },
                    )
                }
            }
        }
    }
}

@Composable
private fun CartLines(
    lines: List<Pair<String, Int>>,
    onIncrease: (String) -> Unit,
    onRemove: (String) -> Unit,
) {
    Column(modifier = Modifier.padding(horizontal = Spacing.lg, vertical = Spacing.sm)) {
        SectionHeader(stringResource(R.string.pos_items))
        lines.forEach { (name, quantity) ->
            Row(
                modifier = Modifier.fillMaxWidth().padding(vertical = Spacing.xs),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = name,
                    style = MaterialTheme.typography.bodyMedium,
                    modifier = Modifier.weight(1f),
                )
                TextButton(onClick = { onRemove(name) }) {
                    Text("\u2212", style = MaterialTheme.typography.titleMedium)
                }
                Text(
                    text = quantity.toString(),
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.Bold,
                )
                TextButton(onClick = { onIncrease(name) }) {
                    Text("+", style = MaterialTheme.typography.titleMedium)
                }
            }
        }
        Text(
            text = stringResource(R.string.pos_fefo_note),
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun CartBar(itemCount: Int, total: String, onCheckout: () -> Unit) {
    Surface(
        color = MaterialTheme.colorScheme.surface,
        tonalElevation = 3.dp,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(Spacing.lg),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = stringResource(R.string.pos_total),
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Text(
                    text = total,
                    style = MaterialTheme.typography.titleLarge,
                    fontWeight = FontWeight.Bold,
                )
                Text(
                    text = stringResource(R.string.pos_items) + " · " + itemCount,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Button(
                onClick = onCheckout,
                shape = RoundedCornerShape(Radii.button),
                modifier = Modifier.height(52.dp),
            ) {
                Text(
                    text = stringResource(R.string.pos_checkout),
                    fontWeight = FontWeight.Bold,
                )
            }
        }
    }
}

@Composable
private fun CheckoutSheet(
    state: PosUiState,
    onPaymentChange: (PaymentMethod) -> Unit,
    onDiscountChange: (String) -> Unit,
    onReceivedChange: (String) -> Unit,
    onCustomerChange: (String) -> Unit,
    onConfirm: () -> Unit,
    onClear: () -> Unit,
) {
    Column(modifier = Modifier.fillMaxWidth().padding(Spacing.xl)) {
        Text(
            text = stringResource(R.string.pos_payment_method),
            style = MaterialTheme.typography.titleSmall,
            fontWeight = FontWeight.SemiBold,
        )
        Spacer(Modifier.height(Spacing.sm))
        Row(horizontalArrangement = Arrangement.spacedBy(Spacing.sm)) {
            PaymentMethod.entries.take(3).forEach { method ->
                FilterChip(
                    selected = state.payment == method,
                    onClick = { onPaymentChange(method) },
                    label = { Text(paymentLabel(method)) },
                )
            }
        }
        Spacer(Modifier.height(Spacing.sm))
        Row(horizontalArrangement = Arrangement.spacedBy(Spacing.sm)) {
            PaymentMethod.entries.drop(3).forEach { method ->
                FilterChip(
                    selected = state.payment == method,
                    onClick = { onPaymentChange(method) },
                    label = { Text(paymentLabel(method)) },
                )
            }
        }

        if (state.payment == PaymentMethod.CREDIT) {
            Spacer(Modifier.height(Spacing.md))
            OutlinedTextField(
                value = state.customerName,
                onValueChange = onCustomerChange,
                label = { Text(stringResource(R.string.pos_customer_name)) },
                placeholder = { Text(stringResource(R.string.pos_customer_placeholder)) },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
        }

        Spacer(Modifier.height(Spacing.lg))
        OutlinedTextField(
            value = if (state.discountPercent == 0) "" else state.discountPercent.toString(),
            onValueChange = onDiscountChange,
            label = { Text(stringResource(R.string.pos_discount) + " %") },
            singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(Modifier.height(Spacing.md))
        OutlinedTextField(
            value = if (state.received.isZero) "" else state.received.toBigDecimal().toPlainString(),
            onValueChange = onReceivedChange,
            label = { Text(stringResource(R.string.pos_amount_paid)) },
            singleLine = true,
            keyboardOptions = KeyboardOptions(
                keyboardType = KeyboardType.Decimal,
                imeAction = ImeAction.Done,
            ),
            modifier = Modifier.fillMaxWidth(),
        )

        Spacer(Modifier.height(Spacing.lg))
        KeyValueRow(stringResource(R.string.pos_items), state.itemCount.toString())
        KeyValueRow(
            label = stringResource(R.string.pos_total),
            value = MoneyFormat.format(state.totals.subtotal),
        )
        if (!state.totals.discount.isZero) {
            KeyValueRow(
                label = stringResource(R.string.pos_discount),
                value = "- " + MoneyFormat.format(state.totals.discount),
            )
        }
        KeyValueRow(
            label = stringResource(R.string.pos_total),
            value = MoneyFormat.format(state.totals.total),
        )
        if (state.payment == PaymentMethod.CASH && !state.received.isZero) {
            KeyValueRow(
                label = stringResource(R.string.pos_change_due),
                value = MoneyFormat.format(state.changeDue),
            )
        }
        if (state.payment == PaymentMethod.CREDIT) {
            KeyValueRow(
                label = stringResource(R.string.pay_credit),
                value = MoneyFormat.format(state.creditRemainder),
            )
        }

        Spacer(Modifier.height(Spacing.xl))
        Button(
            onClick = onConfirm,
            enabled = !state.busy,
            shape = RoundedCornerShape(Radii.button),
            modifier = Modifier.fillMaxWidth().height(54.dp),
        ) {
            Text(
                text = stringResource(R.string.pos_checkout),
                fontWeight = FontWeight.Bold,
            )
        }
        TextButton(onClick = onClear, modifier = Modifier.fillMaxWidth()) {
            Text(stringResource(R.string.pos_clear))
        }
    }
}

@Composable
private fun paymentLabel(method: PaymentMethod): String = stringResource(
    when (method) {
        PaymentMethod.CASH -> R.string.pay_cash
        PaymentMethod.BKASH -> R.string.pay_bkash
        PaymentMethod.NAGAD -> R.string.pay_nagad
        PaymentMethod.CARD -> R.string.pay_card
        PaymentMethod.CREDIT -> R.string.pay_credit
    },
)
