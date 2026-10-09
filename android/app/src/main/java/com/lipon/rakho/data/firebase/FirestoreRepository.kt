package com.lipon.rakho.data.firebase

import com.google.firebase.auth.FirebaseAuth
import com.google.firebase.firestore.FirebaseFirestore
import com.google.firebase.firestore.MetadataChanges
import com.google.firebase.firestore.Query
import com.google.firebase.firestore.SetOptions
import com.google.firebase.firestore.Source
import com.lipon.rakho.core.model.Batch
import com.lipon.rakho.core.model.BatchAllocation
import com.lipon.rakho.core.model.CartLine
import com.lipon.rakho.core.model.Medicine
import com.lipon.rakho.core.model.PaymentMethod
import com.lipon.rakho.core.model.PharmacyProfile
import com.lipon.rakho.core.model.Sale
import com.lipon.rakho.core.money.Money
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.tasks.await
import java.time.Instant
import java.time.LocalDate

/**
 * All Firestore operations for a single pharmacy — the app's only store.
 *
 * Data lives at:
 *   pharmacies/{uid}/medicines/{medicineId}
 *   pharmacies/{uid}/batches/{batchId}
 *   pharmacies/{uid}/sales/{saleId}
 *   pharmacies/{uid}/dues/{dueId}
 *   pharmacies/{uid}/purchases/{purchaseId}
 *   pharmacies/{uid}/expenses/{expenseId}
 *   pharmacies/{uid}/profile (single document)
 *
 * Writes are composed with [FirebaseFirestore.batch] rather than
 * [FirebaseFirestore.runTransaction] on purpose: batched writes are queued by
 * the offline persistence layer and replayed exactly once when the network
 * returns, so a counter sale lands even when the internet is down. The batch
 * quantities are allocated on device (FEFO) before the write, and every
 * decrement is a [com.google.firebase.firestore.FieldValue.increment], so a
 * replay adjusts the server value without ever double-booking.
 *
 * Snapshot listeners are registered with [MetadataChanges.INCLUDE] so the
 * pending-writes counter below reflects local mutations immediately: this is
 * what drives the sync banner while a write waits for network.
 */
class FirestoreRepository {

    private val db = FirebaseFirestore.getInstance()
    private val auth = FirebaseAuth.getInstance()

    /** Current user's UID — the pharmacy's cloud identity. */
    val uid: String
        get() = auth.currentUser?.uid
            ?: error("FirestoreRepository used before authentication")

    private fun pharmacyDoc() = db.collection("pharmacies").document(uid)
    private fun medicines() = pharmacyDoc().collection("medicines")
    private fun batches() = pharmacyDoc().collection("batches")
    private fun sales() = pharmacyDoc().collection("sales")
    private fun dues() = pharmacyDoc().collection("dues")
    private fun purchases() = pharmacyDoc().collection("purchases")
    private fun expenses() = pharmacyDoc().collection("expenses")
    private fun customers() = pharmacyDoc().collection("customers")

    // ─────────────────────────────────────────────────────────────────────
    // Pending-writes tracking (powers the sync banner)
    // ─────────────────────────────────────────────────────────────────────

    private val pendingByCollection = MutableStateFlow<Map<String, Int>>(emptyMap())
    private val _pendingWrites = MutableStateFlow(0)

    /** How many queued writes the local cache still holds, across collections. */
    val pendingWrites: StateFlow<Int> = _pendingWrites.asStateFlow()

    private fun notePending(collection: String, count: Int) {
        pendingByCollection.value = pendingByCollection.value + (collection to count)
        _pendingWrites.value = pendingByCollection.value.values.sum()
    }

    // ─────────────────────────────────────────────────────────────────────
    // Real-time flows (Firestore snapshot listeners)
    // ─────────────────────────────────────────────────────────────────────

    // The query lambdas are evaluated at collection time, not now: the app
    // builds these flows before anyone has signed in, and the pharmacy path
    // needs a uid. A re-subscription after sign-out reads the new identity.
    fun observeMedicines(): Flow<List<Medicine>> = listen("medicines", {
        medicines().whereEqualTo("isActive", true)
    }) { snap ->
        snap?.documents?.mapNotNull { it.toMedicine() }.orEmpty()
    }

