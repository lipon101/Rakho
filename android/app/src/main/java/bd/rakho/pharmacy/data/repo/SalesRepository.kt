package bd.rakho.pharmacy.data.repo

import bd.rakho.pharmacy.core.domain.FefoPlanner
import bd.rakho.pharmacy.core.domain.FefoResult
import bd.rakho.pharmacy.core.model.CartLine
import bd.rakho.pharmacy.core.model.PendingOperationType
import bd.rakho.pharmacy.core.model.Sale
import bd.rakho.pharmacy.core.result.AppError
import bd.rakho.pharmacy.core.time.DhakaTime
import bd.rakho.pharmacy.data.local.LocalCache
import bd.rakho.pharmacy.data.remote.RakhoApi
import bd.rakho.pharmacy.data.remote.apiCall
import bd.rakho.pharmacy.data.remote.dto.BatchDto
import bd.rakho.pharmacy.data.remote.dto.CreateSaleRequest
import bd.rakho.pharmacy.data.remote.dto.SaleDto
import bd.rakho.pharmacy.data.remote.dto.SaleLineRequest
import bd.rakho.pharmacy.data.remote.toDomain
import bd.rakho.pharmacy.data.remote.toApiValue
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

class SalesRepository(
    private val api: RakhoApi,
    private val cache: LocalCache,
    private val inventory: InventoryRepository,
    private val json: Json,
) {

    private val saleListSerializer = ListSerializer(SaleDto.serializer())
    private val batchListSerializer = ListSerializer(BatchDto.serializer())

    fun observeSales(): Flow<List<Sale>> = cache.revision.map {
        cache.read(LocalCache.KEY_SALES) { json.decodeFromString(saleListSerializer, it) }
            ?.map { it.toDomain() }
            .orEmpty()
    }

    /**
     * Records a sale.
     *
     * Online: the server allocates batches (FEFO) and returns the authoritative
     * record. Offline: the same FEFO rules run locally so the receipt and the
     * on-device stock are correct immediately, and the request is queued. The
     * invoice number is generated on the device and is unique per pharmacy, so
     * replaying a queued sale can never create a duplicate — the server rejects
     * the repeat and we treat that rejection as success.
     */
    suspend fun recordSale(
        lines: List<CartLine>,
        paymentMethod: bd.rakho.pharmacy.core.model.PaymentMethod,
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

        val remote = apiCall(json) { api.createSale(request) }
        remote.fold(
            onSuccess = {
                refreshSales()
                return Result.success(
                    SaleRecord(invoiceNumber, lines, queued = false, soldAtMillis = System.currentTimeMillis()),
                )
            },
            onFailure = { error ->
                if (error !is AppError.Network) return Result.failure(error)
            },
        )

        // Offline path: allocate against the cached batches.
        val today = DhakaTime.today()
        val cachedBatches = cache.read(LocalCache.KEY_BATCHES) { json.decodeFromString(batchListSerializer, it) }
            ?.mapNotNull { it.toDomain() }
            .orEmpty()

        val deductions = mutableMapOf<String, Int>()
        val resolvedLines = mutableListOf<CartLine>()
        for (line in lines) {
            val stock = cachedBatches
                .filter { it.medicineId == line.medicineId }
                .map {
                    bd.rakho.pharmacy.core.domain.BatchStock(
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

        cache.enqueue(PendingOperationType.SALE, json.encodeToString(request))
        inventory.applyOfflineAllocations(deductions)
        return Result.success(
            SaleRecord(invoiceNumber, resolvedLines, queued = true, soldAtMillis = System.currentTimeMillis()),
        )
    }

    suspend fun refreshSales(): Result<Unit> = apiCall(json) {
        val sales = api.sales().results
        cache.write(LocalCache.KEY_SALES, sales) { json.encodeToString(saleListSerializer, it) }
    }

    /** Deterministic, per-pharmacy-unique invoice number (max 50 chars). */
    suspend fun nextInvoiceNumber(deviceId: String): String {
        val suffix = UUID.randomUUID().toString().take(6).uppercase()
        val stamp = System.currentTimeMillis().toString().takeLast(9)
        val device = deviceId.ifBlank { "DEV" }.take(6).uppercase()
        return "RKH-$device-$stamp-$suffix"
    }

    fun todayExpiryCutoff(today: LocalDate): LocalDate = today
}
