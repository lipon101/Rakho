package com.lipon.rakho.feature.receive

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.lipon.rakho.core.domain.MedicineSearch
import com.lipon.rakho.core.model.Medicine
import com.lipon.rakho.core.money.Money
import com.lipon.rakho.core.money.MoneyFormat
import com.lipon.rakho.core.result.AppError
import com.lipon.rakho.core.time.DhakaTime
import com.lipon.rakho.data.repo.PurchaseItemRequest
import com.lipon.rakho.data.repo.InventoryRepository
import com.lipon.rakho.data.repo.WriteOutcome
import com.lipon.rakho.data.session.SessionStore
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
    /** A medicine that did not exist was created; the draft now points at it. */
    data class StartedNewMedicine(val name: String) : ReceiveMessage
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

    /**
     * Starts a draft for a medicine that has no entry yet: creates it (server
     * or local-only), then points this draft at the fresh id so validation
     * and saving work exactly like a picked medicine.
     */
    fun startNewMedicineDraft(displayName: String, onReady: (String) -> Unit = {}) {
        val current = draft.value
        if (busy.value) return
        busy.value = true
        val fallbackPrice = if (current.unitCost.isZero) {
            if (current.sellingPrice.isZero) Money(1_00) else current.sellingPrice
        } else {
            current.unitCost
        }
        viewModelScope.launch {
            sessionStore.ensureDeviceId()
            val brand = displayName.substringBeforeLast(" ").ifBlank { displayName }.trim()
            val strength = displayName.substringAfterLast(" ", "").takeIf {
                it.any { ch -> ch.isDigit() }
            }.orEmpty()
            val request = com.lipon.rakho.data.repo.CreateMedicineRequest(
                brandName = brand.ifBlank { displayName.trim() },
                strength = strength,
                defaultSellingPrice = fallbackPrice.toBigDecimal().toPlainString(),
                lowStockThreshold = 10,
            )
            inventory.addMedicine(request).fold(
                onSuccess = { outcome ->
                    // The new medicine lands via the observed medicines flow;
                    // resolve its id there so offline and online behave alike.
                    val created = inventory.medicineByBrand(
                        request.brandName,
                        request.strength,
                    )
                    if (created != null) {
                        draft.value = draft.value.copy(
                            medicineId = created.id,
                            medicineName = created.displayName,
                        )
                        message.value = ReceiveMessage.StartedNewMedicine(created.displayName)
                        onReady(created.displayName)
                    } else {
                        message.value = when (outcome) {
                            WriteOutcome.Synced -> ReceiveMessage.Synced
                            WriteOutcome.Queued -> ReceiveMessage.Queued
                        }
                    }
                },
                onFailure = { error ->
                    message.value = ReceiveMessage.Failed(error.message ?: "error")
                },
            )
            busy.value = false
        }
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
        if (query.trim().isEmpty()) return emptyList()
        // Ranked live suggestions over the whole pharmacy — the same matcher
        // as New Sale and Stock, so the receive flow suggests identically.
        return MedicineSearch.rank(medicines, query).take(8)
    }
}