    fun observeBatches(activeOnly: Boolean = false): Flow<List<Batch>> = listen("batches", {
        if (activeOnly) batches().whereGreaterThan("quantityAvailable", 0) else batches()
    }) { snap ->
        snap?.documents?.mapNotNull { it.toBatch() }.orEmpty()
    }

    fun observeSales(): Flow<List<Sale>> = listen("sales", {
        sales().orderBy("soldAt", Query.Direction.DESCENDING).limit(1000)
    }) { snap ->
        snap?.documents?.mapNotNull { it.toSale() }.orEmpty()
    }

    fun observeDues(): Flow<List<FirestoreDueEntry>> = listen("dues", {
        dues().orderBy("createdAt", Query.Direction.DESCENDING).limit(2000)
    }) { snap ->
        snap?.documents?.mapNotNull { doc ->
            val id = doc.id
            val customer = doc.getString("customer") ?: return@mapNotNull null
            val amountPaisa = doc.getLong("amountPaisa") ?: return@mapNotNull null
            val createdAt = doc.getLong("createdAt") ?: return@mapNotNull null
            FirestoreDueEntry(
                id = id,
                customer = customer,
                amountPaisa = amountPaisa,
                createdAt = createdAt,
                invoiceNumber = doc.getString("invoiceNumber").orEmpty(),
                note = doc.getString("note").orEmpty(),
            )
        }.orEmpty()
    }

    fun observeExpenses(): Flow<List<FirestoreExpense>> = listen("expenses", {
        expenses().orderBy("createdAt", Query.Direction.DESCENDING).limit(500)
    }) { snap ->
        snap?.documents?.mapNotNull { doc ->
            val id = doc.id
            val category = doc.getString("category") ?: return@mapNotNull null
            val amountPaisa = doc.getLong("amountPaisa") ?: return@mapNotNull null
            val createdAt = doc.getLong("createdAt") ?: return@mapNotNull null
            FirestoreExpense(
                id = id,
                category = category,
                amountPaisa = amountPaisa,
                note = doc.getString("note").orEmpty(),
                createdAt = createdAt,
            )
        }.orEmpty()
    }

    fun observePurchases(): Flow<List<FirestorePurchase>> = listen("purchases", {
        purchases().orderBy("receivedAt", Query.Direction.DESCENDING).limit(500)
    }) { snap ->
        snap?.documents?.mapNotNull { doc ->
            val id = doc.id
            val receivedAt = doc.getLong("receivedAt") ?: return@mapNotNull null
            @Suppress("UNCHECKED_CAST")
            val items = (doc.get("items") as? List<Map<String, Any>>)?.mapNotNull { item ->
                FirestorePurchaseItem(
                    medicineId = item["medicineId"] as? String ?: return@mapNotNull null,
                    medicineName = item["medicineName"] as? String ?: "",
                    batchNumber = item["batchNumber"] as? String ?: "",
                    expiryDate = item["expiryDate"] as? String ?: "",
                    quantity = (item["quantity"] as? Long)?.toInt() ?: 0,
                    unitCostPaisa = (item["unitCostPaisa"] as? Long) ?: 0L,
                    sellingPricePaisa = (item["sellingPricePaisa"] as? Long) ?: 0L,
                )
            }.orEmpty()
            FirestorePurchase(id, doc.getString("supplier").orEmpty(), receivedAt, items)
        }.orEmpty()
    }

    fun observeProfile(): Flow<PharmacyProfile?> = listenDoc("profile", { pharmacyDoc() }) { snap ->
        snap?.takeIf { it.exists() }?.let {
            PharmacyProfile(
                name = it.getString("name").orEmpty(),
                currency = it.getString("currency") ?: "BDT",
                address = it.getString("address").orEmpty(),
                phone = it.getString("phone").orEmpty(),
            )
        }
    }

    /** The customer phone book that powers baki reminders. */
    fun observeCustomers(): Flow<List<FirestoreCustomer>> = listen("customers", {
        customers().orderBy("name", Query.Direction.ASCENDING).limit(1000)
    }) { snap ->
        snap?.documents?.mapNotNull { doc ->
            val id = doc.id
            val name = doc.getString("name") ?: return@mapNotNull null
            FirestoreCustomer(
                id = id,
                name = name,
                phone = doc.getString("phone").orEmpty(),
                note = doc.getString("note").orEmpty(),
            )
        }.orEmpty()
    }

