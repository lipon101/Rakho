package com.lipon.rakho.feature.stock

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.lipon.rakho.core.domain.MedicineSearch
import com.lipon.rakho.core.model.Batch
import com.lipon.rakho.core.model.Medicine
import com.lipon.rakho.core.model.StockFilter
import com.lipon.rakho.core.money.Money
import com.lipon.rakho.data.repo.UpdateBatchRequest
import com.lipon.rakho.data.repo.UpdateMedicineRequest
import com.lipon.rakho.core.result.AppError
import com.lipon.rakho.core.time.DhakaTime
import com.lipon.rakho.core.time.ExpiryRules
import com.lipon.rakho.core.time.ExpiryStatus
import com.lipon.rakho.data.repo.InventoryRepository
import com.lipon.rakho.data.repo.WriteOutcome
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import java.time.LocalDate

/** One batch row as shown on the expiry radar. */
data class StockBatchRow(
    val batch: Batch,
    val status: ExpiryStatus,
    val daysUntilExpiry: Long,
) {
    val value: Money get() = batch.stockValue
}

/** A medicine with all of its batches and totals. */
data class StockGroup(
    val medicine: Medicine,
    val batches: List<StockBatchRow>,
    val totalUnits: Int,
    val totalValue: Money,
) {
    val isLow: Boolean get() = totalUnits <= medicine.lowStockThreshold
    val worstStatus: ExpiryStatus
        get() = batches.minByOrNull { it.batch.expiryDate }?.status ?: ExpiryStatus.HEALTHY
}

sealed interface StockMessage {
    data object WrittenOff : StockMessage
    data object WriteOffQueued : StockMessage
    data object MedicineSaved : StockMessage
    data object BatchSaved : StockMessage
    data object EditQueued : StockMessage
    data class Failed(val text: String) : StockMessage
}

data class StockUiState(
    val query: String = "",
    val filter: StockFilter = StockFilter.ALL,
    val groups: List<StockGroup> = emptyList(),
    /** Live counts per radar filter, computed on the full pharmacy — never on the filtered view. */
    val counts: StockCounts = StockCounts(),
    /** Total medicines in the pharmacy, so a filtered view can say "3 of 40". */
    val totalGroupCount: Int = 0,
    val busy: Boolean = false,
    val message: StockMessage? = null,
    /** Medicine currently open in the edit dialog, if any. */
    val editingMedicine: Medicine? = null,
    /** Batch currently open in the edit dialog, if any. */
    val editingBatch: StockBatchRow? = null,
) {
    val totalUnits: Int get() = groups.sumOf { it.totalUnits }
    val totalValue: Money get() = groups.fold(Money.ZERO) { acc, group -> acc + group.totalValue }
    val groupCount: Int get() = groups.size
    val isFiltered: Boolean get() = filter != StockFilter.ALL || query.isNotBlank()
}

/** Live medicine counts per radar filter, derived from the full stock list. */
data class StockCounts(
    val expiring: Int = 0,
    val expired: Int = 0,
    val low: Int = 0,
)

class StockViewModel(private val inventory: InventoryRepository) : ViewModel() {

    private val query = MutableStateFlow("")
    private val filter = MutableStateFlow(StockFilter.ALL)
    private val busy = MutableStateFlow(false)
    private val message = MutableStateFlow<StockMessage?>(null)
    private val editTargetMedicine = MutableStateFlow<Medicine?>(null)
    private val editTargetBatch = MutableStateFlow<StockBatchRow?>(null)

    fun openEditMedicine(medicine: Medicine) {
        editTargetMedicine.value = medicine
    }

    fun openEditBatch(row: StockBatchRow) {
        editTargetBatch.value = row
    }

    fun dismissEdit() {
        editTargetMedicine.value = null
        editTargetBatch.value = null
    }

    private val today: LocalDate get() = DhakaTime.today()

