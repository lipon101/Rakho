package com.lipon.rakho.data.repo

import com.lipon.rakho.core.domain.BatchStock
import com.lipon.rakho.core.domain.FefoPlanner
import com.lipon.rakho.core.domain.FefoResult
import com.lipon.rakho.core.model.Batch
import com.lipon.rakho.core.model.CartLine
import com.lipon.rakho.core.model.Medicine
import com.lipon.rakho.core.model.PendingOperationType
import com.lipon.rakho.core.model.PaymentMethod
import com.lipon.rakho.core.model.Sale
import com.lipon.rakho.core.result.AppError
import com.lipon.rakho.core.time.DhakaTime
import com.lipon.rakho.data.local.LocalCache
import com.lipon.rakho.data.local.LocalMedicineDto
import com.lipon.rakho.data.remote.RakhoApi
import com.lipon.rakho.data.remote.apiCall
import com.lipon.rakho.data.remote.dto.BatchDto
import com.lipon.rakho.data.remote.dto.CreateSaleRequest
import com.lipon.rakho.data.remote.dto.MedicineDto
import com.lipon.rakho.data.remote.dto.SaleDto
import com.lipon.rakho.data.remote.dto.SaleLineRequest
import com.lipon.rakho.data.remote.toDomain
import com.lipon.rakho.data.remote.toApiValue
import com.lipon.rakho.data.session.SessionStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json
import java.time.LocalDate
import java.util.UUID

/** A completed sale, whether it reached the server or is waiting to sync. */
data class SaleRecord(
    val invoiceNumber: String,
    val lines: List<CartLine>,
    val queued: Boolean,
    val soldAtMillis: Long,
)

/**
 * Sales, offline-first by design.
 *
 * Connected: the server allocates batches and is the record of truth.
 * Offline or local-only: the same FEFO rules run on device against the cached
 * (or locally-created) batches, the sale is stored in [LocalCache.KEY_LOCAL_SALES]
 * or queued for replay, and stock is deducted locally so the next sale sees
 * the truth. Offline sales carry a device-generated invoice number that the
 * server rejects as a duplicate on replay, so a sale can never be booked twice.
 */
