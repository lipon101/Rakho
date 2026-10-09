package com.lipon.rakho.data.repo

import com.lipon.rakho.core.domain.BatchStock
import com.lipon.rakho.core.domain.FefoPlanner
import com.lipon.rakho.core.domain.FefoResult
import com.lipon.rakho.core.model.CartLine
import com.lipon.rakho.core.model.PaymentMethod
import com.lipon.rakho.core.model.Sale
import com.lipon.rakho.core.money.Money
import com.lipon.rakho.core.result.AppError
import com.lipon.rakho.core.time.DhakaTime
import com.lipon.rakho.data.firebase.FirestoreData
import com.lipon.rakho.data.firebase.FirestoreRepository
import kotlinx.coroutines.flow.Flow
import java.util.UUID

/** A completed sale, whether it reached the server or is still queued offline. */
data class SaleRecord(
    val invoiceNumber: String,
    val lines: List<CartLine>,
    val queued: Boolean,
    val soldAtMillis: Long,
    /** Discount the counter gave; part of the sale's truth, not cosmetic. */
    val discount: Money = Money.ZERO,
    /** Baki customer, when the sale was booked on credit. */
    val customerName: String = "",
)

/**
 * Sales over Firestore, offline-safe by design.
 *
 * FEFO allocation runs on device against the shared batch flow, then
 * [FirestoreRepository.recordSale] writes the sale, the batch deductions and
 * the matching customer due as one batched commit. Firestore's offline
 * persistence queues the commit when there is no network and replays it
 * exactly once — increments cannot double-deduct — so the counter never
 * waits on the internet.
 */
class SalesRepository(
    private val firestore: FirestoreRepository,
    private val data: FirestoreData,
) {

    fun observeSales(): Flow<List<Sale>> = data.sales

    /** One-shot list for reports, in the same order the UI shows them. */
    suspend fun salesSnapshot(): List<Sale> = data.sales.value

    suspend fun recordSale(
        lines: List<CartLine>,
        paymentMethod: PaymentMethod,
        note: String,
        invoiceNumber: String,
        discount: Money = Money.ZERO,
        customerName: String = "",
    ): Result<SaleRecord> {
        val today = DhakaTime.today()
        val batches = data.batches.value

        val resolvedLines = mutableListOf<CartLine>()
        for (line in lines) {
            val stock = batches
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
                is FefoResult.Allocated ->
                    resolvedLines += line.copy(allocations = plan.allocations)
            }
        }

        val written = runCatching {
            firestore.recordSale(
                invoiceNumber = invoiceNumber,
                lines = resolvedLines,
                paymentMethod = paymentMethod,
                discount = discount,
                note = note,
                customerName = customerName,
            )
        }
        if (written.isFailure) {
            val error = written.exceptionOrNull()
            return Result.failure(
                if (error is AppError) error else AppError.Unknown(error),
            )
        }

        return Result.success(
            SaleRecord(
                invoiceNumber,
                resolvedLines,
                queued = data.pendingWrites.value > 0,
                soldAtMillis = System.currentTimeMillis(),
                discount = discount,
                customerName = customerName,
            ),
        )
    }

    /**
     * Deterministic, per-pharmacy-unique invoice number (max 50 chars).
     * The suffix and timestamp make collisions impossible across devices of
     * the same shop; the device prefix tells a supplier which till wrote it.
     */
    suspend fun nextInvoiceNumber(deviceId: String): String {
        val suffix = UUID.randomUUID().toString().take(6).uppercase()
        val stamp = System.currentTimeMillis().toString().takeLast(9)
        val device = deviceId.ifBlank { "DEV" }.take(6).uppercase()
        return "RKH-$device-$stamp-$suffix"
    }
}