    val state: StateFlow<StockUiState> = combine(
        inventory.observeMedicines(),
        inventory.observeBatches(),
        query,
        filter,
        combine(busy, message, editTargetMedicine, editTargetBatch) {
                isBusy, msg, editingMedicine, editingBatch ->
            EditState(isBusy, msg, editingMedicine, editingBatch)
        },
    ) { medicines, batches, searchQuery, activeFilter, edit ->
        // Counts always describe the FULL pharmacy (no search, no filter), so
        // the chips answer "how many are expiring?" even while filtered.
        val allGroups = buildGroups(medicines, batches, "", StockFilter.ALL)
        StockUiState(
            query = searchQuery,
            filter = activeFilter,
            groups = buildGroups(medicines, batches, searchQuery, activeFilter),
            counts = StockCounts(
                expiring = allGroups.count { group ->
                    group.batches.any {
                        it.status == ExpiryStatus.EXPIRING_SOON || it.status == ExpiryStatus.EXPIRES_TODAY
                    }
                },
                expired = allGroups.count { group ->
                    group.batches.any { it.status == ExpiryStatus.EXPIRED }
                },
                low = allGroups.count { it.isLow },
            ),
            totalGroupCount = allGroups.size,
            busy = edit.isBusy,
            message = edit.message,
            editingMedicine = edit.medicine,
            editingBatch = edit.batch,
        )
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), StockUiState())

    private data class EditState(
        val isBusy: Boolean,
        val message: StockMessage?,
        val medicine: Medicine?,
        val batch: StockBatchRow?,
    )

    fun onQueryChange(value: String) {
        query.value = value
    }

    fun onFilterChange(value: StockFilter) {
        filter.value = value
    }

    fun consumeMessage() {
        message.value = null
    }

    /** Writes off an expired/damaged batch; queueing keeps the shop moving offline. */
    fun writeOff(batchId: String, note: String) {
        if (busy.value) return
        busy.value = true
        viewModelScope.launch {
            inventory.writeOffBatch(batchId, note).fold(
                onSuccess = { outcome ->
                    message.value = when (outcome) {
                        WriteOutcome.Synced -> StockMessage.WrittenOff
                        WriteOutcome.Queued -> StockMessage.WriteOffQueued
                    }
                },
                onFailure = { error ->
                    message.value = StockMessage.Failed(error.message ?: "error")
                },
            )
            busy.value = false
        }
    }

    /** Corrects a medicine's details; the cache is patched instantly so every tab reflects it. */
    fun updateMedicine(request: UpdateMedicineRequest) {
        val target = state.value.editingMedicine ?: return
        if (busy.value) return
        busy.value = true
        viewModelScope.launch {
            inventory.updateMedicine(target.id, request).fold(
                onSuccess = { outcome ->
                    message.value = when (outcome) {
                        WriteOutcome.Synced -> StockMessage.MedicineSaved
                        WriteOutcome.Queued -> StockMessage.EditQueued
                    }
                    editTargetMedicine.value = null
                },
                onFailure = { error ->
                    message.value = StockMessage.Failed(error.message ?: "error")
                },
            )
            busy.value = false
        }
    }

    /** Corrects a batch; [quantityAvailable] is the absolute counted shelf number, never a delta. */
    fun updateBatch(request: UpdateBatchRequest) {
        val target = state.value.editingBatch ?: return
        if (busy.value) return
        busy.value = true
        viewModelScope.launch {
            inventory.updateBatch(target.batch.id, request).fold(
                onSuccess = { outcome ->
                    message.value = when (outcome) {
                        WriteOutcome.Synced -> StockMessage.BatchSaved
                        WriteOutcome.Queued -> StockMessage.EditQueued
                    }
                    editTargetBatch.value = null
                },
                onFailure = { error ->
                    message.value = StockMessage.Failed(error.message ?: "error")
                },
            )
            busy.value = false
        }
    }

    private fun buildGroups(
        medicines: List<Medicine>,
        batches: List<Batch>,
        searchQuery: String,
        activeFilter: StockFilter,
    ): List<StockGroup> {
        val byMedicine = batches.groupBy { it.medicineId }

        // Ranked live search over every medicine — same matcher as New Sale,
        // so typing filters the whole pharmacy instantly with no hidden caps.
        return MedicineSearch.rank(medicines, searchQuery)
            .asSequence()
            .map { medicine ->
                val rows = byMedicine[medicine.id].orEmpty().map { batch ->
                    val days = ExpiryRules.daysUntil(batch.expiryDate, today)
                    StockBatchRow(
                        batch = batch,
                        status = ExpiryRules.status(batch.expiryDate, today),
                        daysUntilExpiry = days,
                    )
                }
                StockGroup(
                    medicine = medicine,
                    batches = rows.sortedBy { it.batch.expiryDate },
                    totalUnits = rows.sumOf { it.batch.quantityAvailable },
                    totalValue = rows.fold(Money.ZERO) { acc, row -> acc + row.value },
                )
            }
            .filter { group ->
                when (activeFilter) {
                    StockFilter.ALL -> true
                    StockFilter.EXPIRING -> group.batches.any {
                        it.status == ExpiryStatus.EXPIRING_SOON || it.status == ExpiryStatus.EXPIRES_TODAY
                    }
                    StockFilter.EXPIRED -> group.batches.any { it.status == ExpiryStatus.EXPIRED }
                    StockFilter.LOW -> group.isLow
                }
            }
            .sortedWith(compareBy({ it.worstStatus.ordinal }, { it.medicine.brandName }))
            .toList()
    }
}

/** Convenience for the settings/report screens. */
fun StockUiState.isEmpty(): Boolean = groups.isEmpty()
