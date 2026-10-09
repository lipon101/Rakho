package com.lipon.rakho.feature.dues

import androidx.compose.foundation.background
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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.layout.heightIn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Chat
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Contacts
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Handshake
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.PersonAdd
import androidx.compose.material.icons.filled.Schedule
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExtendedFloatingActionButton
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
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.lipon.rakho.R
import com.lipon.rakho.core.model.CustomerDue
import com.lipon.rakho.core.time.ExpiryStatus
import com.lipon.rakho.core.money.Money
import com.lipon.rakho.data.firebase.FirestoreCustomer
import com.lipon.rakho.data.repo.DuesLedgerEntry
import com.lipon.rakho.core.money.MoneyFormat
import com.lipon.rakho.di.RakhoViewModelFactory
import com.lipon.rakho.ui.charts.SegmentedBar
import com.lipon.rakho.ui.charts.Segment
import com.lipon.rakho.ui.components.EmptyState
import com.lipon.rakho.ui.components.SectionHeader
import com.lipon.rakho.ui.components.StatusExpiryStrip
import com.lipon.rakho.ui.components.StatusPill
import com.lipon.rakho.ui.theme.Radii
import com.lipon.rakho.ui.theme.Sizes
import com.lipon.rakho.ui.theme.Spacing
import com.lipon.rakho.ui.theme.StatusExpired
import com.lipon.rakho.ui.theme.StatusNear
import com.lipon.rakho.ui.theme.statusExpiredContainer
import com.lipon.rakho.ui.theme.statusExpiredText
import com.lipon.rakho.ui.theme.statusNearContainer
import com.lipon.rakho.ui.theme.statusNearText
import java.time.Instant

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DuesScreen(
    onBack: () -> Unit,
    viewModel: DuesViewModel = viewModel(factory = RakhoViewModelFactory),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val snackbar = remember { SnackbarHostState() }
    val settledTemplate = stringResource(R.string.dues_settled_toast)
    val removedText = stringResource(R.string.dues_entry_removed)
    val context = androidx.compose.ui.platform.LocalContext.current
    var editing by remember { mutableStateOf<FirestoreCustomer?>(null) }
    var adding by remember { mutableStateOf(false) }

    val reminderTemplate = stringResource(R.string.baki_reminder_message)
    val remindLabel = stringResource(R.string.dues_remind)

    // One-tap baki reminder: composed locally, handed to WhatsApp (or any
    // text app if the number is unknown). Nothing is sent automatically.
    fun remind(due: CustomerDue) {
        val draft = viewModel.reminderDraft(due)
        val text = reminderTemplate
            .replace("%1\$s", draft.name)
            .replace("%2\$s", draft.amount)
            .replace("%3\$d", draft.days.toString())
            .replace("%4\$s", state.shopName.ifBlank { context.getString(R.string.app_name) })
        BakiShare.send(context, draft.phone, text, remindLabel)
    }

    LaunchedEffect(state.message) {
        when (val msg = state.message) {
            DuesMessage.EntryRemoved -> {
                snackbar.showSnackbar(removedText)
                viewModel.consumeMessage()
            }
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
        floatingActionButton = {
            ExtendedFloatingActionButton(
                onClick = { adding = true },
                icon = { Icon(Icons.Filled.PersonAdd, contentDescription = null) },
                text = { Text(stringResource(R.string.dues_add_customer)) },
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
                    DueRow(
                        due = due,
                        phone = viewModel.phoneFor(due.customer),
                        onSettle = { viewModel.openSettle(due) },
                        onReview = { viewModel.openLedger(due) },
                        onRemind = { remind(due) },
                    )
                }
            }

            // The cloud phone book. Editing lives here, not in a separate
            // tab: it exists to serve the reminders, one row per customer.
            item { SectionHeader(stringResource(R.string.dues_book_title)) }
            if (state.book.isEmpty()) {
                item {
                    Text(
                        text = stringResource(R.string.dues_book_empty),
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(vertical = Spacing.sm),
                    )
                }
            } else {
                items(state.book, key = { it.id }) { customer ->
                    Card(
                        onClick = { editing = customer },
                        shape = RoundedCornerShape(Radii.card),
                        colors = CardDefaults.cardColors(
                            containerColor = MaterialTheme.colorScheme.surface,
                        ),
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Row(
                            modifier = Modifier.padding(horizontal = Spacing.lg, vertical = Spacing.sm),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Icon(
                                Icons.Filled.Contacts,
                                contentDescription = null,
                                tint = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                            Column(
                                modifier = Modifier.weight(1f).padding(start = Spacing.md),
                            ) {
                                Text(
                                    text = customer.name,
                                    style = MaterialTheme.typography.bodyLarge,
                                    fontWeight = FontWeight.Medium,
                                    maxLines = 1,
                                    overflow = TextOverflow.Ellipsis,
                                )
                                Text(
                                    text = customer.phone.ifBlank {
                                        stringResource(R.string.dues_no_phone)
                                    },
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                            IconButton(onClick = { viewModel.deleteCustomer(customer.id) }) {
                                Icon(
                                    Icons.Filled.Delete,
                                    contentDescription = stringResource(R.string.action_delete),
                                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                        }
                    }
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

    state.reviewing?.let { customer ->
        LedgerDialog(
            customer = customer,
            entries = state.ledger,
            onDismiss = viewModel::dismissLedger,
            onRemove = viewModel::removeEntry,
        )
    }

    if (adding || editing != null) {
        CustomerDialog(
            initial = editing,
            onDismiss = { adding = false; editing = null },
            onSave = { id, name, phone ->
                viewModel.saveCustomer(id, name, phone)
                adding = false
                editing = null
            },
        )
    }
}

/** Add/edit one phone-book row. Two fields only — at the counter, less is more. */
@Composable
private fun CustomerDialog(
    initial: FirestoreCustomer?,
    onDismiss: () -> Unit,
    onSave: (id: String?, name: String, phone: String) -> Unit,
) {
    var name by remember(initial) { mutableStateOf(initial?.name.orEmpty()) }
    var phone by remember(initial) { mutableStateOf(initial?.phone.orEmpty()) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = {
            Text(
                if (initial == null) {
                    stringResource(R.string.dues_add_customer)
                } else {
                    stringResource(R.string.dues_edit_customer)
                },
            )
        },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(Spacing.md)) {
                OutlinedTextField(
                    value = name,
                    onValueChange = { name = it },
                    label = { Text(stringResource(R.string.dues_customer_name)) },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                OutlinedTextField(
                    value = phone,
                    onValueChange = { phone = it.filter { ch -> ch.isDigit() || ch == '+' } },
                    label = { Text(stringResource(R.string.dues_phone)) },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Phone),
                    supportingText = { Text(stringResource(R.string.dues_phone_help)) },
                    modifier = Modifier.fillMaxWidth(),
                )
            }
        },
        confirmButton = {
            Button(onClick = { onSave(initial?.id, name.trim(), phone.trim()) }, enabled = name.isNotBlank()) {
                Text(stringResource(R.string.action_save))
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text(stringResource(R.string.action_cancel)) }
        },
    )
}

@Composable
private fun DueRow(
    due: CustomerDue,
    phone: String,
    onSettle: () -> Unit,
    onReview: () -> Unit,
    onRemind: () -> Unit,
) {
    // Baki ages like milk, not wine: 30+ days is money you may never see,
    // 8–29 days needs a reminder this week, under a week is normal trade.
    val ageDays = (System.currentTimeMillis() - due.dueSinceMillis) / 86_400_000L
    val agingSerious = ageDays >= 30
    val agingWatch = ageDays in 8..29
    Card(
        onClick = onSettle,
        shape = RoundedCornerShape(Radii.card),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(modifier = Modifier.fillMaxWidth()) {
            StatusExpiryStrip(
                when {
                    agingSerious -> ExpiryStatus.EXPIRED
                    agingWatch -> ExpiryStatus.EXPIRING_SOON
                    else -> ExpiryStatus.HEALTHY
                },
            )
            Row(
                modifier = Modifier.weight(1f).padding(Spacing.lg),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(
                    Icons.Filled.Person,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Column(
                    modifier = Modifier.weight(1f).padding(start = Spacing.md),
                ) {
                    Text(
                        text = due.customer,
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.SemiBold,
                    )
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(
                            text = dueSinceLabel(due.dueSinceMillis),
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        if (phone.isNotBlank()) {
                            Text(
                                text = " · $phone",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                            )
                        }
                        if (agingSerious || agingWatch) {
                            Spacer(Modifier.width(Spacing.sm))
                            val (container, content, icon) = if (agingSerious) {
                                Triple(statusExpiredContainer(), statusExpiredText(), Icons.Filled.Warning)
                            } else {
                                Triple(statusNearContainer(), statusNearText(), Icons.Filled.Schedule)
                            }
                            StatusPill(
                                text = stringResource(
                                    if (agingSerious) R.string.dues_age_old else R.string.dues_age_mid,
                                ),
                                containerColor = container,
                                contentColor = content,
                                icon = icon,
                            )
                        }
                    }
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
                    Row {
                        // The polite nudge, one tap, over the channel the whole
                        // country already chases baki on.
                        if (due.amount.paisa > 0) {
                            IconButton(onClick = onRemind) {
                                Icon(
                                    imageVector = Icons.Filled.Chat,
                                    contentDescription = stringResource(R.string.dues_remind),
                                    tint = MaterialTheme.colorScheme.primary,
                                )
                            }
                        }
                        TextButton(onClick = onReview) {
                            Text(stringResource(R.string.dues_ledger))
                        }
                        TextButton(onClick = onSettle, enabled = due.amount.paisa > 0) {
                            Text(stringResource(R.string.dues_receive))
                        }
                    }
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
private fun LedgerDialog(
    customer: CustomerDue,
    entries: List<DuesLedgerEntry>,
    onDismiss: () -> Unit,
    onRemove: (String) -> Unit,
) {
    var pendingRemoval by remember { mutableStateOf<DuesLedgerEntry?>(null) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.dues_ledger_title, customer.customer)) },
        text = {
            if (entries.isEmpty()) {
                Text(
                    stringResource(R.string.dues_ledger_empty),
                    style = MaterialTheme.typography.bodyMedium,
                )
            } else {
                LazyColumn(
                    modifier = Modifier.heightIn(max = 360.dp),
                    verticalArrangement = Arrangement.spacedBy(Spacing.sm),
                ) {
                    items(entries, key = { it.id }) { entry ->
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Column(modifier = Modifier.weight(1f)) {
                                Text(
                                    text = ledgerDateLabel(entry.createdAtMillis),
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                                val label = if (entry.invoiceNumber.isNotBlank()) {
                                    stringResource(R.string.dues_ledger_invoice, entry.invoiceNumber)
                                } else if (entry.note.isNotBlank()) {
                                    entry.note
                                } else {
                                    stringResource(R.string.dues_ledger_entry)
                                }
                                Text(
                                    text = label,
                                    style = MaterialTheme.typography.bodyMedium,
                                    maxLines = 1,
                                )
                            }
                            Text(
                                text = (if (entry.amount.paisa < 0) "−" else "+") +
                                    MoneyFormat.format(entry.amount.abs()),
                                style = MaterialTheme.typography.titleSmall,
                                fontWeight = FontWeight.Bold,
                                color = if (entry.amount.paisa < 0) {
                                    MaterialTheme.colorScheme.secondary
                                } else {
                                    MaterialTheme.colorScheme.error
                                },
                                modifier = Modifier.padding(end = Spacing.sm),
                            )
                            // Corrections are same-day only: the ledger is a
                            // safety net for typos, not a history editor.
                            if (isSameDay(entry.createdAtMillis)) {
                                IconButton(onClick = { pendingRemoval = entry }) {
                                    Icon(
                                        imageVector = Icons.Filled.Delete,
                                        contentDescription = stringResource(R.string.dues_remove_entry),
                                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                                    )
                                }
                            }
                        }
                    }
                }
            }
        },
        confirmButton = {
            TextButton(onClick = onDismiss) { Text(stringResource(R.string.action_close)) }
        },
    )

    pendingRemoval?.let { entry ->
        AlertDialog(
            onDismissRequest = { pendingRemoval = null },
            title = { Text(stringResource(R.string.dues_remove_entry)) },
            text = {
                Text(
                    stringResource(
                        R.string.dues_remove_confirm,
                        MoneyFormat.format(entry.amount.abs()),
                    ),
                )
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        onRemove(entry.id)
                        pendingRemoval = null
                    },
                ) {
                    Text(stringResource(R.string.action_confirm))
                }
            },
            dismissButton = {
                TextButton(onClick = { pendingRemoval = null }) {
                    Text(stringResource(R.string.action_cancel))
                }
            },
        )
    }
}

@Composable
private fun ledgerDateLabel(millis: Long): String {
    val date = Instant.ofEpochMilli(millis).atZone(com.lipon.rakho.core.time.DhakaTime.ZONE).toLocalDate()
    return com.lipon.rakho.core.time.DhakaTime.format(date)
}

/** A ledger row can only be corrected on the day it was entered. */
private fun isSameDay(millis: Long): Boolean =
    Instant.ofEpochMilli(millis).atZone(com.lipon.rakho.core.time.DhakaTime.ZONE).toLocalDate() ==
        com.lipon.rakho.core.time.DhakaTime.today()

@Composable
private fun dueSinceLabel(millis: Long): String {
    // Dhaka time, like every other date in the app: a due recorded at 11 pm
    // must not read as the previous day just because the device zone differs.
    val date = Instant.ofEpochMilli(millis).atZone(com.lipon.rakho.core.time.DhakaTime.ZONE).toLocalDate()
    return stringResource(R.string.dues_since, com.lipon.rakho.core.time.DhakaTime.formatShort(date))
}
