package com.lipon.rakho.data.firebase

import com.lipon.rakho.core.model.Batch
import com.lipon.rakho.core.model.Medicine
import com.lipon.rakho.core.model.PharmacyProfile
import com.lipon.rakho.core.model.Sale
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.stateIn

/**
 * The single set of shared pharmacy flows.
 *
 * Every screen reads through these StateFlows instead of opening its own
 * snapshot listener: one Firestore listener per collection serves the whole
 * app, which is what keeps read counts inside the free monthly quota. The
 * flows stay subscribed for a minute after the last reader leaves, so tab
 * switches never reconnect-and-refetch.
 */
class FirestoreData(
    firestore: FirestoreRepository,
    scope: CoroutineScope,
) {
    val medicines: StateFlow<List<Medicine>> =
        firestore.observeMedicines().stateIn(scope, KEEP, emptyList())

    val batches: StateFlow<List<Batch>> =
        firestore.observeBatches().stateIn(scope, KEEP, emptyList())

    val sales: StateFlow<List<Sale>> =
        firestore.observeSales().stateIn(scope, KEEP, emptyList())

    val dues: StateFlow<List<FirestoreDueEntry>> =
        firestore.observeDues().stateIn(scope, KEEP, emptyList())

    val customers: StateFlow<List<FirestoreCustomer>> =
        firestore.observeCustomers().stateIn(scope, KEEP, emptyList())

    val profile: StateFlow<PharmacyProfile?> =
        firestore.observeProfile().stateIn(scope, KEEP, null)

    /** Pending cloud writes across all collections, for the sync banner. */
    val pendingWrites: StateFlow<Int> = firestore.pendingWrites

    private companion object {
        val KEEP = SharingStarted.WhileSubscribed(60_000L)
    }
}
