package bd.rakho.pharmacy.data.repo

import bd.rakho.pharmacy.core.model.PendingOperation
import bd.rakho.pharmacy.core.model.PendingOperationType
import bd.rakho.pharmacy.core.result.AppError
import bd.rakho.pharmacy.data.local.LocalCache
import bd.rakho.pharmacy.data.remote.RakhoApi
import bd.rakho.pharmacy.data.remote.apiCall
import bd.rakho.pharmacy.data.remote.dto.CreateMedicineRequest
import bd.rakho.pharmacy.data.remote.dto.CreateSaleRequest
import bd.rakho.pharmacy.data.remote.dto.ReceivePurchaseRequest
import bd.rakho.pharmacy.data.remote.dto.WastageRequest
import bd.rakho.pharmacy.data.session.SessionStore
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