    /** One listener shape for collection/query listeners, with metadata tracking. */
    private fun <T> listen(
        collection: String,
        query: () -> Query,
        mapper: (com.google.firebase.firestore.QuerySnapshot?) -> T,
    ): Flow<T> = callbackFlow {
        val reg = query().addSnapshotListener(MetadataChanges.INCLUDE) { snap, err ->
            if (err != null) {
                close(err)
                return@addSnapshotListener
            }
            notePending(collection, snap?.documents?.count { it.metadata.hasPendingWrites() } ?: 0)
            trySend(mapper(snap))
        }
        awaitClose { reg.remove() }
    }

    /** Profile-style single-document listener. */
    private fun <T> listenDoc(
        collection: String,
        doc: () -> com.google.firebase.firestore.DocumentReference,
        mapper: (com.google.firebase.firestore.DocumentSnapshot?) -> T,
    ): Flow<T> = callbackFlow {
        val reg = doc().addSnapshotListener(MetadataChanges.INCLUDE) { snap, err ->
            if (err != null) {
                close(err)
                return@addSnapshotListener
            }
            notePending(collection, if (snap?.metadata?.hasPendingWrites() == true) 1 else 0)
            trySend(mapper(snap))
        }
        awaitClose { reg.remove() }
    }

    // ─────────────────────────────────────────────────────────────────────
    // Writes (offline-safe batched mutations)
    // ─────────────────────────────────────────────────────────────────────

    /** Creates or updates the pharmacy profile document. */
    suspend fun saveProfile(name: String, phone: String, address: String) {
        pharmacyDoc().set(
            mapOf(
                "name" to name,
                "phone" to phone,
                "address" to address,
                "currency" to "BDT",
                "updatedAt" to System.currentTimeMillis(),
            ),
            SetOptions.merge(),
        ).await()
    }

    /** Adds a new medicine. Returns its Firestore ID. */
    suspend fun addMedicine(
        brandName: String,
        genericName: String,
        strength: String,
        dosageForm: String,
        barcode: String = "",
        sellingPricePaisa: Long,
        lowStockThreshold: Int = 10,
        catalogMedicineId: Long? = null,
    ): String {
        val doc = medicines().document()
        doc.set(
            mapOf(
                "id" to doc.id,
                "brandName" to brandName,
                "genericName" to genericName,
                "strength" to strength,
                "dosageForm" to dosageForm,
                "barcode" to barcode,
                "defaultSellingPricePaisa" to sellingPricePaisa,
                "lowStockThreshold" to lowStockThreshold,
                "availableQuantity" to 0,
                "isActive" to true,
                "catalogMedicineId" to catalogMedicineId,
                "createdAt" to System.currentTimeMillis(),
                "updatedAt" to System.currentTimeMillis(),
            ),
        ).await()
        return doc.id
    }

    /** Updates editable fields on an existing medicine. */
    suspend fun updateMedicine(
        medicineId: String,
        brandName: String? = null,
        genericName: String? = null,
        strength: String? = null,
        dosageForm: String? = null,
        barcode: String? = null,
        sellingPricePaisa: Long? = null,
        lowStockThreshold: Int? = null,
    ) {
        val updates = mutableMapOf<String, Any>("updatedAt" to System.currentTimeMillis())
        brandName?.let { updates["brandName"] = it }
        genericName?.let { updates["genericName"] = it }
        strength?.let { updates["strength"] = it }
        dosageForm?.let { updates["dosageForm"] = it }
        barcode?.let { updates["barcode"] = it }
        sellingPricePaisa?.let { updates["defaultSellingPricePaisa"] = it }
        lowStockThreshold?.let { updates["lowStockThreshold"] = it }
        medicines().document(medicineId).update(updates).await()
    }

