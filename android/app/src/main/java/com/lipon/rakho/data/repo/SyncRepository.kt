package com.lipon.rakho.data.repo

import com.google.firebase.firestore.FirebaseFirestore
import com.lipon.rakho.data.firebase.FirestoreData
import com.lipon.rakho.data.session.SessionStore
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch

enum class SyncPhase { IDLE, SYNCING, OFFLINE, ERROR }

data class SyncStatus(
    val phase: SyncPhase = SyncPhase.IDLE,
    val pendingCount: Int = 0,
    val lastSyncAtMillis: Long = 0L,
    val lastError: String? = null,
    val lastSyncedOps: Int = 0,
)

/**
 * Reflects Firestore's own sync cycle, rather than running one.
 *
 * Offline persistence queues every batched write and replays it automatically
 * when the network returns, so there is no pending-operations table to flush
 * and no pull-refresh to issue. What this repository does is observe: the
 * pending-writes counter (from the shared listeners' metadata) drives the
 * "syncing" banner, and a snapshots-in-sync callback marks the moment the
 * shop's data is truly up to date on both sides.
 */
class SyncRepository(
    private val data: FirestoreData,
    private val session: SessionStore,
    scope: CoroutineScope,
) {

    private val _status = MutableStateFlow(SyncStatus())
    val status: StateFlow<SyncStatus> = _status.asStateFlow()

    private val db = FirebaseFirestore.getInstance()

    /** Queued-write count, kept collected so [status] stays fresh app-wide. */
    val pendingCount: Flow<Int> = data.pendingWrites.map { pending ->
        _status.value = _status.value.copy(
            pendingCount = pending,
            phase = if (pending > 0) SyncPhase.SYNCING else SyncPhase.IDLE,
        )
        pending
    }

    init {
        scope.launch {
            _status.value = _status.value.copy(
                lastSyncAtMillis = session.current().lastSyncAtMillis,
            )
            pendingCount.collect { }
        }
        scope.launch {
            snapshotsInSync().collect {
                if (data.pendingWrites.value == 0) markSynced()
            }
        }
    }

    /**
     * Pull-to-refresh / manual "Sync now". There is nothing to push or pull by
     * hand — listeners are live and writes self-replay — so this just settles
     * the banner state: idle with a fresh timestamp when the queue is empty,
     * otherwise still syncing.
     */
    suspend fun syncNow(): Result<Unit> {
        if (data.pendingWrites.value > 0) {
            _status.value = _status.value.copy(phase = SyncPhase.SYNCING, lastError = null)
        } else {
            markSynced()
        }
        return Result.success(Unit)
    }

    private suspend fun markSynced() {
        val now = System.currentTimeMillis()
        session.markSynced(now)
        val flushed = _status.value.pendingCount
        _status.value = SyncStatus(
            phase = SyncPhase.IDLE,
            pendingCount = 0,
            lastSyncAtMillis = now,
            lastSyncedOps = flushed,
        )
    }

    /** Fires whenever every active listener has caught up with the server. */
    private fun snapshotsInSync(): Flow<Unit> = callbackFlow {
        val reg = db.addSnapshotsInSyncListener { trySend(Unit) }
        awaitClose { reg.remove() }
    }
}
