package com.lipon.rakho.core.domain

import com.lipon.rakho.core.model.BatchAllocation
import com.lipon.rakho.core.money.Money
import com.lipon.rakho.core.time.ExpiryRules
import java.time.LocalDate

/** A batch as seen by the allocation planner. */
data class BatchStock(
    val batchId: String,
    val batchNumber: String,
    val expiryDate: LocalDate,
    val quantityAvailable: Int,
    val unitCost: Money,
    val sellingPrice: Money,
)

sealed interface FefoResult {
    data class Allocated(
        val allocations: List<BatchAllocation>,
        val cost: Money,
        val requested: Int,
    ) : FefoResult

    /** Not enough non-expired stock on hand. */
    data class InsufficientStock(val requested: Int, val available: Int) : FefoResult
}

/**
 * Plans a sale using First-Expired-First-Out, exactly like the backend:
 *  - expired batches are never allocated,
 *  - batches are consumed soonest-expiry first, ties broken by batch number
 *    so the result is deterministic across devices and the server,
 *  - requested quantity that cannot be covered reports the shortfall instead
 *    of silently over-allocating.
 */
object FefoPlanner {

    fun plan(
        stock: List<BatchStock>,
        requested: Int,
        today: LocalDate,
    ): FefoResult {
        if (requested <= 0) return FefoResult.Allocated(emptyList(), Money.ZERO, requested)

        val sellable = stock
            .filter { it.quantityAvailable > 0 && ExpiryRules.isSellable(it.expiryDate, today) }
            .sortedWith(compareBy({ it.expiryDate }, { it.batchNumber }))

        val available = sellable.sumOf { it.quantityAvailable }
        if (available < requested) return FefoResult.InsufficientStock(requested, available)

        val allocations = mutableListOf<BatchAllocation>()
        var remaining = requested
        var cost = Money.ZERO
        for (batch in sellable) {
            if (remaining <= 0) break
            val take = minOf(batch.quantityAvailable, remaining)
            allocations += BatchAllocation(
                batchId = batch.batchId,
                batchNumber = batch.batchNumber,
                expiryDate = batch.expiryDate,
                quantity = take,
            )
            cost += batch.unitCost * take
            remaining -= take
        }
        return FefoResult.Allocated(allocations, cost, requested)
    }
}