    /**
     * Receives a stock purchase: creates the batch documents, increments each
     * medicine's available quantity and files the purchase record — one batch
     * write, queued offline and replayed once. Returns the purchase document ID.
     */
    suspend fun receiveStock(
        items: List<ReceiveStockItem>,
        supplier: String = "",
    ): String {
        val now = System.currentTimeMillis()
        val purchaseId = purchases().document().id
        val batch = db.batch()
        items.forEach { item ->
            val batchDoc = batches().document()
            batch.set(
                batchDoc,
                mapOf(
                    "id" to batchDoc.id,
                    "medicineId" to item.medicineId,
                    "medicineName" to item.medicineName,
                    "medicineStrength" to item.medicineStrength,
                    "batchNumber" to item.batchNumber,
                    "expiryDate" to item.expiryDate.toString(),
                    "unitCostPaisa" to item.unitCostPaisa,
                    "sellingPricePaisa" to item.sellingPricePaisa,
                    "quantityReceived" to item.quantity,
                    "quantityAvailable" to item.quantity,
                    "receivedAt" to now,
                ),
            )
        }
        items.groupBy { it.medicineId }.forEach { (medicineId, grouped) ->
            val totalQty = grouped.sumOf { it.quantity }
            batch.update(
                medicines().document(medicineId),
                mapOf(
                    "availableQuantity" to com.google.firebase.firestore.FieldValue
                        .increment(totalQty.toLong()),
                    "updatedAt" to now,
                ),
            )
        }
        batch.set(
            purchases().document(purchaseId),
            mapOf(
                "id" to purchaseId,
                "supplier" to supplier,
                "receivedAt" to now,
                "items" to items.map { item ->
                    mapOf(
                        "medicineId" to item.medicineId,
                        "medicineName" to item.medicineName,
                        "batchNumber" to item.batchNumber,
                        "expiryDate" to item.expiryDate.toString(),
                        "quantity" to item.quantity,
                        "unitCostPaisa" to item.unitCostPaisa,
                        "sellingPricePaisa" to item.sellingPricePaisa,
                    )
                },
                "totalCostPaisa" to items.sumOf { it.unitCostPaisa * it.quantity },
            ),
        )
        batch.commit().await()
        return purchaseId
    }

    /**
     * Records a completed sale. The lines arrive with their FEFO allocations
     * already resolved on device; this write decrements exactly those batches
     * (increment-based, so a queued replay cannot double-deduct), files the
     * sale document, and books the customer due when payment is CREDIT.
     */
    suspend fun recordSale(
        invoiceNumber: String,
        lines: List<CartLine>,
        paymentMethod: PaymentMethod,
        discount: Money,
        note: String,
        customerName: String = "",
    ): String {
        val saleId = sales().document().id
        val now = System.currentTimeMillis()
        val batch = db.batch()

        lines.forEach { line ->
            line.allocations.forEach { alloc ->
                batch.update(
                    batches().document(alloc.batchId),
                    mapOf(
                        "quantityAvailable" to com.google.firebase.firestore.FieldValue
                            .increment(-alloc.quantity.toLong()),
                        "updatedAt" to now,
                    ),
                )
            }
            val totalDeducted = line.allocations.sumOf { it.quantity }
            batch.update(
                medicines().document(line.medicineId),
                mapOf(
                    "availableQuantity" to com.google.firebase.firestore.FieldValue
                        .increment(-totalDeducted.toLong()),
                    "updatedAt" to now,
                ),
            )
        }

        val subtotalPaisa = lines.sumOf { it.unitPrice.paisa * it.quantity }
        val totalPaisa = (subtotalPaisa - discount.paisa).coerceAtLeast(0L)

        batch.set(
            sales().document(saleId),
            mapOf(
                "id" to saleId,
                "invoiceNumber" to invoiceNumber,
                "soldAt" to now,
                "subtotalPaisa" to subtotalPaisa,
                "discountPaisa" to discount.paisa,
                "totalPaisa" to totalPaisa,
                "paymentMethod" to paymentMethod.name,
                "note" to note,
                "customerName" to customerName,
                "lines" to lines.map { line ->
                    mapOf(
                        "medicineId" to line.medicineId,
                        "medicineName" to line.medicineName,
                        "quantity" to line.quantity,
                        "unitPricePaisa" to line.unitPrice.paisa,
                        "lineTotalPaisa" to line.unitPrice.paisa * line.quantity,
                        "allocations" to line.allocations.map { alloc ->
                            mapOf(
                                "batchId" to alloc.batchId,
                                "batchNumber" to alloc.batchNumber,
                                "expiryDate" to alloc.expiryDate.toString(),
                                "quantity" to alloc.quantity,
                                "unitCostPaisa" to alloc.unitCost.paisa,
                            )
                        },
                    )
                },
            ),
        )

        // If CREDIT, book the due in the same write so a sale can never exist
        // without its matching baki entry.
        if (paymentMethod == PaymentMethod.CREDIT && customerName.isNotBlank()) {
            val dueDoc = dues().document()
            batch.set(
                dueDoc,
                mapOf(
                    "id" to dueDoc.id,
                    "customer" to customerName,
                    "amountPaisa" to totalPaisa,
                    "invoiceNumber" to invoiceNumber,
                    "note" to note,
                    "createdAt" to now,
                ),
            )
        }
        batch.commit().await()
        return saleId
    }

