package com.lipon.rakho.data.repo

import com.lipon.rakho.core.model.PendingOperation
import com.lipon.rakho.core.model.PendingOperationType
import com.lipon.rakho.core.result.AppError
import com.lipon.rakho.data.local.LocalCache
import com.lipon.rakho.data.remote.RakhoApi
import com.lipon.rakho.data.remote.apiCall
import com.lipon.rakho.data.remote.dto.CreateMedicineRequest
import com.lipon.rakho.data.remote.dto.CreateSaleRequest
import com.lipon.rakho.data.remote.dto.ReceivePurchaseRequest
import com.lipon.rakho.data.remote.dto.WastageRequest
import com.lipon.rakho.data.session.SessionStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.map
import kotlinx.serialization.json.Json

enum class SyncPhase { IDLE, SYNCING, OFFLINE, ERROR }

data class SyncStatus(
    val phase: SyncPhase = SyncPhase.IDLE,
    val pendingCount: Int = 0,
    val lastSyncAtMillis: Long = 0L,
    val lastError: String? = null,
    val lastSyncedOps: Int = 0,
)

/**
 * Owns the "sync the shop, then flush anything the shop did offline" cycle.
 *
 * Replay is idempotent by design: sales carry a device-generated invoice number
 * that the server rejects as a duplicate, which we interpret as "already
 * recorded", so a dropped connection mid-request can never double-book a sale.
 */
class SyncRepository(
    private val api: RakhoApi,
    private val cache: LocalCache,
    private val inventory: InventoryRepository,
    private val sales: SalesRepository,
    private val session: SessionStore,
    private val json: Json,
) {

    private val _status = MutableStateFlow(SyncStatus())
    val status: StateFlow<SyncStatus> = _status.asStateFlow()

    private val maxAttempts = 5

    val pendingCount: Flow<Int> = cache.revision.map { cache.pendingCount() }
        .combine(session.state.map { it.lastSyncAtMillis }) { pending, lastSync ->
            _status.value = _status.value.copy(pendingCount = pending, lastSyncAtMillis = lastSync)
            pending
        }

    /** Full cycle: push offline work first, then pull fresh state. */
    suspend fun syncNow(): Result<Unit> {
        if (!session.current().isConnected) {
            _status.value = _status.value.copy(phase = SyncPhase.IDLE)
            return Result.success(Unit)
        }
        _status.value = _status.value.copy(phase = SyncPhase.SYNCING, lastError = null)

        // First sync after connecting: upload anything recorded while the app
        // ran without a key, remapping local ids to real server ids. Cheap no-op
        // when there is nothing local to promote.
        runCatching { inventory.promoteLocalData() }

        val flushed = flushPending()

        val refreshResult = inventory.refresh()
        val salesResult = sales.refreshSales()

        val failure = (flushed as? FlushResult.Failed)?.error
            ?: refreshResult.exceptionOrNull()
            ?: salesResult.exceptionOrNull()

        return if (failure == null) {
            val now = System.currentTimeMillis()
            session.markSynced(now)
            _status.value = SyncStatus(
                phase = SyncPhase.IDLE,
                pendingCount = cache.pendingCount(),
                lastSyncAtMillis = now,
                lastSyncedOps = (flushed as? FlushResult.Processed)?.count ?: 0,
            )
            Result.success(Unit)
        } else {
            val phase = if (failure is AppError.Network) SyncPhase.OFFLINE else SyncPhase.ERROR
            _status.value = _status.value.copy(phase = phase, lastError = failure.message)
            Result.failure(failure)
        }
    }

    sealed interface FlushResult {
        data class Processed(val count: Int) : FlushResult
        data class Failed(val error: AppError) : FlushResult
    }

    suspend fun flushPending(): FlushResult {
        val queued = cache.pending()
        var processed = 0
        for (op in queued) {
            when (val outcome = replay(op)) {
                ReplayOutcome.Done -> {
                    cache.deleteOp(op.id)
                    processed++
                }
                ReplayOutcome.PermanentFailure -> {
                    // Unfixable payloads are dropped so they cannot block the
                    // queue forever; the error is kept for the settings screen.
                    cache.recordFailure(op.id, "rejected")
                    if (op.attempts + 1 >= maxAttempts) cache.deleteOp(op.id)
                }
                is ReplayOutcome.RetryLater -> {
                    cache.recordFailure(op.id, outcome.error.message ?: "retry")
                    return FlushResult.Failed(outcome.error)
                }
            }
        }
        return FlushResult.Processed(processed)
    }

    private sealed interface ReplayOutcome {
        data object Done : ReplayOutcome
        data object PermanentFailure : ReplayOutcome
        data class RetryLater(val error: AppError) : ReplayOutcome
    }

    private suspend fun replay(op: PendingOperation): ReplayOutcome {
        val result: Result<Any> = when (op.type) {
            PendingOperationType.SALE -> apiCall(json) {
                api.createSale(json.decodeFromString(CreateSaleRequest.serializer(), op.payload))
            }
            PendingOperationType.PURCHASE -> apiCall(json) {
                api.receivePurchase(
                    json.decodeFromString(ReceivePurchaseRequest.serializer(), op.payload),
                )
            }
            PendingOperationType.WASTAGE -> {
                val payload = json.decodeFromString(WastagePayload.serializer(), op.payload)
                apiCall(json) { api.writeOffBatch(payload.batchId, WastageRequest(payload.note)) }
            }
            PendingOperationType.MEDICINE -> apiCall(json) {
                api.createMedicine(json.decodeFromString(CreateMedicineRequest.serializer(), op.payload))
            }
        }

        return result.fold(
            onSuccess = { ReplayOutcome.Done },
            onFailure = { error ->
                when (error) {
                    is AppError.Network -> ReplayOutcome.RetryLater(error)
                    // A duplicate invoice means an earlier attempt actually
                    // reached the server: treat as success, never double-book.
                    is AppError.Validation ->
                        if (error.detail.contains("already exists", ignoreCase = true)) {
                            ReplayOutcome.Done
                        } else {
                            ReplayOutcome.PermanentFailure
                        }
                    is AppError.Unknown -> ReplayOutcome.RetryLater(error)
                    else -> ReplayOutcome.PermanentFailure
                }
            },
        )
    }
}
