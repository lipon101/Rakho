package com.lipon.rakho.core.domain

import com.lipon.rakho.core.model.Batch
import com.lipon.rakho.core.model.BatchAllocation
import com.lipon.rakho.core.model.CartLine
import com.lipon.rakho.core.model.Medicine
import com.lipon.rakho.core.model.PaymentMethod
import com.lipon.rakho.core.model.Sale
import com.lipon.rakho.core.money.Money
import com.lipon.rakho.core.time.DhakaTime
import com.lipon.rakho.core.time.SalesRange
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate

/**
 * Reports math is the shop's money truth: profit from real FEFO costs,
 * previous-window deltas, payment % that sums to 100, and slow movers from
 * live batches — never estimates.
 */
class SalesAnalyticsTest {

    private val today = LocalDate.of(2026, 10, 9)

    private fun sale(
        date: LocalDate,
        paisa: Long,
        method: PaymentMethod = PaymentMethod.CASH,
        lines: List<CartLine> = emptyList(),
    ) = Sale(
        id = "$date-$paisa-${method.name}",
        invoiceNumber = "INV-$date",
        soldAt = date.atTime(10, 0).atZone(DhakaTime.ZONE).toInstant(),
        total = Money(paisa),
        paymentMethod = method,
        lines = lines,
    )

    private fun line(
        medicineId: String,
        name: String,
        pricePaisa: Long,
        qty: Int,
        costPaisa: Long,
    ) = CartLine(
        medicineId = medicineId,
        medicineName = name,
        unitPrice = Money(pricePaisa),
        quantity = qty,
        allocations = listOf(
            BatchAllocation(
                batchId = "b-$medicineId",
                batchNumber = "B1",
                expiryDate = today.plusYears(1),
                quantity = qty,
                unitCost = Money(costPaisa),
            ),
        ),
    )

    @Test
    fun `profit uses FEFO costs and legacy lines stay out of the margin`() {
        // 10 pcs bought at ৳70, sold at ৳100 → profit ৳300 on ৳1,000 known.
        val withCost = sale(
            date = today,
            paisa = 1_000_00,
            lines = listOf(line("m1", "Napa", 100_00, 10, 70_00)),
        )
        val legacy = sale(
            date = today,
            paisa = 500_00,
            lines = listOf(
                CartLine("m2", "Seclo", Money(500_00), 1, emptyList()),
            ),
        )
        val (profit, known) = SalesAnalytics.profitAndKnownRevenue(listOf(withCost, legacy))
        // Profit 300 on the cost-known 1,000 line; the 500 legacy line ignored.
        assertEquals(300_00L, profit.paisa)
        assertEquals(1_000_00L, known.paisa)
    }

    @Test
    fun `previous window is the same length immediately before`() {
        val sales = listOf(
            sale(LocalDate.of(2026, 10, 5), 700_00),
            sale(LocalDate.of(2026, 9, 30), 300_00),
            sale(LocalDate.of(2026, 9, 25), 999_00),
        )
        // 7D window Oct 3–9; previous window Sep 26–Oct 2 holds Sep 30 only.
        val prev = SalesAnalytics.previousWindowTotal(sales, SalesRange.LAST_7D, today)
        assertEquals(300_00L, prev?.paisa)
    }

    @Test
    fun `payment percentages always sum to 100`() {
        val sales = listOf(
            sale(today, 100_00, PaymentMethod.CASH),
            sale(today, 100_00, PaymentMethod.BKASH),
            sale(today, 100_00, PaymentMethod.NAGAD),
        )
        val analytics = SalesAnalytics.analyze(
            sales, emptyList(), emptyList(), SalesRange.LAST_7D, today,
        )
        assertEquals(100, analytics.paymentSlices.sumOf { it.percent })
        assertEquals(3, analytics.paymentSlices.size)
    }

    @Test
    fun `slow movers are unsold stocked medicines ordered by capital`() {
        val medA = Medicine("a", "FastMed")
        val medB = Medicine("b", "SlowMed")
        val medC = Medicine("c", "OldStock")
        fun batch(id: String, med: String, qty: Int, costPaisa: Long) = Batch(
            id = id,
            medicineId = med,
            medicineName = med,
            batchNumber = "B1",
            expiryDate = today.plusYears(1),
            unitCost = Money(costPaisa),
            sellingPrice = Money(costPaisa + 1_000),
            quantityReceived = qty,
            quantityAvailable = qty,
        )
        val batches = listOf(
            batch("1", "a", 10, 50_00),
            batch("2", "b", 5, 200_00),
            batch("3", "c", 0, 999_00),
        )
        val sales = listOf(
            sale(today, 100_00, lines = listOf(line("a", "FastMed", 100_00, 1, 50_00))),
        )
        val analytics = SalesAnalytics.analyze(
            sales, batches, listOf(medA, medB, medC), SalesRange.LAST_7D, today,
        )
        // Only SlowMed: OldStock has zero units, FastMed sold.
        assertEquals(listOf("b"), analytics.slowMovers.map { it.medicineId })
        assertEquals(5, analytics.slowMovers.first().unitsOnHand)
    }

    @Test
    fun `empty range yields nulls not zeros-that-lie`() {
        val analytics = SalesAnalytics.analyze(
            emptyList(), emptyList(), emptyList(), SalesRange.LAST_7D, today,
        )
        assertTrue(analytics.total.isZero)
        assertNull(analytics.marginPct)
        assertTrue(analytics.paymentSlices.isEmpty())
        assertTrue(analytics.slowMovers.isEmpty())
    }
}