    /** Books a due entry (positive = owed). */
    suspend fun addDueEntry(customer: String, invoiceNumber: String, amountPaisa: Long, note: String) {
        val doc = dues().document()
        doc.set(
            mapOf(
                "id" to doc.id,
                "customer" to customer,
                "amountPaisa" to amountPaisa,
                "invoiceNumber" to invoiceNumber,
                "note" to note,
                "createdAt" to System.currentTimeMillis(),
            ),
        ).await()
    }

    /** Settles a due by recording a negative-amount entry. */
    suspend fun settleDue(customer: String, amountPaisa: Long, note: String = "") {
        val doc = dues().document()
        doc.set(
            mapOf(
                "id" to doc.id,
                "customer" to customer,
                "amountPaisa" to -amountPaisa,
                "invoiceNumber" to "",
                "note" to note.ifBlank { "Payment received" },
                "createdAt" to System.currentTimeMillis(),
            ),
        ).await()
    }

    suspend fun removeDueEntry(entryId: String) {
        dues().document(entryId).delete().await()
    }

    /** Adds or updates a customer book entry. Returns the document id. */
    suspend fun saveCustomer(customerId: String?, name: String, phone: String, note: String): String {
        val doc = if (customerId.isNullOrBlank()) customers().document() else customers().document(customerId)
        doc.set(
            mapOf(
                "id" to doc.id,
                "name" to name,
                "phone" to phone,
                "note" to note,
                "updatedAt" to System.currentTimeMillis(),
            ),
            SetOptions.merge(),
        ).await()
        return doc.id
    }

    suspend fun deleteCustomer(customerId: String) {
        customers().document(customerId).delete().await()
    }

    /** Writes off a batch (sets quantity to 0 and adjusts the medicine total). */
    suspend fun writeOffBatch(batchId: String, note: String = "") {
        val batchSnap = batches().document(batchId).get(Source.CACHE).await()
        val medicineId = batchSnap.getString("medicineId") ?: return
        val available = batchSnap.getLong("quantityAvailable") ?: 0L
        val now = System.currentTimeMillis()
        val batch = db.batch()
        batch.update(
            batches().document(batchId),
            mapOf(
                "quantityAvailable" to 0L,
                "updatedAt" to now,
                "writeOffNote" to note,
            ),
        )
        batch.update(
            medicines().document(medicineId),
            mapOf(
                "availableQuantity" to com.google.firebase.firestore.FieldValue
                    .increment(-available),
                "updatedAt" to now,
            ),
        )
        batch.commit().await()
    }

    /** Updates a batch's details (absolute quantity, expiry, prices). */
    suspend fun updateBatch(
        batchId: String,
        batchNumber: String? = null,
        expiryDate: LocalDate? = null,
        unitCostPaisa: Long? = null,
        sellingPricePaisa: Long? = null,
        quantityAvailable: Int? = null,
    ) {
        val updates = mutableMapOf<String, Any>("updatedAt" to System.currentTimeMillis())
        batchNumber?.let { updates["batchNumber"] = it }
        expiryDate?.let { updates["expiryDate"] = it.toString() }
        unitCostPaisa?.let { updates["unitCostPaisa"] = it }
        sellingPricePaisa?.let { updates["sellingPricePaisa"] = it }

        if (quantityAvailable == null) {
            batches().document(batchId).update(updates).await()
            return
        }

        // The counted quantity is absolute; the medicine total moves by the
        // difference between the counted shelf and what the cache holds.
        val batchSnap = batches().document(batchId).get(Source.CACHE).await()
        val oldQty = batchSnap.getLong("quantityAvailable") ?: 0L
        val medicineId = batchSnap.getString("medicineId") ?: ""
        val delta = quantityAvailable.toLong() - oldQty
        updates["quantityAvailable"] = quantityAvailable.toLong()
        val batch = db.batch()
        batch.update(batches().document(batchId), updates)
        if (medicineId.isNotBlank() && delta != 0L) {
            batch.update(
                medicines().document(medicineId),
                mapOf(
                    "availableQuantity" to com.google.firebase.firestore.FieldValue
                        .increment(delta),
                    "updatedAt" to System.currentTimeMillis(),
                ),
            )
        }
        batch.commit().await()
    }

