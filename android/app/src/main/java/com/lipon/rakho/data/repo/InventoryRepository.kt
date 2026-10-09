package com.lipon.rakho.data.repo

import com.lipon.rakho.core.model.Batch
import com.lipon.rakho.core.model.DashboardStats
import com.lipon.rakho.core.model.ExpiryAlert
import com.lipon.rakho.core.model.LowStockAlert
import com.lipon.rakho.core.model.Medicine
import com.lipon.rakho.core.model.PharmacyProfile
import com.lipon.rakho.core.model.Sale
import com.lipon.rakho.core.money.Money
import com.lipon.rakho.core.time.DhakaTime
import com.lipon.rakho.core.time.ExpiryRules
import com.lipon.rakho.data.firebase.FirestoreData
import com.lipon.rakho.data.firebase.FirestoreRepository
import com.lipon.rakho.data.firebase.ReceiveStockItem
import com.lipon.rakho.data.session.SessionStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.map
import java.time.LocalDate

/** What the expiry radar shows. */
data class AlertSnapshot(
    val expired: List<ExpiryAlert> = emptyList(),
    val expiringSoon: List<ExpiryAlert> = emptyList(),
    val lowStock: List<LowStockAlert> = emptyList(),
)

/** Result of a write: landed in the cloud, or queued by offline persistence. */
sealed interface WriteOutcome {
    data object Synced : WriteOutcome
    data object Queued : WriteOutcome
}

/**
 * Inventory for the pharmacy, served entirely from Firestore.
 *
 * Reads come from the shared [FirestoreData] flows — realtime when online and
 * straight from the on-device cache when not, with no second store to keep in
 * step. Writes go through [FirestoreRepository]; Firestore's persistence
 * layer queues anything the network cannot take yet and replays it once, so
 * the counter never stops and nothing is ever double-applied.
 */
