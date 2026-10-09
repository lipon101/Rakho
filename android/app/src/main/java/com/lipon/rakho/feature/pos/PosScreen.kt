package com.lipon.rakho.feature.pos

import androidx.compose.foundation.BorderStroke
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
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Inventory2
import androidx.compose.material.icons.filled.QrCodeScanner
import androidx.compose.material.icons.filled.Remove
import androidx.compose.material.icons.filled.Schedule
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import com.lipon.rakho.ui.components.RakhoFilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.SnackbarResult
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
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.lipon.rakho.R
import com.lipon.rakho.core.model.CartLine
import com.lipon.rakho.core.model.PaymentMethod
import com.lipon.rakho.core.money.MoneyFormat
import com.lipon.rakho.core.time.DhakaTime
import com.lipon.rakho.core.time.ExpiryRules
import com.lipon.rakho.core.time.ExpiryStatus
import com.lipon.rakho.di.RakhoViewModelFactory
import com.lipon.rakho.ui.components.EmptyState
import com.lipon.rakho.ui.components.ExpiryStatusPill
import com.lipon.rakho.ui.components.KeyValueRow
import com.lipon.rakho.ui.components.RakhoSearchField
import com.lipon.rakho.ui.components.SectionHeader
import com.lipon.rakho.ui.components.StatusExpiryStrip
import com.lipon.rakho.ui.components.StatusPill
import com.lipon.rakho.ui.theme.Radii
import com.lipon.rakho.ui.theme.Sizes
import com.lipon.rakho.ui.theme.Spacing
import com.lipon.rakho.ui.theme.statusExpiredContainer
import com.lipon.rakho.ui.theme.statusExpiredText
import com.lipon.rakho.ui.theme.statusNearContainer
import com.lipon.rakho.ui.theme.statusNearText
import com.lipon.rakho.ui.theme.statusSafeContainer
import com.lipon.rakho.ui.theme.statusSafeText
import com.lipon.rakho.ui.util.FileSharing
import java.time.Instant
import java.time.format.DateTimeFormatter

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PosScreen(
    onDone: () -> Unit,
    onAddMedicine: (prefill: String) -> Unit = {},
    onScanBarcode: () -> Unit = {},
    viewModel: PosViewModel = viewModel(factory = RakhoViewModelFactory),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val book by viewModel.book.collectAsStateWithLifecycle()
    val snackbar = remember { SnackbarHostState() }
    var sheetOpen by remember { mutableStateOf(false) }
    val sheetState = rememberModalBottomSheetState()

    val context = LocalContext.current
    val recordedText = stringResource(R.string.pos_sale_recorded)
    val queuedText = stringResource(R.string.pos_sale_queued)
    val insufficientText = stringResource(R.string.pos_insufficient_stock)
    val customerRequiredText = stringResource(R.string.pos_customer_required)
    val genericError = stringResource(R.string.error_generic)
    val shareAction = stringResource(R.string.pos_share)
    val shareTitle = stringResource(R.string.pos_receipt_share)
    val shopFallback = stringResource(R.string.app_name)
    val thanksText = stringResource(R.string.pos_receipt_thanks)
    val customerLabel = stringResource(R.string.pos_receipt_customer)
    val invoiceLabel = stringResource(R.string.pos_receipt_invoice)
    val subtotalLabel = stringResource(R.string.pos_receipt_subtotal)
    val discountLabel = stringResource(R.string.pos_discount)
    val totalLabel = stringResource(R.string.pos_total)
    val paymentLabel = stringResource(R.string.pos_payment_method)
    val amountPaidLabel = stringResource(R.string.pos_amount_paid)
    val changeLabel = stringResource(R.string.pos_change_due)
    val creditLabel = stringResource(R.string.pay_credit)
    val payCash = stringResource(R.string.pay_cash)
    val payBkash = stringResource(R.string.pay_bkash)
    val payNagad = stringResource(R.string.pay_nagad)
    val payCard = stringResource(R.string.pay_card)
    val payCredit = stringResource(R.string.pay_credit)

    fun paymentName(method: PaymentMethod): String = when (method) {
        PaymentMethod.CASH -> payCash
        PaymentMethod.BKASH -> payBkash
        PaymentMethod.NAGAD -> payNagad
        PaymentMethod.CARD -> payCard
        PaymentMethod.CREDIT -> payCredit
    }

    /**
     * The receipt exactly as the customer was charged — same totals, same
     * discount, Dhaka time — written as plain text so it opens in any chat or
     * printer app the shop already uses.
     */
    val formatReceipt: (Receipt) -> String = { r ->
        val stamp = Instant.ofEpochMilli(r.soldAtMillis)
            .atZone(DhakaTime.ZONE)
            .format(DateTimeFormatter.ofPattern("dd MMM yyyy, HH:mm"))
        val rule = "-".repeat(28)
        buildString {
            appendLine(r.shopName.ifBlank { shopFallback })
            appendLine(stamp)
            appendLine(rule)
            appendLine("$invoiceLabel ${r.invoice}")
            r.lines.forEach { line ->
                appendLine("${line.name} × ${line.quantity} = ${MoneyFormat.format(line.lineTotal)}")
            }
            appendLine(rule)
            appendLine("$subtotalLabel ${MoneyFormat.format(r.subtotal)}")
            if (!r.discount.isZero) appendLine("$discountLabel ${MoneyFormat.format(r.discount)}")
            appendLine("$totalLabel ${MoneyFormat.format(r.total)}")
            appendLine("$paymentLabel ${paymentName(r.paymentMethod)}")
            if (!r.received.isZero) appendLine("$amountPaidLabel ${MoneyFormat.format(r.received)}")
            if (!r.changeDue.isZero) appendLine("$changeLabel ${MoneyFormat.format(r.changeDue)}")
            if (!r.credit.isZero) {
                appendLine("$creditLabel ${MoneyFormat.format(r.credit)}")
                if (r.customerName.isNotBlank()) appendLine("$customerLabel ${r.customerName}")
            }
            appendLine(rule)
            appendLine(thanksText)
        }
    }

    LaunchedEffect(state.message) {
        when (val message = state.message) {
            is PosMessage.Recorded -> {
                sheetOpen = false
                val choice = snackbar.showSnackbar(
                    message = "$recordedText · ${message.invoice}",
                    actionLabel = shareAction,
                    withDismissAction = true,
                )
                if (choice == SnackbarResult.ActionPerformed) {
                    FileSharing.shareText(
                        context,
                        "rakho-receipt-${message.receipt.invoice}.txt",
                        formatReceipt(message.receipt),
                        mimeType = "text/plain",
                        chooserTitle = shareTitle,
                    )
                }
                viewModel.consumeMessage()
            }
            is PosMessage.Queued -> {
                sheetOpen = false
                val choice = snackbar.showSnackbar(
                    message = queuedText,
                    actionLabel = shareAction,
                    withDismissAction = true,
                )
                if (choice == SnackbarResult.ActionPerformed) {
                    FileSharing.shareText(
                        context,
                        "rakho-receipt-${message.receipt.invoice}.txt",
                        formatReceipt(message.receipt),
                        mimeType = "text/plain",
                        chooserTitle = shareTitle,
                    )
                }
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
                actions = {
                    IconButton(onClick = onScanBarcode) {
                        Icon(
                            imageVector = Icons.Filled.QrCodeScanner,
                            contentDescription = "Scan Barcode",
                        )
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
            Box(
                modifier = Modifier.padding(horizontal = Spacing.lg, vertical = Spacing.sm),
            ) {
                RakhoSearchField(
                    value = state.query,
                    onValueChange = viewModel::onQueryChange,
                    hint = stringResource(R.string.pos_search_hint),
                )
            }

            if (state.cart.isNotEmpty()) {
                CartLines(
                    lines = state.cart,
                    linePrices = state.linePrices,
                    onIncrease = viewModel::add,
                    onDecrease = viewModel::decrement,
                    onDelete = viewModel::remove,
                    onQuantityChange = viewModel::setQuantity,
                    onPriceChange = viewModel::onLinePriceChange,
                )
                HorizontalDivider(modifier = Modifier.padding(horizontal = Spacing.lg))
            }

            if (state.items.isEmpty() && state.query.isBlank()) {
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
                            inCart = state.cart
                                .firstOrNull { it.medicineId == item.medicine.id }
                                ?.quantity
                                ?: 0,
                            onIncrease = { viewModel.add(item.medicine.id) },
                            onDecrease = { viewModel.decrement(item.medicine.id) },
                        )
                    }

                    // Your shelves have no match: offer the 21k-brand
                    // catalogue + a manual-add door, right at the counter.
                    if (state.query.isNotBlank()) {
                        if (state.catalogSearching) {
                            item {
                                Row(
                                    verticalAlignment = Alignment.CenterVertically,
                                    modifier = Modifier.padding(vertical = Spacing.sm),
                                ) {
                                    CircularProgressIndicator(
                                        modifier = Modifier.size(16.dp),
                                        strokeWidth = 2.dp,
                                    )
                                    Spacer(Modifier.width(Spacing.sm))
                                    Text(
                                        text = stringResource(R.string.add_medicine_searching),
                                        style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    )
                                }
                            }
                        }
                        items(state.catalogHits, key = { "cat-${it.id}" }) { hit ->
                            CatalogFallbackRow(
                                name = hit.displayName,
                                sub = listOf(hit.genericName, hit.dosageForm)
                                    .filter { it.isNotBlank() }
                                    .joinToString(" · "),
                                onAdd = { onAddMedicine(hit.displayName) },
                            )
                        }
                        if (!state.catalogSearching) {
                            item {
                                CatalogFallbackRow(
                                    name = stringResource(
                                        R.string.pos_add_custom,
                                        state.query.trim(),
                                    ),
                                    sub = stringResource(R.string.add_medicine_manual),
                                    onAdd = { onAddMedicine(state.query.trim()) },
                                )
                            }
                        }
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
                book = book,
                onPaymentChange = viewModel::onPaymentChange,
                onDiscountChange = viewModel::onDiscountChange,
                onDiscountAmountChange = viewModel::onDiscountAmountChange,
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
private fun CatalogFallbackRow(name: String, sub: String, onAdd: () -> Unit) {
    Surface(
        shape = RoundedCornerShape(Radii.card),
        color = MaterialTheme.colorScheme.surface,
        tonalElevation = 1.dp,
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
        onClick = onAdd,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(
            modifier = Modifier.padding(Spacing.lg),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = name,
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.SemiBold,
                )
                if (sub.isNotBlank()) {
                    Text(
                        text = sub,
                        style = MaterialTheme.typography.bodySmall,
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

@Composable
private fun MedicineRow(
    item: PosItem,
    inCart: Int,
    onIncrease: () -> Unit,
    onDecrease: () -> Unit,
) {
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
                Row(verticalAlignment = Alignment.Top) {
                    Column(modifier = Modifier.weight(1f)) {
                        Text(
                            text = item.medicine.displayName,
                            style = MaterialTheme.typography.titleSmall,
                            fontWeight = FontWeight.SemiBold,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                        Spacer(Modifier.height(Spacing.xs))
                        Text(
                            text = listOf(item.medicine.genericName, item.medicine.dosageForm)
                                .filter { it.isNotBlank() }
                                .joinToString(" · "),
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                    }
                    Spacer(Modifier.width(Spacing.md))
                    Column(horizontalAlignment = Alignment.End) {
                        Text(
                            text = MoneyFormat.format(item.price),
                            style = MaterialTheme.typography.titleSmall,
                            fontWeight = FontWeight.Bold,
                        )
                        Spacer(Modifier.height(Spacing.xs))
                        // In the cart this row becomes a stepper, so the counter can
                        // fix a mis-tap in place instead of hunting for the line above.
                        if (inCart > 0) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                IconButton(onClick = onDecrease) {
                                    Icon(
                                        imageVector = Icons.Filled.Remove,
                                        contentDescription = stringResource(R.string.cd_decrease),
                                        tint = MaterialTheme.colorScheme.primary,
                                    )
                                }
                                Text(
                                    text = inCart.toString(),
                                    style = MaterialTheme.typography.titleSmall,
                                    fontWeight = FontWeight.Bold,
                                    textAlign = TextAlign.Center,
                                    modifier = Modifier.width(32.dp),
                                )
                                AddButton(
                                    enabled = !item.isOutOfStock,
                                    onClick = onIncrease,
                                )
                            }
                        } else {
                            AddButton(
                                enabled = !item.isOutOfStock,
                                onClick = onIncrease,
                            )
                        }
                    }
                }
                // Stock and expiry sit on their own full-width line so they
                // never fight the stepper for horizontal room.
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
                        icon = Icons.Filled.Inventory2,
                    )
                    item.nearestExpiry?.let { expiry ->
                        Spacer(Modifier.width(Spacing.sm))
                        val days = ExpiryRules.daysUntil(expiry, DhakaTime.today())
                        val (container, content) = when {
                            days <= 0 -> statusExpiredContainer() to statusExpiredText()
                            days <= ExpiryRules.EXPIRING_SOON_DAYS ->
                                statusNearContainer() to statusNearText()
                            else -> statusSafeContainer() to statusSafeText()
                        }
                        val glyph = when {
                            days <= 0 -> Icons.Filled.Warning
                            days <= ExpiryRules.EXPIRING_SOON_DAYS -> Icons.Filled.Schedule
                            else -> Icons.Filled.CheckCircle
                        }
                        StatusPill(
                            text = when {
                                days <= 0 -> stringResource(R.string.stock_expires_today)
                                days <= ExpiryRules.EXPIRING_SOON_DAYS ->
                                    stringResource(R.string.stock_expires_in, days)
                                else -> stringResource(
                                    R.string.pos_expiry_date,
                                    DhakaTime.formatShort(expiry),
                                )
                            },
                            containerColor = container,
                            contentColor = content,
                            icon = glyph,
                        )
                    }
                }
            }
        }
    }
}

/** Shared add-to-cart affordance for a product row. */
@Composable
private fun AddButton(enabled: Boolean, onClick: () -> Unit) {
    IconButton(onClick = onClick, enabled = enabled) {
        Icon(
            imageVector = Icons.Filled.Add,
            contentDescription = stringResource(R.string.cd_add),
            tint = if (enabled) {
                MaterialTheme.colorScheme.primary
            } else {
                MaterialTheme.colorScheme.onSurfaceVariant
            },
        )
    }
}

/**
 * The cart, as fully editable lines rather than a read-only tally.
 *
 * Every field a shopkeeper can get wrong at the counter — quantity, unit
 * price, or the whole line — is corrected here, in place, before checkout.
 */
@Composable
private fun CartLines(
    lines: List<CartLine>,
    linePrices: Map<String, String>,
    onIncrease: (String) -> Unit,
    onDecrease: (String) -> Unit,
    onDelete: (String) -> Unit,
    onQuantityChange: (String, Int) -> Unit,
    onPriceChange: (String, String) -> Unit,
) {
    Column(modifier = Modifier.padding(horizontal = Spacing.lg, vertical = Spacing.sm)) {
        SectionHeader(stringResource(R.string.pos_cart_items))
        lines.forEach { line ->
            Spacer(Modifier.height(Spacing.sm))
            CartLineCard(
                line = line,
                priceText = linePrices[line.medicineId]
                    ?: line.unitPrice.toBigDecimal().toPlainString(),
                onIncrease = { onIncrease(line.medicineId) },
                onDecrease = { onDecrease(line.medicineId) },
                onDelete = { onDelete(line.medicineId) },
                onQuantityChange = { onQuantityChange(line.medicineId, it) },
                onPriceChange = { onPriceChange(line.medicineId, it) },
            )
        }
        Text(
            text = stringResource(R.string.pos_fefo_note),
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(top = Spacing.sm),
        )
    }
}

@Composable
private fun CartLineCard(
    line: CartLine,
    priceText: String,
    onIncrease: () -> Unit,
    onDecrease: () -> Unit,
    onDelete: () -> Unit,
    onQuantityChange: (Int) -> Unit,
    onPriceChange: (String) -> Unit,
) {
    // The field owns a draft so clearing it to retype never deletes the line
    // underneath the user's fingers; the cart quantity still commits as typed.
    var quantityText by remember(line.medicineId, line.quantity) {
        mutableStateOf(line.quantity.toString())
    }

    // The line sells from specific FEFO batches; the strip and chip tell the
    // counter which expiry the last unit of this line will actually hit —
    // the same glance-signal the Stock rows use.
    val nearestExpiry = line.allocations.minOfOrNull { it.expiryDate }
    val expiryStatus = nearestExpiry?.let { ExpiryRules.status(it, DhakaTime.today()) }
    val expiryDays = nearestExpiry?.let { ExpiryRules.daysUntil(it, DhakaTime.today()) }

    Surface(
        shape = RoundedCornerShape(Radii.card),
        color = MaterialTheme.colorScheme.surfaceVariant,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(modifier = Modifier.fillMaxWidth()) {
            if (expiryStatus != null) {
                StatusExpiryStrip(expiryStatus)
            }
            Column(modifier = Modifier.weight(1f).padding(Spacing.md)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        text = line.medicineName,
                        style = MaterialTheme.typography.titleSmall,
                        fontWeight = FontWeight.SemiBold,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                        modifier = Modifier.weight(1f),
                    )
                    if (expiryStatus != null && expiryStatus != ExpiryStatus.HEALTHY && expiryDays != null) {
                        Spacer(Modifier.width(Spacing.sm))
                        ExpiryStatusPill(
                            status = expiryStatus,
                            daysUntilExpiry = expiryDays,
                            modifier = Modifier.widthIn(max = 132.dp),
                        )
                    }
                    Spacer(Modifier.width(Spacing.sm))
                    Text(
                        text = MoneyFormat.format(line.unitPrice * line.quantity),
                        style = MaterialTheme.typography.titleSmall,
                        fontWeight = FontWeight.Bold,
                        color = MaterialTheme.colorScheme.primary,
                    )
                }

                Spacer(Modifier.height(Spacing.sm))

                Row(verticalAlignment = Alignment.CenterVertically) {
                OutlinedTextField(
                    value = priceText,
                    onValueChange = onPriceChange,
                    label = { Text(stringResource(R.string.pos_line_price)) },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                    textStyle = MaterialTheme.typography.bodyMedium,
                    modifier = Modifier.width(84.dp),
                )
                Spacer(Modifier.weight(1f))
                IconButton(onClick = onDecrease) {
                    Icon(
                        imageVector = Icons.Filled.Remove,
                        contentDescription = stringResource(R.string.cd_decrease),
                    )
                }
                OutlinedTextField(
                    value = quantityText,
                    onValueChange = { text ->
                        quantityText = text.filter { it.isDigit() }.take(5)
                        quantityText.toIntOrNull()?.let { onQuantityChange(it) }
                    },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(
                        keyboardType = KeyboardType.Number,
                        imeAction = ImeAction.Done,
                    ),
                    textStyle = MaterialTheme.typography.titleSmall.copy(
                        fontWeight = FontWeight.Bold,
                        textAlign = TextAlign.Center,
                    ),
                    modifier = Modifier.width(56.dp),
                )
                IconButton(onClick = onIncrease) {
                    Icon(
                        imageVector = Icons.Filled.Add,
                        contentDescription = stringResource(R.string.cd_increase),
                        tint = MaterialTheme.colorScheme.primary,
                    )
                }
                IconButton(onClick = onDelete) {
                    Icon(
                        imageVector = Icons.Filled.Delete,
                        contentDescription = stringResource(R.string.pos_remove_line),
                        tint = MaterialTheme.colorScheme.error,
                    )
                }
            }
            }
        }
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
                modifier = Modifier.height(Sizes.primaryButtonHeight),
            ) {
                Text(
                    text = stringResource(R.string.pos_checkout),
                    fontWeight = FontWeight.Bold,
                )
            }
        }
    }
}

@OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)
@Composable
private fun CheckoutSheet(
    state: PosUiState,
    book: List<com.lipon.rakho.data.firebase.FirestoreCustomer>,
    onPaymentChange: (PaymentMethod) -> Unit,
    onDiscountChange: (String) -> Unit,
    onDiscountAmountChange: (String) -> Unit,
    onReceivedChange: (String) -> Unit,
    onCustomerChange: (String) -> Unit,
    onConfirm: () -> Unit,
    onClear: () -> Unit,
) {
    Column(modifier = Modifier.fillMaxWidth().padding(Spacing.xl)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = stringResource(R.string.pos_payment_method),
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.SemiBold,
                modifier = Modifier.weight(1f),
            )
            // Clear lives in the header, deliberately away from the confirm
            // CTA at the bottom: a mis-tap there must not empty the cart.
            TextButton(onClick = onClear) {
                Text(stringResource(R.string.pos_clear))
            }
        }
        Spacer(Modifier.height(Spacing.sm))
        Row(horizontalArrangement = Arrangement.spacedBy(Spacing.sm)) {
            PaymentMethod.entries.take(3).forEach { method ->
                RakhoFilterChip(
                    selected = state.payment == method,
                    onClick = { onPaymentChange(method) },
                    label = paymentLabel(method),
                )
            }
        }
        Spacer(Modifier.height(Spacing.sm))
        Row(horizontalArrangement = Arrangement.spacedBy(Spacing.sm)) {
            PaymentMethod.entries.drop(3).forEach { method ->
                RakhoFilterChip(
                    selected = state.payment == method,
                    onClick = { onPaymentChange(method) },
                    label = paymentLabel(method),
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
            // One-tap names from the phone book: the baki history only helps
            // if the name is typed the same way every time, so let the shop
            // tap it instead.
            val typed = state.customerName.trim().lowercase()
            val suggestions = book.asSequence()
                .map { it.name }
                .filter { it.isNotBlank() && (typed.isEmpty() || it.lowercase().contains(typed)) }
                .distinct()
                .take(6)
                .toList()
            if (suggestions.isNotEmpty()) {
                Spacer(Modifier.height(Spacing.sm))
                androidx.compose.foundation.layout.FlowRow(
                    horizontalArrangement = Arrangement.spacedBy(Spacing.sm),
                    verticalArrangement = Arrangement.spacedBy(Spacing.xs),
                ) {
                    suggestions.forEach { name ->
                        RakhoFilterChip(
                            selected = name.equals(state.customerName.trim(), ignoreCase = true),
                            onClick = { onCustomerChange(name) },
                            label = name,
                        )
                    }
                }
            }
        }

        Spacer(Modifier.height(Spacing.lg))
        Row(horizontalArrangement = Arrangement.spacedBy(Spacing.md)) {
            OutlinedTextField(
                value = if (state.discountPercent == 0) "" else state.discountPercent.toString(),
                onValueChange = onDiscountChange,
                label = { Text(stringResource(R.string.pos_discount) + " %") },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                modifier = Modifier.weight(1f),
            )
            OutlinedTextField(
                value = state.discountAmountText,
                onValueChange = onDiscountAmountChange,
                label = { Text(stringResource(R.string.pos_discount_amount)) },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                modifier = Modifier.weight(1f),
            )
        }
        Text(
            text = stringResource(R.string.pos_discount_hint),
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(top = Spacing.xs),
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
            label = stringResource(R.string.pos_receipt_subtotal),
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
            modifier = Modifier.fillMaxWidth().height(Sizes.primaryButtonHeight),
        ) {
            Text(
                text = stringResource(R.string.pos_checkout),
                fontWeight = FontWeight.Bold,
            )
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