    /** Records an expense. */
    suspend fun addExpense(category: String, amountPaisa: Long, note: String): String {
        val doc = expenses().document()
        doc.set(
            mapOf(
                "id" to doc.id,
                "category" to category,
                "amountPaisa" to amountPaisa,
                "note" to note,
                "createdAt" to System.currentTimeMillis(),
            ),
        ).await()
        return doc.id
    }

    suspend fun deleteExpense(expenseId: String) {
        expenses().document(expenseId).delete().await()
    }

    // ─────────────────────────────────────────────────────────────────────
    // One-shot reads
    // ─────────────────────────────────────────────────────────────────────

    suspend fun getMedicine(medicineId: String): Medicine? =
        medicines().document(medicineId).get(Source.CACHE).await().toMedicine()

    suspend fun getProfile(): PharmacyProfile? {
        val snap = pharmacyDoc().get(Source.CACHE).await()
        return if (snap.exists()) {
            PharmacyProfile(
                name = snap.getString("name").orEmpty(),
                currency = snap.getString("currency") ?: "BDT",
                address = snap.getString("address").orEmpty(),
                phone = snap.getString("phone").orEmpty(),
            )
        } else null
    }

    /**
     * Initialises the pharmacy document on first sign-in. Server-first read:
     * a second device must not mistake a not-yet-downloaded cache for an
     * absent profile and overwrite the real one.
     */
    suspend fun ensurePharmacyProfile(shopName: String) {
        val snap = pharmacyDoc().get().await()
        if (!snap.exists()) {
            pharmacyDoc().set(
                mapOf(
                    "name" to shopName,
                    "currency" to "BDT",
                    "address" to "",
                    "phone" to "",
                    "createdAt" to System.currentTimeMillis(),
                    "uid" to uid,
                ),
            ).await()
        }
    }

    /**
     * Deletes every document this pharmacy owns, then signs out. This is the
     * account-data deletion path a shopkeeper can actually verify: no ticket,
     * no waiting, no server-side queue.
     */
    suspend fun deleteAllData() {
        val collections = listOf(
            medicines(), batches(), sales(), dues(), purchases(), expenses(), customers(),
        )
        for (collection in collections) {
            var remaining = true
            while (remaining) {
                val docs = collection.limit(400).get().await().documents
                if (docs.isEmpty()) {
                    remaining = false
                } else {
                    val batch = db.batch()
                    docs.forEach { batch.delete(it.reference) }
                    batch.commit().await()
                }
            }
        }
        pharmacyDoc().delete().await()
    }

    // ─────────────────────────────────────────────────────────────────────
    // Mapper helpers
    // ─────────────────────────────────────────────────────────────────────

    private fun com.google.firebase.firestore.DocumentSnapshot.toMedicine(): Medicine? {
        val id = getString("id") ?: this.id
        val brandName = getString("brandName") ?: return null
        return Medicine(
            id = id,
            brandName = brandName,
            genericName = getString("genericName").orEmpty(),
            strength = getString("strength").orEmpty(),
            dosageForm = getString("dosageForm").orEmpty(),
            barcode = getString("barcode").orEmpty(),
            defaultSellingPrice = Money.fromPaisa(getLong("defaultSellingPricePaisa") ?: 0L),
            lowStockThreshold = getLong("lowStockThreshold")?.toInt() ?: 10,
            availableQuantity = getLong("availableQuantity")?.toInt() ?: 0,
            isActive = getBoolean("isActive") ?: true,
        )
    }

    private fun com.google.firebase.firestore.DocumentSnapshot.toBatch(): Batch? {
        val id = getString("id") ?: this.id
        val medicineId = getString("medicineId") ?: return null
        val expiryStr = getString("expiryDate") ?: return null
        val expiryDate = runCatching { LocalDate.parse(expiryStr) }.getOrNull() ?: return null
        return Batch(
            id = id,
            medicineId = medicineId,
            medicineName = getString("medicineName").orEmpty(),
            medicineStrength = getString("medicineStrength").orEmpty(),
            batchNumber = getString("batchNumber").orEmpty(),
            expiryDate = expiryDate,
            unitCost = Money.fromPaisa(getLong("unitCostPaisa") ?: 0L),
            sellingPrice = Money.fromPaisa(getLong("sellingPricePaisa") ?: 0L),
            quantityReceived = getLong("quantityReceived")?.toInt() ?: 0,
            quantityAvailable = getLong("quantityAvailable")?.toInt() ?: 0,
        )
    }

