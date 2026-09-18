package bd.rakho.pharmacy.feature.receive

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import bd.rakho.pharmacy.core.model.Medicine
import bd.rakho.pharmacy.core.money.Money
import bd.rakho.pharmacy.core.money.MoneyFormat
import bd.rakho.pharmacy.core.result.AppError
import bd.rakho.pharmacy.core.time.DhakaTime
import bd.rakho.pharmacy.data.remote.dto.PurchaseItemRequest
import bd.rakho.pharmacy.data.repo.InventoryRepository
import bd.rakho.pharmacy.data.repo.WriteOutcome
import bd.rakho.pharmacy.data.session.SessionStore
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import java.time.LocalDate

/** A line being entered, before it becomes a purchase item. */
data class ReceiveDraft(
    val medicineId: String = "",
    val medicineName: String = "",
    val batchNumber: String = "",
    val expiryText: String = "",
    val quantityText: String = "",
    val unitCostText: String = "",
    val sellingPriceText: String = "",
    val supplier: String = "",
) {
    val quantity: Int get() = quantityText.filter { it.isDigit() }.toIntOrNull() ?: 0
    val unitCost: Money get() = Money.parse(unitCostText)
    val sellingPrice: Money get() = Money.parse(sellingPriceText)

    /** True when the line is complete and safe to save. */
    fun validated(today: LocalDate): ReceiveValidation {
        if (medicineId.isBlank()) return ReceiveValidation.NoMedicine
        if (batchNumber.isBlank()) return ReceiveValidation.NoBatch
        val expiry = DhakaTime.parseDate(expiryText) ?: return ReceiveValidation.BadExpiry
        if (!expiry.isAfter(today)) return ReceiveValidation.PastExpiry
        if (quantity <= 0) return ReceiveValidation.NoQuantity
        if (unitCost.isZero) return ReceiveValidation.NoCost
        if (sellingPrice.isZero) return ReceiveValidation.NoPrice
        if (sellingPrice < unitCost) return ReceiveValidation.PriceBelowCost
        return ReceiveValidation.Ok
    }
}

enum class ReceiveValidation {
    Ok, NoMedicine, NoBatch, BadExpiry, PastExpiry, NoQuantity, NoCost, NoPrice, PriceBelowCost
}

sealed interface ReceiveMessage {
    data object Synced : ReceiveMessage
    data object Queued : ReceiveMessage
    data class Failed(val text: String) : ReceiveMessage
    data class Invalid(val reason: ReceiveValidation) : ReceiveMessage
}

data class ReceiveUiState(
    val draft: ReceiveDraft = ReceiveDraft(),
    val items: List<PurchaseItemRequest> = emptyList(),
    val itemLabels: List<String> = emptyList(),
    val medicineMatches: List<Medicine> = emptyList(),
    val busy: Boolean = false,
    val message: ReceiveMessage? = null,
) {
    val canSave: Boolean get() = items.isNotEmpty()
}

class ReceiveViewModel(
    private val inventory: InventoryRepository,
    private val sessionStore: SessionStore,
) : ViewModel() {

    private val draft = MutableStateFlow(ReceiveDraft())
    private val items = MutableStateFlow<List<PurchaseItemRequest>>(emptyList())
    private val labels = MutableStateFlow<List<String>>(emptyList())
    private val busy = MutableStateFlow(false)
    private val message = MutableStateFlow<ReceiveMessage?>(null)

    val state: StateFlow<ReceiveUiState> = combine(
        draft,
        combine(items, labels) { lines, names -> lines to names },
        inventory.observeMedicines(),
        combine(busy, message) { isBusy, msg -> isBusy to msg },
    ) { currentDraft, lineData, medicines, status ->
        val (lines, names) = lineData
        val (isBusy, msg) = status
        ReceiveUiState(
            draft = currentDraft,
            items = lines,
            itemLabels = names,
            medicineMatches = searchMedicines(medicines, currentDraft.medicineName),
            busy = isBusy,
            message = msg,
        )
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), ReceiveUiState())

    fun onDraftChange(update: (ReceiveDraft) -> ReceiveDraft) {
        draft.value = update(draft.value)
    }

    fun selectMedicine(medicine: Medicine) {
        draft.value = draft.value.copy(
            medicineId = medicine.id,
            medicineName = medicine.displayName,
            sellingPriceText = if (draft.value.sellingPriceText.isBlank()) {
                medicine.defaultSellingPrice.toBigDecimal().toPlainString()
            } else {
                draft.value.sellingPriceText
            },
        )
    }

    fun consumeMessage() {
        message.value = null
    }

    /** Adds the current line to the pending purchase. */
    fun addLine() {
        val current = draft.value
        when (val validation = current.validated(DhakaTime.today())) {
            ReceiveValidation.Ok -> Unit
            else -> {
                message.value = ReceiveMessage.Invalid(validation)
                return
            }
        }
        val item = PurchaseItemRequest(
            medicine = current.medicineId,
            batchNumber = current.batchNumber.trim(),
            expiryDate = DhakaTime.parseDate(current.expiryText)?.toString().orEmpty(),
            quantity = current.quantity,
            unitCost = current.unitCost.toBigDecimal().toPlainString(),
            sellingPrice = current.sellingPrice.toBigDecimal().toPlainString(),
            supplierName = current.supplier.trim(),
        )
        items.value = items.value + item
        labels.value = labels.value + listOf(
            current.medicineName,
            "#${current.batchNumber.trim()}",
            DhakaTime.parseDate(current.expiryText)?.let { DhakaTime.format(it) }.orEmpty(),
            "${current.quantity} \u00d7 ${MoneyFormat.format(current.sellingPrice)}",
        ).joinToString(" · ")
        draft.value = ReceiveDraft(
            supplier = current.supplier,
            medicineName = "",
        )
    }

    fun removeLine(index: Int) {
        items.value = items.value.filterIndexed { i, _ -> i != index }
        labels.value = labels.value.filterIndexed { i, _ -> i != index }
    }

    /** Saves the whole purchase; queues it when the shop has no connection. */
    fun save() {
        if (items.value.isEmpty() || busy.value) return
        busy.value = true
        viewModelScope.launch {
            sessionStore.ensureDeviceId()
            inventory.receiveStock(items.value).fold(
                onSuccess = { outcome ->
                    message.value = when (outcome) {
                        WriteOutcome.Synced -> ReceiveMessage.Synced
                        WriteOutcome.Queued -> ReceiveMessage.Queued
                    }
                    items.value = emptyList()
                    labels.value = emptyList()
                    draft.value = ReceiveDraft()
                },
                onFailure = { error ->
                    message.value = when (error) {
                        is AppError.Network -> ReceiveMessage.Queued
                        is AppError.Validation -> ReceiveMessage.Failed(error.detail)
                        else -> ReceiveMessage.Failed(error.message ?: "error")
                    }
                },
            )
            busy.value = false
        }
    }

    private fun searchMedicines(medicines: List<Medicine>, query: String): List<Medicine> {
        val needle = query.trim().lowercase()
        if (needle.length < 2) return emptyList()
        return medicines
            .filter {
                it.isActive && (
                    it.brandName.lowercase().contains(needle) ||
                        it.genericName.lowercase().contains(needle)
                    )
            }
            .take(6)
    }
}