class InventoryRepository(
    private val firestore: FirestoreRepository,
    private val data: FirestoreData,
    private val sessionStore: SessionStore,
) {

    // ---- Reads -------------------------------------------------------------

    fun observeMedicines(): Flow<List<Medicine>> = data.medicines

    fun observeBatches(activeOnly: Boolean = false): Flow<List<Batch>> =
        if (activeOnly) data.batches.map { list -> list.filter { it.quantityAvailable > 0 } }
        else data.batches

    /** Expiry and low-stock radar, derived on device so it works offline. */
    fun observeAlerts(horizonDays: Long = ExpiryRules.EXPIRING_SOON_DAYS): Flow<AlertSnapshot> =
        combine(data.medicines, data.batches) { medicines, batches ->
            computeAlerts(medicines, batches, horizonDays, DhakaTime.today())
        }

    fun observeDashboard(): Flow<DashboardStats> =
        combine(data.medicines, data.batches, data.sales) { medicines, batches, sales ->
            computeDashboard(medicines, batches, sales, DhakaTime.today())
        }

    fun observeProfile(): Flow<PharmacyProfile?> = data.profile

    /** One-shot list for code that needs names without subscribing to a flow. */
    suspend fun medicinesSnapshot(): List<Medicine> = data.medicines.value

    /** Finds a medicine by brand + strength (case-insensitive), for just-created drafts. */
    suspend fun medicineByBrand(brandName: String, strength: String): Medicine? =
        data.medicines.value.firstOrNull {
            it.brandName.equals(brandName, ignoreCase = true) &&
                it.strength.equals(strength, ignoreCase = true)
        }

    // ---- Profile ------------------------------------------------------------

    suspend fun refreshProfile(): Result<PharmacyProfile> =
        Result.success(
            firestore.getProfile()
                ?: PharmacyProfile(name = sessionStore.current().shopName),
        )

    suspend fun updateProfile(name: String, phone: String, address: String): Result<Unit> =
        runCatching {
            firestore.saveProfile(name, phone, address)
            sessionStore.updateShopName(name)
        }

    // ---- Writes -------------------------------------------------------------

    suspend fun receiveStock(items: List<PurchaseItemRequest>): Result<WriteOutcome> =
        runCatching {
            val names = data.medicines.value.associateBy { it.id }
            firestore.receiveStock(
                items.map { item ->
                    val medicine = names[item.medicine]
                    ReceiveStockItem(
                        medicineId = item.medicine,
                        medicineName = medicine?.brandName ?: "",
                        medicineStrength = medicine?.strength ?: "",
                        batchNumber = item.batchNumber,
                        expiryDate = LocalDate.parse(item.expiryDate),
                        quantity = item.quantity,
                        unitCostPaisa = Money.parse(item.unitCost).paisa,
                        sellingPricePaisa = Money.parse(item.sellingPrice).paisa,
                        supplier = item.supplierName,
                    )
                },
                supplier = items.firstOrNull()?.supplierName.orEmpty(),
            )
            outcome()
        }

    suspend fun writeOffBatch(batchId: String, note: String): Result<WriteOutcome> =
        runCatching {
            firestore.writeOffBatch(batchId, note)
            outcome()
        }

    /** Corrects a medicine's details (price, threshold, names, barcode). */
    suspend fun updateMedicine(
        medicineId: String,
        request: UpdateMedicineRequest,
    ): Result<WriteOutcome> = runCatching {
        firestore.updateMedicine(
            medicineId = medicineId,
            brandName = request.brandName,
            genericName = request.genericName,
            strength = request.strength,
            dosageForm = request.dosageForm,
            barcode = request.barcode,
            sellingPricePaisa = request.defaultSellingPrice?.let { Money.parse(it).paisa },
            lowStockThreshold = request.lowStockThreshold,
        )
        outcome()
    }

    /** Corrects a batch; the counted quantity is absolute, never a delta. */
    suspend fun updateBatch(
        batchId: String,
        request: UpdateBatchRequest,
    ): Result<WriteOutcome> = runCatching {
        firestore.updateBatch(
            batchId = batchId,
            batchNumber = request.batchNumber,
            expiryDate = request.expiryDate?.let { LocalDate.parse(it) },
            unitCostPaisa = request.unitCost?.let { Money.parse(it).paisa },
            sellingPricePaisa = request.sellingPrice?.let { Money.parse(it).paisa },
            quantityAvailable = request.quantityAvailable,
        )
        outcome()
    }

    suspend fun addMedicine(request: CreateMedicineRequest): Result<WriteOutcome> =
        runCatching {
            firestore.addMedicine(
                brandName = request.brandName,
                genericName = request.genericName,
                strength = request.strength,
                dosageForm = request.dosageForm,
                barcode = request.barcode,
                sellingPricePaisa = Money.parse(request.defaultSellingPrice).paisa,
                lowStockThreshold = request.lowStockThreshold,
                catalogMedicineId = request.catalogMedicine,
            )
            outcome()
        }

    // ---- Derived data --------------------------------------------------------

    /**
     * A write that waits for the network is still a saved write — say which.
     * The listener metadata counter (not an SDK global) is the source: this
     * Android build of Firestore exposes no instance-wide pending-writes call.
     */
    private fun outcome(): WriteOutcome =
        if (data.pendingWrites.value > 0) {
            WriteOutcome.Queued
        } else {
            WriteOutcome.Synced
        }

    private fun computeAlerts(
        medicines: List<Medicine>,
        batches: List<Batch>,
        horizonDays: Long,
        today: LocalDate,
    ): AlertSnapshot {
        val stocked = batches.filter { it.quantityAvailable > 0 }
        val expired = stocked
            .filter { ExpiryRules.daysUntil(it.expiryDate, today) < 0 }
            .sortedBy { it.expiryDate }
            .map { ExpiryAlert(it, ExpiryRules.daysUntil(it.expiryDate, today)) }
        val expiring = stocked
            .filter {
                val days = ExpiryRules.daysUntil(it.expiryDate, today)
                days in 0..horizonDays
            }
            .sortedBy { it.expiryDate }
            .map { ExpiryAlert(it, ExpiryRules.daysUntil(it.expiryDate, today)) }

        val batchesByMedicine = stocked.groupBy { it.medicineId }
        val lowStock = medicines
            .filter { it.isActive }
            .mapNotNull { medicine ->
                val available = batchesByMedicine[medicine.id].orEmpty()
                    .sumOf { it.quantityAvailable }
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

    private fun computeDashboard(
        medicines: List<Medicine>,
        batches: List<Batch>,
        sales: List<Sale>,
        today: LocalDate,
    ): DashboardStats {
        val alerts = computeAlerts(medicines, batches, ExpiryRules.EXPIRING_SOON_DAYS, today)
        val stockValue = batches.fold(Money.ZERO) { acc, batch -> acc + batch.stockValue }
        // Money on the shelf that will be lost if nothing sells in time.
        val expiringValue = (alerts.expired + alerts.expiringSoon)
            .map { it.batch }
            .fold(Money.ZERO) { acc, batch -> acc + batch.stockValue }
        val todaySales = sales.filter {
            it.soldAt.atZone(DhakaTime.ZONE).toLocalDate() == today
        }
        return DashboardStats(
            todaySales = todaySales.fold(Money.ZERO) { acc, sale -> acc + sale.total },
            todayProfit = computeProfit(todaySales, batches),
            todaySaleCount = todaySales.size,
            stockValue = stockValue,
            medicineCount = medicines.size,
            expiredCount = alerts.expired.size,
            expiringSoonCount = alerts.expiringSoon.size,
            lowStockCount = alerts.lowStock.size,
            expiringValue = expiringValue,
        )
    }

    /**
     * Real gross profit: the FEFO allocation on every line records which batch
     * (and cost) was consumed. Cost captured at sale time is authoritative; the
     * live batch list is only a fallback for legacy rows. Lines with no known
     * cost contribute nothing rather than an invented number.
     */
    private fun computeProfit(sales: List<Sale>, batches: List<Batch>): Money {
        val costByBatchId = batches.associate { it.id to it.unitCost }
        return sales
            .flatMap { sale -> sale.lines.asSequence() }
            .map { line ->
                val revenue = line.unitPrice * line.quantity
                val cost = line.allocations
                    .fold(Money.ZERO) { acc, allocation ->
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
}