    @Suppress("UNCHECKED_CAST")
    private fun com.google.firebase.firestore.DocumentSnapshot.toSale(): Sale? {
        val id = getString("id") ?: this.id
        val invoiceNumber = getString("invoiceNumber") ?: return null
        val soldAt = getLong("soldAt") ?: return null
        val totalPaisa = getLong("totalPaisa") ?: 0L
        val paymentMethodStr = getString("paymentMethod") ?: "CASH"
        val paymentMethod = runCatching { PaymentMethod.valueOf(paymentMethodStr) }
            .getOrDefault(PaymentMethod.CASH)

        val rawLines = (get("lines") as? List<Map<String, Any>>).orEmpty()
        val lines = rawLines.mapNotNull { lineMap ->
            val medicineId = lineMap["medicineId"] as? String ?: return@mapNotNull null
            val medicineName = lineMap["medicineName"] as? String ?: ""
            val quantity = (lineMap["quantity"] as? Long)?.toInt() ?: return@mapNotNull null
            val unitPricePaisa = lineMap["unitPricePaisa"] as? Long ?: 0L

            val rawAllocations = (lineMap["allocations"] as? List<Map<String, Any>>).orEmpty()
            val allocations = rawAllocations.mapNotNull { a ->
                val batchId = a["batchId"] as? String ?: return@mapNotNull null
                val batchNumber = a["batchNumber"] as? String ?: ""
                val expiryStr = a["expiryDate"] as? String ?: return@mapNotNull null
                val expiryDate = runCatching { LocalDate.parse(expiryStr) }.getOrNull()
                    ?: return@mapNotNull null
                val allocQty = (a["quantity"] as? Long)?.toInt() ?: return@mapNotNull null
                val unitCostPaisa = a["unitCostPaisa"] as? Long ?: 0L
                BatchAllocation(
                    batchId = batchId,
                    batchNumber = batchNumber,
                    expiryDate = expiryDate,
                    quantity = allocQty,
                    unitCost = Money.fromPaisa(unitCostPaisa),
                )
            }

            CartLine(
                medicineId = medicineId,
                medicineName = medicineName,
                unitPrice = Money.fromPaisa(unitPricePaisa),
                quantity = quantity,
                allocations = allocations,
            )
        }

        return Sale(
            id = id,
            invoiceNumber = invoiceNumber,
            soldAt = Instant.ofEpochMilli(soldAt),
            total = Money.fromPaisa(totalPaisa),
            paymentMethod = paymentMethod,
            lines = lines,
            note = getString("note").orEmpty(),
        )
    }
}

// ─────────────────────────────────────────────────────────────────────────
// Value objects for write operations
// ─────────────────────────────────────────────────────────────────────────

data class ReceiveStockItem(
    val medicineId: String,
    val medicineName: String,
    val medicineStrength: String = "",
    val batchNumber: String,
    val expiryDate: LocalDate,
    val quantity: Int,
    val unitCostPaisa: Long,
    val sellingPricePaisa: Long,
    val supplier: String = "",
)

data class FirestoreDueEntry(
    val id: String,
    val customer: String,
    val amountPaisa: Long,
    val createdAt: Long,
    val invoiceNumber: String = "",
    val note: String = "",
)

/** One customer in the baki phone book. */
data class FirestoreCustomer(
    val id: String,
    val name: String,
    val phone: String,
    val note: String = "",
)

data class FirestoreExpense(
    val id: String,
    val category: String,
    val amountPaisa: Long,
    val note: String,
    val createdAt: Long,
)

data class FirestorePurchase(
    val id: String,
    val supplier: String,
    val receivedAt: Long,
    val items: List<FirestorePurchaseItem>,
) {
    val totalCostPaisa: Long get() = items.sumOf { it.unitCostPaisa * it.quantity }
}

data class FirestorePurchaseItem(
    val medicineId: String,
    val medicineName: String,
    val batchNumber: String,
    val expiryDate: String,
    val quantity: Int,
    val unitCostPaisa: Long,
    val sellingPricePaisa: Long,
)
