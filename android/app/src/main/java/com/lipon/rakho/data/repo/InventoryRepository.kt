package com.lipon.rakho.data.repo

import com.lipon.rakho.core.model.Batch
import com.lipon.rakho.core.model.DashboardStats
import com.lipon.rakho.core.model.ExpiryAlert
import com.lipon.rakho.core.model.LowStockAlert
import com.lipon.rakho.core.model.Medicine
import com.lipon.rakho.core.model.PendingOperationType
import com.lipon.rakho.core.model.PharmacyProfile
import com.lipon.rakho.core.model.Sale
import com.lipon.rakho.core.money.Money
import com.lipon.rakho.core.result.AppError
import com.lipon.rakho.core.time.DhakaTime
import com.lipon.rakho.core.time.ExpiryRules
import com.lipon.rakho.data.local.LocalCache
import com.lipon.rakho.data.local.LocalMedicineDto
import com.lipon.rakho.data.remote.RakhoApi
import com.lipon.rakho.data.remote.apiCall
import com.lipon.rakho.data.remote.dto.BatchDto
import com.lipon.rakho.data.remote.dto.CreateMedicineRequest
import com.lipon.rakho.data.remote.dto.CreateSaleRequest
import com.lipon.rakho.data.remote.dto.DashboardDto
import com.lipon.rakho.data.remote.dto.MedicineDto
import com.lipon.rakho.data.remote.dto.PharmacyDto
import com.lipon.rakho.data.remote.dto.PharmacyPatchRequest
import com.lipon.rakho.data.remote.dto.PurchaseItemRequest
import com.lipon.rakho.data.remote.dto.ReceivePurchaseRequest
import com.lipon.rakho.data.remote.dto.SaleDto
import com.lipon.rakho.data.remote.dto.WastageRequest
import com.lipon.rakho.data.remote.toDomain
import com.lipon.rakho.data.session.SessionStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json
import java.time.LocalDate
import java.util.UUID

/** What the expiry radar shows. */
data class AlertSnapshot(
    val expired: List<ExpiryAlert> = emptyList(),
    val expiringSoon: List<ExpiryAlert> = emptyList(),
    val lowStock: List<LowStockAlert> = emptyList(),
)

/** Result of a write that may have been queued for later sync. */
sealed interface WriteOutcome {
    data object Synced : WriteOutcome
    data object Queued : WriteOutcome
}

/**
 * Inventory data for the pharmacy.
 *
 * The app is deliberately usable without a server: before a pharmacy key is
 * entered, medicines are kept in a local document ([LocalCache.KEY_LOCAL_MEDICINES])
 * and received stock as local batches ([LocalCache.KEY_LOCAL_BATCHES]), so a
 * shop can run entirely offline from the first launch. When a key is later
 * connected, [promoteLocalData] creates the medicines on the server, uploads
 * the batches under the real medicine ids, and rewrites any queued sale to
 * point at them — nothing the pharmacy recorded offline is lost or duplicated.
 */
