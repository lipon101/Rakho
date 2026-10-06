package com.lipon.rakho.feature.stock

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.lipon.rakho.core.model.Batch
import com.lipon.rakho.core.model.Medicine
import com.lipon.rakho.core.model.StockFilter
import com.lipon.rakho.core.money.Money
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
    data class Failed(val text: String) : StockMessage
}

data class StockUiState(
    val query: String = "",
    val filter: StockFilter = StockFilter.ALL,
    val groups: List<StockGroup> = emptyList(),
    val busy: Boolean = false,
    val message: StockMessage? = null,
) {
    val totalUnits: Int get() = groups.sumOf { it.totalUnits }
    val totalValue: Money get() = groups.fold(Money.ZERO) { acc, group -> acc + group.totalValue }
}

class StockViewModel(private val inventory: InventoryRepository) : ViewModel() {

    private val query = MutableStateFlow("")
    private val filter = MutableStateFlow(StockFilter.ALL)
    private val busy = MutableStateFlow(false)
    private val message = MutableStateFlow<StockMessage?>(null)

    private val today: LocalDate get() = DhakaTime.today()

    val state: StateFlow<StockUiState> = combine(
        inventory.observeMedicines(),
        inventory.observeBatches(),
        query,
        filter,
        combine(busy, message) { isBusy, msg -> isBusy to msg },
    ) { medicines, batches, searchQuery, activeFilter, status ->
        val (isBusy, msg) = status
        StockUiState(
            query = searchQuery,
            filter = activeFilter,
            groups = buildGroups(medicines, batches, searchQuery, activeFilter),
            busy = isBusy,
            message = msg,
        )
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), StockUiState())

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

    fun refresh() {
        viewModelScope.launch { inventory.refresh() }
    }

    private fun buildGroups(
        medicines: List<Medicine>,
        batches: List<Batch>,
        searchQuery: String,
        activeFilter: StockFilter,
    ): List<StockGroup> {
        val needle = searchQuery.trim().lowercase()
        val byMedicine = batches.groupBy { it.medicineId }

        return medicines
            .asSequence()
            .filter { medicine ->
                needle.isEmpty() ||
                    medicine.brandName.lowercase().contains(needle) ||
                    medicine.genericName.lowercase().contains(needle) ||
                    medicine.strength.lowercase().contains(needle)
            }
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