class SalesRepository(
    private val api: RakhoApi,
    private val cache: LocalCache,
    private val inventory: InventoryRepository,
    private val sessionStore: SessionStore,
    private val json: Json,
) {

    private val saleListSerializer = ListSerializer(SaleDto.serializer())
    private val batchListSerializer = ListSerializer(BatchDto.serializer())

    fun observeSales(): Flow<List<Sale>> = cache.revision.map {
        readServerSales() + readLocalSales()
    }

    /** One-shot list for reports, in the same order the UI shows them. */
    suspend fun salesSnapshot(): List<Sale> = readServerSales() + readLocalSales()

    suspend fun recordSale(
        lines: List<CartLine>,
        paymentMethod: PaymentMethod,
        note: String,
        invoiceNumber: String,
    ): Result<SaleRecord> {
        val request = CreateSaleRequest(
            invoiceNumber = invoiceNumber,
            paymentMethod = paymentMethod.toApiValue(),
            note = note,
            lines = lines.map {
                SaleLineRequest(
                    medicine = it.medicineId,
                    quantity = it.quantity,
                    unitPrice = it.unitPrice.toBigDecimal().toPlainString(),
                )
            },
        )

        if (sessionStore.current().isConnected) {
            val remote = apiCall(json) { api.createSale(request) }
            remote.fold(
                onSuccess = {
                    refreshSales()
                    return Result.success(
                        SaleRecord(
                            invoiceNumber,
                            lines,
                            queued = false,
                            soldAtMillis = System.currentTimeMillis(),
                        ),
                    )
                },
                onFailure = { error ->
                    if (error !is AppError.Network) return Result.failure(error)
                },
            )
        }

        // Offline / local-only path: allocate against batches the device knows.
        val cachedBatches = readServerBatches() + readLocalBatches()
        val today = DhakaTime.today()

        val deductions = mutableMapOf<String, Int>()
        val resolvedLines = mutableListOf<CartLine>()
        for (line in lines) {
            val stock = cachedBatches
                .filter { it.medicineId == line.medicineId }
                .map {
                    BatchStock(
                        batchId = it.id,
                        batchNumber = it.batchNumber,
                        expiryDate = it.expiryDate,
                        quantityAvailable = it.quantityAvailable,
                        unitCost = it.unitCost,
                        sellingPrice = it.sellingPrice,
                    )
                }
            when (val plan = FefoPlanner.plan(stock, line.quantity, today)) {
                is FefoResult.InsufficientStock ->
                    return Result.failure(AppError.Validation("insufficient stock"))
                is FefoResult.Allocated -> {
                    plan.allocations.forEach { allocation ->
                        deductions[allocation.batchId] =
                            (deductions[allocation.batchId] ?: 0) + allocation.quantity
                    }
                    resolvedLines += line.copy(allocations = plan.allocations)
                }
            }
        }

        if (sessionStore.current().isConnected) {
            cache.enqueue(PendingOperationType.SALE, json.encodeToString(request))
        } else {
            storeLocalSale(resolvedLines, paymentMethod, invoiceNumber)
        }
        inventory.applyOfflineAllocations(deductions)
        return Result.success(
            SaleRecord(
                invoiceNumber,
                resolvedLines,
                queued = true,
                soldAtMillis = System.currentTimeMillis(),
            ),
        )
    }

    suspend fun refreshSales(): Result<Unit> = apiCall(json) {
        val sales = api.sales().results
        cache.write(LocalCache.KEY_SALES, sales) { json.encodeToString(saleListSerializer, it) }
    }

    /**
     * Deterministic, per-pharmacy-unique invoice number (max 50 chars).
     * In local-only mode a readable LH-0001-style sequence is used instead,
     * which is what a counter shop actually writes on a receipt.
     */
    suspend fun nextInvoiceNumber(deviceId: String): String {
        if (!sessionStore.current().isConnected) {
            val next = cache.nextPendingId()
            return "LH-${next.toString().padStart(4, '0')}"
        }
        val suffix = UUID.randomUUID().toString().take(6).uppercase()
        val stamp = System.currentTimeMillis().toString().takeLast(9)
        val device = deviceId.ifBlank { "DEV" }.take(6).uppercase()
        return "RKH-$device-$stamp-$suffix"
    }

    // ---- Local sale storage ------------------------------------------------

    private suspend fun storeLocalSale(
        lines: List<CartLine>,
        paymentMethod: PaymentMethod,
        invoiceNumber: String,
    ) {
        val dto = SaleDto(
            id = UUID.randomUUID().toString(),
            invoiceNumber = invoiceNumber,
            soldAt = java.time.Instant.ofEpochMilli(System.currentTimeMillis()).toString(),
            totalAmount = lines.fold(java.math.BigDecimal.ZERO) { acc, line ->
                acc + line.unitPrice.toBigDecimal().multiply(java.math.BigDecimal(line.quantity))
            }.toPlainString(),
            paymentMethod = paymentMethod.toApiValue(),
            note = "recorded offline",
            lines = lines.map {
                com.lipon.rakho.data.remote.dto.SaleLineDto(
                    medicine = it.medicineId,
                    medicineName = it.medicineName,
                    quantity = it.quantity,
                    unitPrice = it.unitPrice.toBigDecimal().toPlainString(),
                    lineTotal = it.unitPrice.toBigDecimal()
                        .multiply(java.math.BigDecimal(it.quantity)).toPlainString(),
                    allocations = it.allocations.map { allocation ->
                        com.lipon.rakho.data.remote.dto.SaleAllocationDto(
                            batch = allocation.batchId,
                            batchNumber = allocation.batchNumber,
                            expiryDate = allocation.expiryDate.toString(),
                            quantity = allocation.quantity,
                            unitCost = allocation.unitCost.toBigDecimal().toPlainString(),
                        )
                    },
                )
            },
        )
        cache.write(
            LocalCache.KEY_LOCAL_SALES,
            readLocalSaleDtos() + dto,
        ) { json.encodeToString(saleListSerializer, it) }
    }

    private suspend fun readLocalSaleDtos(): List<SaleDto> =
        cache.read(LocalCache.KEY_LOCAL_SALES) { json.decodeFromString(saleListSerializer, it) }
            .orEmpty()

    private suspend fun readLocalSales(): List<Sale> =
        readLocalSaleDtos().mapNotNull { it.toDomain() }

    private suspend fun readServerSales(): List<Sale> =
        cache.read(LocalCache.KEY_SALES) { json.decodeFromString(saleListSerializer, it) }
            ?.mapNotNull { it.toDomain() }
            .orEmpty()

    private suspend fun readServerBatches(): List<Batch> =
        cache.read(LocalCache.KEY_BATCHES) { json.decodeFromString(batchListSerializer, it) }
            ?.mapNotNull { it.toDomain() }
            .orEmpty()

    private suspend fun readLocalBatches(): List<Batch> =
        cache.read(LocalCache.KEY_LOCAL_BATCHES) { json.decodeFromString(batchListSerializer, it) }
            ?.mapNotNull { it.toDomain() }
            .orEmpty()
}
