package bd.rakho.pharmacy.data.repo

import bd.rakho.pharmacy.core.model.Batch
import bd.rakho.pharmacy.core.model.DashboardStats
import bd.rakho.pharmacy.core.model.ExpiryAlert
import bd.rakho.pharmacy.core.model.LowStockAlert
import bd.rakho.pharmacy.core.model.Medicine
import bd.rakho.pharmacy.core.model.PendingOperationType
import bd.rakho.pharmacy.core.model.PharmacyProfile
import bd.rakho.pharmacy.core.money.Money
import bd.rakho.pharmacy.core.time.DhakaTime
import bd.rakho.pharmacy.core.time.ExpiryRules
import bd.rakho.pharmacy.data.local.LocalCache
import bd.rakho.pharmacy.data.remote.RakhoApi
import bd.rakho.pharmacy.data.remote.apiCall
import bd.rakho.pharmacy.data.remote.dto.BatchDto
import bd.rakho.pharmacy.data.remote.dto.CreateMedicineRequest
import bd.rakho.pharmacy.data.remote.dto.MedicineDto
import bd.rakho.pharmacy.data.remote.dto.PharmacyDto
import bd.rakho.pharmacy.data.remote.dto.PurchaseItemRequest
import bd.rakho.pharmacy.data.remote.dto.ReceivePurchaseRequest
import bd.rakho.pharmacy.data.remote.dto.WastageRequest
import bd.rakho.pharmacy.data.remote.toDomain
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json
import java.time.LocalDate

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

