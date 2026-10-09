package com.lipon.rakho.feature.expenses

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
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.MoneyOff
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.ExtendedFloatingActionButton
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
import androidx.compose.runtime.collectAsState
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
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.lipon.rakho.R
import com.lipon.rakho.core.money.Money
import com.lipon.rakho.core.money.MoneyFormat
import com.lipon.rakho.core.time.DhakaTime
import com.lipon.rakho.data.firebase.FirestoreExpense
import com.lipon.rakho.data.firebase.FirestoreRepository
import com.lipon.rakho.di.ContainerHolder
import com.lipon.rakho.ui.components.EmptyState
import com.lipon.rakho.ui.components.SectionHeader
import com.lipon.rakho.ui.theme.Radii
import com.lipon.rakho.ui.theme.Spacing
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import java.time.Instant

val EXPENSE_CATEGORIES = listOf(
    "Rent",
    "Electricity",
    "Staff Salary",
    "Medicine Returned",
    "Shop Supplies",
    "Transport",
    "Internet / Phone",
    "Miscellaneous",
)

data class ExpenseUiState(
    val expenses: List<FirestoreExpense> = emptyList(),
    val busy: Boolean = false,
    val message: String? = null,
)

class ExpenseViewModel(
    private val firestoreRepo: FirestoreRepository,
) : ViewModel() {

    val expenses: StateFlow<List<FirestoreExpense>> = firestoreRepo.observeExpenses()
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    private val _message = MutableStateFlow<Int?>(null)
    val message = _message.asStateFlow()

    private val _busy = MutableStateFlow(false)
    val busy = _busy.asStateFlow()

    fun addExpense(category: String, amountPaisa: Long, note: String) {
        if (amountPaisa <= 0 || category.isBlank()) return
        _busy.value = true
        viewModelScope.launch {
            runCatching {
                firestoreRepo.addExpense(category, amountPaisa, note)
                _message.value = R.string.expenses_saved
            }.onFailure {
                _message.value = R.string.expenses_failed
            }
            _busy.value = false
        }
    }

    fun deleteExpense(expenseId: String) {
        viewModelScope.launch {
            runCatching { firestoreRepo.deleteExpense(expenseId) }
        }
    }

    fun consumeMessage() { _message.value = null }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ExpenseScreen(onBack: () -> Unit) {
    val container = remember { ContainerHolder.get() }
    val viewModel = remember { ExpenseViewModel(container.firestoreRepo) }
    val expenses by viewModel.expenses.collectAsState()
    val busy by viewModel.busy.collectAsState()
    val message by viewModel.message.collectAsState()
    val snackbar = remember { SnackbarHostState() }
    var showAddDialog by remember { mutableStateOf(false) }

    val messageText = message?.let { stringResource(it) }
    LaunchedEffect(messageText) {
        if (messageText != null) {
            snackbar.showSnackbar(messageText)
            viewModel.consumeMessage()
        }
    }

    // Compute total this month
    val totalThisMonth = remember(expenses) {
        val now = DhakaTime.today()
        expenses.filter {
            val date = Instant.ofEpochMilli(it.createdAt).atZone(DhakaTime.ZONE).toLocalDate()
            date.month == now.month && date.year == now.year
        }.sumOf { it.amountPaisa }
    }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            TopAppBar(
                title = { Text(stringResource(R.string.expenses_title)) },
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
                onClick = { showAddDialog = true },
                icon = { Icon(Icons.Filled.Add, null) },
                text = { Text(stringResource(R.string.expenses_add)) },
            )
        },
    ) { padding ->
        LazyColumn(
            modifier = Modifier.fillMaxSize().padding(padding),
            contentPadding = PaddingValues(Spacing.lg),
            verticalArrangement = Arrangement.spacedBy(Spacing.md),
        ) {
            // Summary card
            item {
                Card(
                    shape = RoundedCornerShape(Radii.card),
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.errorContainer,
                    ),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Column(modifier = Modifier.padding(Spacing.xl)) {
                        Text(
                            text = stringResource(R.string.expenses_this_month),
                            style = MaterialTheme.typography.labelLarge,
                            color = MaterialTheme.colorScheme.onErrorContainer.copy(alpha = 0.8f),
                        )
                        Text(
                            text = MoneyFormat.format(Money.fromPaisa(totalThisMonth)),
                            style = MaterialTheme.typography.displaySmall,
                            fontWeight = FontWeight.Bold,
                            color = MaterialTheme.colorScheme.onErrorContainer,
                        )
                    }
                }
            }

            if (expenses.isEmpty()) {
                item {
                    EmptyState(
                        icon = Icons.Filled.MoneyOff,
                        title = stringResource(R.string.expenses_empty_title),
                        body = stringResource(R.string.expenses_empty_body),
                    )
                }
            } else {
                item { SectionHeader(stringResource(R.string.expenses_recent)) }
                items(expenses, key = { it.id }) { expense ->
                    ExpenseRow(expense = expense, onDelete = { viewModel.deleteExpense(expense.id) })
                }
            }
        }
    }

    if (showAddDialog) {
        AddExpenseDialog(
            busy = busy,
            onDismiss = { showAddDialog = false },
            onSave = { category, amount, note ->
                viewModel.addExpense(category, amount, note)
                showAddDialog = false
            },
        )
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun AddExpenseDialog(
    busy: Boolean,
    onDismiss: () -> Unit,
    onSave: (String, Long, String) -> Unit,
) {
    var category by remember { mutableStateOf(EXPENSE_CATEGORIES.first()) }
    var amount by remember { mutableStateOf("") }
    var note by remember { mutableStateOf("") }
    var dropdownOpen by remember { mutableStateOf(false) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.expenses_add)) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(Spacing.md)) {
                ExposedDropdownMenuBox(
                    expanded = dropdownOpen,
                    onExpandedChange = { dropdownOpen = it },
                ) {
                    OutlinedTextField(
                        value = category,
                        onValueChange = {},
                        readOnly = true,
                        label = { Text(stringResource(R.string.expenses_category)) },
                        trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = dropdownOpen) },
                        modifier = Modifier
                            .menuAnchor(androidx.compose.material3.ExposedDropdownMenuAnchorType.PrimaryNotEditable)
                            .fillMaxWidth(),
                    )
                    ExposedDropdownMenu(
                        expanded = dropdownOpen,
                        onDismissRequest = { dropdownOpen = false },
                    ) {
                        EXPENSE_CATEGORIES.forEach { cat ->
                            DropdownMenuItem(
                                text = { Text(cat) },
                                onClick = { category = cat; dropdownOpen = false },
                            )
                        }
                    }
                }
                OutlinedTextField(
                    value = amount,
                    onValueChange = { amount = it.filter { c -> c.isDigit() || c == '.' } },
                    label = { Text(stringResource(R.string.expenses_amount)) },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                    modifier = Modifier.fillMaxWidth(),
                )
                OutlinedTextField(
                    value = note,
                    onValueChange = { note = it },
                    label = { Text(stringResource(R.string.expenses_note)) },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
            }
        },
        confirmButton = {
            Button(
                onClick = {
                    val amountPaisa = (amount.toDoubleOrNull() ?: 0.0).let { (it * 100).toLong() }
                    onSave(category, amountPaisa, note)
                },
                enabled = amount.isNotBlank() && !busy,
            ) {
                Text(stringResource(R.string.action_save))
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text(stringResource(R.string.action_cancel)) }
        },
    )
}

@Composable
private fun ExpenseRow(expense: FirestoreExpense, onDelete: () -> Unit) {
    val date = Instant.ofEpochMilli(expense.createdAt)
        .atZone(DhakaTime.ZONE)
        .let { DhakaTime.format(it.toLocalDate()) }

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
                    text = expense.category,
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.SemiBold,
                )
                if (expense.note.isNotBlank()) {
                    Text(
                        text = expense.note,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                Text(
                    text = date,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Text(
                text = MoneyFormat.format(Money.fromPaisa(expense.amountPaisa)),
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.Bold,
                color = MaterialTheme.colorScheme.error,
            )
            IconButton(onClick = onDelete) {
                Icon(
                    Icons.Filled.Delete,
                    contentDescription = stringResource(R.string.action_delete),
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.size(20.dp),
                )
            }
        }
    }
}