class InventoryRepository(
    private val api: RakhoApi,
    private val cache: LocalCache,
    private val sessionStore: SessionStore,
    private val json: Json,
) {

    private val medicineListSerializer = ListSerializer(MedicineDto.serializer())
    private val batchListSerializer = ListSerializer(BatchDto.serializer())
    private val localMedicineSerializer = ListSerializer(LocalMedicineDto.serializer())

    // ---- Reads (cache-first, re-emitted whenever the cache changes) -------

    /** Server medicines plus any medicines created in local-only mode. */
    fun observeMedicines(): Flow<List<Medicine>> = cache.revision.map {
        allMedicines()
    }

    fun observeBatches(activeOnly: Boolean = false): Flow<List<Batch>> = cache.revision.map {
        val all = readServerBatches() + readLocalBatches()
        if (activeOnly) all.filter { it.quantityAvailable > 0 } else all
    }

    /** Expiry and low-stock radar, derived locally so it works offline. */
    fun observeAlerts(horizonDays: Long = ExpiryRules.EXPIRING_SOON_DAYS): Flow<AlertSnapshot> =
        cache.revision.map { computeAlerts(horizonDays, DhakaTime.today()) }

    fun observeDashboard(): Flow<DashboardStats> = cache.revision.map {
        readDashboard()
    }

    fun observeProfile(): Flow<PharmacyProfile?> = cache.revision.map {
        cache.read(LocalCache.KEY_PROFILE) { raw ->
            val dto = json.decodeFromString(PharmacyDto.serializer(), raw)
            PharmacyProfile(dto.name, dto.currency, dto.address, dto.phone)
        }
    }

    /** One-shot list for code that needs names without subscribing to a flow. */
    suspend fun medicinesSnapshot(): List<Medicine> = allMedicines()

    // ---- Remote refresh ---------------------------------------------------

    suspend fun refresh(): Result<Unit> = apiCall(json) {
        val medicines = api.medicines().results
        val batches = api.batches(active = "true").results
        val alerts = api.alerts(days = ExpiryRules.EXPIRING_SOON_DAYS.toInt())
        val dashboard = api.dashboard()
        val profile = api.pharmacy()

        cache.write(LocalCache.KEY_MEDICINES, medicines, ::encodeMedicines)
        cache.write(LocalCache.KEY_BATCHES, batches, ::encodeBatches)
        cache.write(LocalCache.KEY_ALERTS, alerts) { json.encodeToString(it) }
        cache.write(LocalCache.KEY_DASHBOARD, dashboard) { json.encodeToString(it) }
        cache.write(LocalCache.KEY_PROFILE, profile) { json.encodeToString(it) }
    }

    suspend fun refreshProfile(): Result<PharmacyProfile> {
        if (!sessionStore.current().isConnected) {
            return Result.success(PharmacyProfile(name = sessionStore.current().shopName))
        }
        return apiCall(json) {
            val profile = api.pharmacy()
            cache.write(LocalCache.KEY_PROFILE, profile) { json.encodeToString(it) }
            PharmacyProfile(profile.name, profile.currency, profile.address, profile.phone)
        }
    }

    suspend fun updateProfile(name: String, phone: String, address: String): Result<Unit> {
        if (!sessionStore.current().isConnected) {
            // Local-only mode: the profile lives on this device.
            cache.write(
                LocalCache.KEY_PROFILE,
                PharmacyDto(name = name, phone = phone, address = address),
                ::encodeProfile,
            )
            sessionStore.updateShopName(name)
            return Result.success(Unit)
        }
        return apiCall(json) {
            val profile = api.patchPharmacy(
                PharmacyPatchRequest(
                    name = name.ifBlank { null },
                    phone = phone,
                    address = address,
                ),
            )
            cache.write(LocalCache.KEY_PROFILE, profile) { json.encodeToString(it) }
        }
    }

    // ---- Writes (online when possible, local or queued otherwise) ---------

    suspend fun receiveStock(items: List<PurchaseItemRequest>): Result<WriteOutcome> {
        if (!sessionStore.current().isConnected) {
            appendLocalBatches(items)
            return Result.success(WriteOutcome.Queued)
        }
        val request = ReceivePurchaseRequest(items)
        val result = apiCall(json) { api.receivePurchase(request) }
        return result.fold(
            onSuccess = {
                refresh()
                Result.success(WriteOutcome.Synced)
            },
            onFailure = { error ->
                if (error is AppError.Network) {
                    cache.enqueue(PendingOperationType.PURCHASE, json.encodeToString(request))
                    Result.success(WriteOutcome.Queued)
                } else {
                    Result.failure(error)
                }
            },
        )
    }

    suspend fun writeOffBatch(batchId: String, note: String): Result<WriteOutcome> {
        if (!sessionStore.current().isConnected) {
            zeroOutBatchEverywhere(batchId)
            return Result.success(WriteOutcome.Queued)
        }
        val request = WastageRequest(note)
        val result = apiCall(json) { api.writeOffBatch(batchId, request) }
        return result.fold(
            onSuccess = {
                refresh()
                Result.success(WriteOutcome.Synced)
            },
            onFailure = { error ->
                if (error is AppError.Network) {
                    cache.enqueue(
                        PendingOperationType.WASTAGE,
                        json.encodeToString(WastagePayload(batchId, note)),
                    )
                    zeroOutBatchEverywhere(batchId)
                    Result.success(WriteOutcome.Queued)
                } else {
                    Result.failure(error)
                }
            },
        )
    }

    suspend fun addMedicine(request: CreateMedicineRequest): Result<WriteOutcome> {
        if (!sessionStore.current().isConnected) {
            val local = readLocalMedicineDtos()
            cache.write(
                LocalCache.KEY_LOCAL_MEDICINES,
                local + LocalMedicineDto(
                    id = UUID.randomUUID().toString(),
                    brandName = request.brandName,
                    genericName = request.genericName,
                    strength = request.strength,
                    dosageForm = request.dosageForm,
                    barcode = "",
                    price = request.defaultSellingPrice,
                    lowStockThreshold = request.lowStockThreshold,
                ),
                ::encodeLocalMedicines,
            )
            return Result.success(WriteOutcome.Queued)
        }
        val result = apiCall(json) { api.createMedicine(request) }
        return result.fold(
            onSuccess = {
                refresh()
                Result.success(WriteOutcome.Synced)
            },
            onFailure = { error ->
                if (error is AppError.Network) {
                    cache.enqueue(PendingOperationType.MEDICINE, json.encodeToString(request))
                    Result.success(WriteOutcome.Queued)
                } else {
                    Result.failure(error)
                }
            },
        )
    }

    // ---- Local-only mode ---------------------------------------------------

    /**
     * Uploads everything recorded before the pharmacy was connected.
     *
     * Safe to call repeatedly: existing server medicines are matched by brand
     * and strength before creating new ones, the local medicine document is
     * cleared as soon as creation succeeds, and queued operations are remapped
     * to the real server ids so replay continues to work.
     */
    suspend fun promoteLocalData(): Boolean {
        if (!sessionStore.current().isConnected) return false
        val localMedicines = readLocalMedicineDtos()
        val localBatches = readLocalBatchDtos()
        if (localMedicines.isEmpty() && localBatches.isEmpty()) return false

        val medicineIdMap = mutableMapOf<String, String>()
        if (localMedicines.isNotEmpty()) {
            val existing = api.medicines().results
            for (local in localMedicines) {
                val match = existing.firstOrNull {
                    it.brandName.equals(local.brandName, ignoreCase = true) &&
                        it.strength.equals(local.strength, ignoreCase = true)
                }
                medicineIdMap[local.id] = match?.id ?: api.createMedicine(
                    CreateMedicineRequest(
                        brandName = local.brandName,
                        genericName = local.genericName,
                        strength = local.strength,
                        dosageForm = local.dosageForm,
                        defaultSellingPrice = local.price,
                        lowStockThreshold = local.lowStockThreshold,
                        catalogMedicine = null,
                    ),
                ).id
            }
            // Clear before uploading stock: a retried promote then cannot
            // create the medicines twice.
            cache.write(LocalCache.KEY_LOCAL_MEDICINES, emptyList(), ::encodeLocalMedicines)
        }

        val batchIdMap = mutableMapOf<String, String>()
        if (localBatches.isNotEmpty()) {
            // Server receive ADDS to existing quantities and local sales have
            // already deducted stock, so upload what is actually left on the
            // shelf, keeping each request paired with its local batch id.
            val uploadable = localBatches.mapNotNull { dto ->
                medicineIdMap[dto.medicine]?.let { medicineId ->
                    dto to PurchaseItemRequest(
                        medicine = medicineId,
                        batchNumber = dto.batchNumber,
                        expiryDate = dto.expiryDate,
                        quantity = dto.quantityAvailable,
                        unitCost = dto.unitCost,
                        sellingPrice = dto.sellingPrice,
                        supplierName = dto.supplierName,
                    )
                }
            }
            if (uploadable.isNotEmpty()) {
                // The server upserts batches per (medicine, batch number), so
                // re-received stock is merged rather than duplicated.
                val response = api.receivePurchase(
                    ReceivePurchaseRequest(uploadable.map { it.second }),
                )
                response.batches.forEachIndexed { index, batch ->
                    if (index < uploadable.size) batchIdMap[uploadable[index].first.id] = batch.id
                }
            }
            cache.write(LocalCache.KEY_LOCAL_BATCHES, emptyList(), ::encodeBatches)
        }

        remapPendingOperations(medicineIdMap, batchIdMap)
        return true
    }

    /** Points queued offline operations at the real server ids. */
    private suspend fun remapPendingOperations(
        medicineIds: Map<String, String>,
        batchIds: Map<String, String>,
    ) {
        if (medicineIds.isEmpty() && batchIds.isEmpty()) return
        for (op in cache.pending()) {
            val newPayload: String? = when (op.type) {
                PendingOperationType.SALE -> runCatching {
                    val request = json.decodeFromString(CreateSaleRequest.serializer(), op.payload)
                    json.encodeToString(
                        CreateSaleRequest.serializer(),
                        request.copy(
                            lines = request.lines.map {
                                it.copy(medicine = medicineIds[it.medicine] ?: it.medicine)
                            },
                        ),
                    )
                }.getOrNull()
                PendingOperationType.PURCHASE -> runCatching {
                    val request = json.decodeFromString(ReceivePurchaseRequest.serializer(), op.payload)
                    json.encodeToString(
                        ReceivePurchaseRequest.serializer(),
                        request.copy(
                            items = request.items.map {
                                it.copy(medicine = medicineIds[it.medicine] ?: it.medicine)
                            },
                        ),
                    )
                }.getOrNull()
                PendingOperationType.WASTAGE -> runCatching {
                    val payload = json.decodeFromString(WastagePayload.serializer(), op.payload)
                    json.encodeToString(
                        WastagePayload.serializer(),
                        payload.copy(batchId = batchIds[payload.batchId] ?: payload.batchId),
                    )
                }.getOrNull()
                PendingOperationType.MEDICINE -> null
            }
            if (newPayload != null) cache.updatePayload(op.id, newPayload)
        }
    }

    // ---- Cache helpers ----------------------------------------------------

    private suspend fun readServerMedicines(): List<Medicine> =
        cache.read(LocalCache.KEY_MEDICINES) { json.decodeFromString(medicineListSerializer, it) }
            ?.map { it.toDomain() }
            .orEmpty()

    private suspend fun readLocalMedicineDtos(): List<LocalMedicineDto> =
        cache.read(LocalCache.KEY_LOCAL_MEDICINES) {
            json.decodeFromString(localMedicineSerializer, it)
        }.orEmpty()

    private fun LocalMedicineDto.toMedicine() = Medicine(
        id = id,
        brandName = brandName,
        genericName = genericName,
        strength = strength,
        dosageForm = dosageForm,
        barcode = barcode,
        defaultSellingPrice = Money.parse(price),
        lowStockThreshold = lowStockThreshold,
        isActive = isActive,
        localId = id,
    )

    private suspend fun allMedicines(): List<Medicine> =
        readServerMedicines() + readLocalMedicineDtos().map { it.toMedicine() }

    private suspend fun readServerBatches(): List<Batch> =
        cache.read(LocalCache.KEY_BATCHES) { json.decodeFromString(batchListSerializer, it) }
            ?.mapNotNull { it.toDomain() }
            .orEmpty()

    private suspend fun readLocalBatches(): List<Batch> =
        cache.read(LocalCache.KEY_LOCAL_BATCHES) { json.decodeFromString(batchListSerializer, it) }
            ?.mapNotNull { it.toDomain() }
            .orEmpty()

    private suspend fun readLocalBatchDtos(): List<BatchDto> =
        cache.read(LocalCache.KEY_LOCAL_BATCHES) { json.decodeFromString(batchListSerializer, it) }
            .orEmpty()

    private suspend fun appendLocalBatches(items: List<PurchaseItemRequest>) {
        val medicines = allMedicines().associateBy { it.id }
        val newBatches = items.map { item ->
            val medicine = medicines[item.medicine]
            BatchDto(
                id = UUID.randomUUID().toString(),
                medicine = item.medicine,
                medicineName = medicine?.displayName.orEmpty(),
                medicineStrength = medicine?.strength.orEmpty(),
                batchNumber = item.batchNumber,
                expiryDate = item.expiryDate,
                unitCost = item.unitCost,
                sellingPrice = item.sellingPrice,
                quantityReceived = item.quantity,
                quantityAvailable = item.quantity,
                supplierName = item.supplierName,
            )
        }
        cache.write(
            LocalCache.KEY_LOCAL_BATCHES,
            readLocalBatchDtos() + newBatches,
            ::encodeBatches,
        )
    }

    private suspend fun readDashboard(): DashboardStats {
        val cached = cache.read(LocalCache.KEY_DASHBOARD) {
            json.decodeFromString(DashboardDto.serializer(), it)
        }
        val today = DhakaTime.today()
        val alerts = computeAlerts(ExpiryRules.EXPIRING_SOON_DAYS, today)
        val medicines = allMedicines()
        val batches = readServerBatches() + readLocalBatches()
        val stockValue = batches.fold(Money.ZERO) { acc, batch -> acc + batch.stockValue }
        // Money on the shelf that will be lost if nothing sells in time.
        val expiringValue = (alerts.expired + alerts.expiringSoon)
            .map { it.batch }
            .fold(Money.ZERO) { acc, batch -> acc + batch.stockValue }
        return DashboardStats(
            todaySales = Money.parse(cached?.sales?.todayAmount),
            todayProfit = computeTodayProfit(today),
            todaySaleCount = cached?.sales?.todayCount ?: 0,
            stockValue = stockValue,
            medicineCount = medicines.size,
            expiredCount = alerts.expired.size,
            expiringSoonCount = alerts.expiringSoon.size,
            lowStockCount = alerts.lowStock.size,
            expiringValue = expiringValue,
        )
    }

    /**
     * Real gross profit for today: for every line sold today, the actual
     * FEFO allocation records which batch (and cost) was consumed.
     * Selling price comes from the line, cost from the allocation's batch
     * cost captured at sale time. Falls back to zero when a sale predates
     * allocation data (legacy rows) rather than inventing a number.
     */
    private suspend fun computeTodayProfit(today: LocalDate): Money {
        val costByBatchId = (readServerBatches() + readLocalBatches())
            .associate { it.id to it.unitCost }
        val startOfDay = today.atStartOfDay(DhakaTime.ZONE).toInstant()
        val sales: List<Sale> = readServerSales() + readLocalSales()
        return sales
            .filter { it.soldAt >= startOfDay }
            .flatMap { sale -> sale.lines.asSequence() }
            .map { line ->
                val revenue = line.unitPrice * line.quantity
                val cost = line.allocations
                    .fold(Money.ZERO) { acc, allocation ->
                        // Cost captured at sale time is authoritative; the
                        // live batch list is only a fallback for legacy rows.
                        val unitCost = if (allocation.unitCost.isZero) {
                            costByBatchId[allocation.batchId] ?: Money.ZERO
                        } else {
                            allocation.unitCost
                        }
                        acc + unitCost * allocation.quantity
                    }
                revenue - cost
            }
            .fold(Money.ZERO) { acc, profit -> acc + profit }
    }

    private suspend fun readServerSales(): List<Sale> {
        val serializer = ListSerializer(SaleDto.serializer())
        return cache.read(LocalCache.KEY_SALES) { json.decodeFromString(serializer, it) }
            .orEmpty()
            .mapNotNull { it.toDomain() }
    }

    private suspend fun readLocalSales(): List<Sale> {
        val serializer = ListSerializer(SaleDto.serializer())
        return cache.read(LocalCache.KEY_LOCAL_SALES) { json.decodeFromString(serializer, it) }
            .orEmpty()
            .mapNotNull { it.toDomain() }
    }

    private suspend fun computeAlerts(horizonDays: Long, today: LocalDate): AlertSnapshot {
        val batches = (readServerBatches() + readLocalBatches()).filter { it.quantityAvailable > 0 }
        val expired = batches
            .filter { ExpiryRules.daysUntil(it.expiryDate, today) < 0 }
            .sortedBy { it.expiryDate }
            .map { ExpiryAlert(it, ExpiryRules.daysUntil(it.expiryDate, today)) }
        val expiring = batches
            .filter {
                val days = ExpiryRules.daysUntil(it.expiryDate, today)
                days in 0..horizonDays
            }
            .sortedBy { it.expiryDate }
            .map { ExpiryAlert(it, ExpiryRules.daysUntil(it.expiryDate, today)) }

        val batchesByMedicine = batches.groupBy { it.medicineId }
        val lowStock = allMedicines()
            .filter { it.isActive }
            .mapNotNull { medicine ->
                val available = batchesByMedicine[medicine.id].orEmpty().sumOf { it.quantityAvailable }
                if (available <= medicine.lowStockThreshold) {
                    LowStockAlert(
                        medicineId = medicine.id,
                        name = medicine.displayName,
                        available = available,
                        threshold = medicine.lowStockThreshold,
                    )
                } else {
                    null
                }
            }
        return AlertSnapshot(expired = expired, expiringSoon = expiring, lowStock = lowStock)
    }

    /** Zeroes a batch whether it lives in the server cache or the local document. */
    private suspend fun zeroOutBatchEverywhere(batchId: String) {
        val local = readLocalBatches()
        if (local.any { it.id == batchId }) {
            cache.write(
                LocalCache.KEY_LOCAL_BATCHES,
                local.map { if (it.id == batchId) it.copy(quantityAvailable = 0) else it },
                ::encodeBatchesFromDomain,
            )
        }
        val server = readServerBatches()
        if (server.any { it.id == batchId }) {
            cache.write(
                LocalCache.KEY_BATCHES,
                server.map { if (it.id == batchId) it.copy(quantityAvailable = 0) else it },
                ::encodeBatchesFromDomain,
            )
        }
    }

    /** Adjusts cached stock after an offline sale so the counter stays accurate. */
    suspend fun applyOfflineAllocations(deductions: Map<String, Int>) {
        if (deductions.isEmpty()) return
        fun adjust(list: List<Batch>): List<Batch> = list.map { batch ->
            val take = deductions[batch.id] ?: 0
            if (take > 0) {
                batch.copy(quantityAvailable = (batch.quantityAvailable - take).coerceAtLeast(0))
            } else {
                batch
            }
        }
        val local = readLocalBatches()
        if (local.any { deductions.containsKey(it.id) }) {
            cache.write(LocalCache.KEY_LOCAL_BATCHES, adjust(local), ::encodeBatchesFromDomain)
        }
        val server = readServerBatches()
        if (server.any { deductions.containsKey(it.id) }) {
            cache.write(LocalCache.KEY_BATCHES, adjust(server), ::encodeBatchesFromDomain)
        }
    }

    private fun batchToDto(batch: Batch): BatchDto = BatchDto(
        id = batch.id,
        medicine = batch.medicineId,
        medicineName = batch.medicineName,
        medicineStrength = batch.medicineStrength,
        batchNumber = batch.batchNumber,
        expiryDate = batch.expiryDate.toString(),
        unitCost = batch.unitCost.toBigDecimal().toPlainString(),
        sellingPrice = batch.sellingPrice.toBigDecimal().toPlainString(),
        quantityReceived = batch.quantityReceived,
        quantityAvailable = batch.quantityAvailable,
    )

    private fun encodeMedicines(list: List<MedicineDto>): String =
        json.encodeToString(medicineListSerializer, list)

    private fun encodeLocalMedicines(list: List<LocalMedicineDto>): String =
        json.encodeToString(localMedicineSerializer, list)

    private fun encodeBatches(list: List<BatchDto>): String =
        json.encodeToString(batchListSerializer, list)

    private fun encodeBatchesFromDomain(list: List<Batch>): String =
        json.encodeToString(batchListSerializer, list.map(::batchToDto))

    private fun encodeProfile(profile: PharmacyDto): String =
        json.encodeToString(PharmacyDto.serializer(), profile)
}

@kotlinx.serialization.Serializable
data class WastagePayload(val batchId: String, val note: String)