class InventoryRepository(
    private val api: RakhoApi,
    private val cache: LocalCache,
    private val json: Json,
) {

    private val medicineListSerializer = ListSerializer(MedicineDto.serializer())
    private val batchListSerializer = ListSerializer(BatchDto.serializer())

    // ---- Reads (cache-first, re-emitted whenever the cache changes) -------

    fun observeMedicines(): Flow<List<Medicine>> = cache.revision.map {
        readMedicines()
    }

    fun observeBatches(activeOnly: Boolean = false): Flow<List<Batch>> = cache.revision.map {
        val all = readBatches()
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

    suspend fun refreshProfile(): Result<PharmacyProfile> = apiCall(json) {
        val profile = api.pharmacy()
        cache.write(LocalCache.KEY_PROFILE, profile) { json.encodeToString(it) }
        PharmacyProfile(profile.name, profile.currency, profile.address, profile.phone)
    }

    suspend fun updateProfile(name: String, phone: String, address: String): Result<Unit> =
        apiCall(json) {
            val profile = api.patchPharmacy(
                bd.rakho.pharmacy.data.remote.dto.PharmacyPatchRequest(
                    name = name.ifBlank { null },
                    phone = phone,
                    address = address,
                ),
            )
            cache.write(LocalCache.KEY_PROFILE, profile) { json.encodeToString(it) }
        }

    // ---- Writes (online when possible, queued when offline) --------------

    suspend fun receiveStock(items: List<PurchaseItemRequest>): Result<WriteOutcome> {
        val request = ReceivePurchaseRequest(items)
        val result = apiCall(json) { api.receivePurchase(request) }
        return result.fold(
            onSuccess = {
                refresh()
                Result.success(WriteOutcome.Synced)
            },
            onFailure = { error ->
                if (error is bd.rakho.pharmacy.core.result.AppError.Network) {
                    cache.enqueue(PendingOperationType.PURCHASE, json.encodeToString(request))
                    Result.success(WriteOutcome.Queued)
                } else {
                    Result.failure(error)
                }
            },
        )
    }

    suspend fun writeOffBatch(batchId: String, note: String): Result<WriteOutcome> {
        val request = WastageRequest(note)
        val result = apiCall(json) { api.writeOffBatch(batchId, request) }
        return result.fold(
            onSuccess = {
                refresh()
                Result.success(WriteOutcome.Synced)
            },
            onFailure = { error ->
                if (error is bd.rakho.pharmacy.core.result.AppError.Network) {
                    cache.enqueue(
                        PendingOperationType.WASTAGE,
                        json.encodeToString(WastagePayload(batchId, note)),
                    )
                    zeroOutCachedBatch(batchId)
                    Result.success(WriteOutcome.Queued)
                } else {
                    Result.failure(error)
                }
            },
        )
    }

    suspend fun addMedicine(request: CreateMedicineRequest): Result<WriteOutcome> {
        val result = apiCall(json) { api.createMedicine(request) }
        return result.fold(
            onSuccess = {
                refresh()
                Result.success(WriteOutcome.Synced)
            },
            onFailure = { error ->
                if (error is bd.rakho.pharmacy.core.result.AppError.Network) {
                    cache.enqueue(PendingOperationType.MEDICINE, json.encodeToString(request))
                    Result.success(WriteOutcome.Queued)
                } else {
                    Result.failure(error)
                }
            },
        )
    }

    // ---- Cache helpers ----------------------------------------------------

    private suspend fun readMedicines(): List<Medicine> =
        cache.read(LocalCache.KEY_MEDICINES) { json.decodeFromString(medicineListSerializer, it) }
            ?.map { it.toDomain() }
            .orEmpty()

    private suspend fun readBatches(): List<Batch> =
        cache.read(LocalCache.KEY_BATCHES) { json.decodeFromString(batchListSerializer, it) }
            ?.mapNotNull { it.toDomain() }
            .orEmpty()

    private suspend fun readDashboard(): DashboardStats {
        val cached = cache.read(LocalCache.KEY_DASHBOARD) {
            json.decodeFromString(bd.rakho.pharmacy.data.remote.dto.DashboardDto.serializer(), it)
        }
        val today = DhakaTime.today()
        val alerts = computeAlerts(ExpiryRules.EXPIRING_SOON_DAYS, today)
        val medicines = readMedicines()
        val stockValue = readBatches().sumOf { it.quantityAvailable }.let { _ ->
            readBatches().fold(Money.ZERO) { acc, batch -> acc + batch.stockValue }
        }
        return DashboardStats(
            todaySales = Money.parse(cached?.sales?.todayAmount),
            todayProfit = estimateTodayProfit(),
            todaySaleCount = cached?.sales?.todayCount ?: 0,
            stockValue = stockValue,
            medicineCount = medicines.size,
            expiredCount = alerts.expired.size,
            expiringSoonCount = alerts.expiringSoon.size,
            lowStockCount = alerts.lowStock.size,
        )
    }

    /** Profit requires sale prices; until the reports API lands we approximate. */
    private suspend fun estimateTodayProfit(): Money = Money.ZERO

    private suspend fun computeAlerts(horizonDays: Long, today: LocalDate): AlertSnapshot {
        val batches = readBatches().filter { it.quantityAvailable > 0 }
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
        val lowStock = readMedicines()
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

    private suspend fun zeroOutCachedBatch(batchId: String) {
        val batches = readBatches()
        val updated = batches.map { if (it.id == batchId) it.copy(quantityAvailable = 0) else it }
        cache.write(LocalCache.KEY_BATCHES, updated, ::encodeBatchesFromDomain)
    }

    /** Adjusts cached stock after an offline sale so the counter stays accurate. */
    suspend fun applyOfflineAllocations(deductions: Map<String, Int>) {
        if (deductions.isEmpty()) return
        val batches = readBatches()
        val updated = batches.map { batch ->
            val take = deductions[batch.id] ?: 0
            if (take > 0) batch.copy(quantityAvailable = (batch.quantityAvailable - take).coerceAtLeast(0))
            else batch
        }
        cache.write(LocalCache.KEY_BATCHES, updated, ::encodeBatchesFromDomain)
    }

    private fun encodeMedicines(list: List<bd.rakho.pharmacy.data.remote.dto.MedicineDto>): String =
        json.encodeToString(medicineListSerializer, list)

    private fun encodeBatches(list: List<bd.rakho.pharmacy.data.remote.dto.BatchDto>): String =
        json.encodeToString(batchListSerializer, list)

    private fun encodeBatchesFromDomain(list: List<Batch>): String =
        json.encodeToString(
            batchListSerializer,
            list.map { batch ->
                bd.rakho.pharmacy.data.remote.dto.BatchDto(
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
            },
        )
}

@kotlinx.serialization.Serializable
data class WastagePayload(val batchId: String, val note: String)
