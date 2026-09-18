package com.lipon.rakho.core

import com.lipon.rakho.core.domain.BatchStock
import com.lipon.rakho.core.domain.FefoPlanner
import com.lipon.rakho.core.domain.FefoResult
import com.lipon.rakho.core.money.Money
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate

class FefoPlannerTest {

    private val today = LocalDate.of(2026, 9, 18)

    private fun batch(
        id: String,
        expiry: String,
        quantity: Int,
        cost: String = "10.00",
    ) = BatchStock(
        batchId = id,
        batchNumber = id.uppercase(),
        expiryDate = LocalDate.parse(expiry),
        quantityAvailable = quantity,
        unitCost = Money.parse(cost),
        sellingPrice = Money.parse("15.00"),
    )

    @Test
    fun `consumes the soonest expiring batch first`() {
        val stock = listOf(
            batch("b2", "2027-06-01", 50),
            batch("b1", "2026-12-01", 20),
            batch("b3", "2028-01-01", 100),
        )
        val result = FefoPlanner.plan(stock, 30, today)
        assertTrue(result is FefoResult.Allocated)
        val allocations = (result as FefoResult.Allocated).allocations
        assertEquals(listOf("b1", "b2"), allocations.map { it.batchId })
        assertEquals(listOf(20, 10), allocations.map { it.quantity })
    }

    @Test
    fun `carries the batch cost at allocation time`() {
        // Profit accounting depends on the cost captured at sale time:
        // the batch may be fully sold and gone from the stock list later.
        val stock = listOf(
            batch("cheap", "2026-12-01", 10, cost = "8.00"),
            batch("dear", "2027-01-01", 10, cost = "12.50"),
        )
        val allocations = (FefoPlanner.plan(stock, 15, today) as FefoResult.Allocated).allocations
        assertEquals(
            Money.parse("8.00") * 10 + Money.parse("12.50") * 5,
            allocations.fold(Money.ZERO) { acc, a -> acc + a.unitCost * a.quantity },
        )
    }

    @Test
    fun `never allocates an expired batch`() {
        val stock = listOf(
            batch("expired", "2026-08-31", 100),
            batch("good", "2027-01-01", 5),
        )
        val result = FefoPlanner.plan(stock, 5, today) as FefoResult.Allocated
        assertEquals(listOf("good"), result.allocations.map { it.batchId })
    }

    @Test
    fun `reports the shortfall instead of over-allocating`() {
        val stock = listOf(batch("only", "2027-01-01", 3))
        val result = FefoPlanner.plan(stock, 10, today)
        assertTrue(result is FefoResult.InsufficientStock)
        assertEquals(3, (result as FefoResult.InsufficientStock).available)
    }

    @Test
    fun `treats a batch expiring today as sellable`() {
        val stock = listOf(batch("today", "2026-09-18", 4))
        val result = FefoPlanner.plan(stock, 4, today) as FefoResult.Allocated
        assertEquals(4, result.allocations.single().quantity)
    }

    @Test
    fun `ties on expiry are broken deterministically by batch number`() {
        val stock = listOf(
            batch("z9", "2027-01-01", 5),
            batch("a1", "2027-01-01", 5),
        )
        val first = FefoPlanner.plan(stock, 6, today) as FefoResult.Allocated
        val second = FefoPlanner.plan(stock.reversed(), 6, today) as FefoResult.Allocated
        assertEquals(first.allocations.map { it.batchId }, second.allocations.map { it.batchId })
        assertEquals(listOf("a1", "z9"), first.allocations.map { it.batchId })
    }

    @Test
    fun `returns the cost of the allocated units`() {
        val stock = listOf(
            batch("b1", "2026-12-01", 2, cost = "8.00"),
        )
        val result = FefoPlanner.plan(stock, 2, today) as FefoResult.Allocated
        assertEquals(Money.parse("16.00"), result.cost)
    }

    @Test
    fun `zero quantity allocates nothing`() {
        val result = FefoPlanner.plan(listOf(batch("b1", "2027-01-01", 5)), 0, today)
        assertTrue(result is FefoResult.Allocated)
        assertTrue((result as FefoResult.Allocated).allocations.isEmpty())
    }
}
