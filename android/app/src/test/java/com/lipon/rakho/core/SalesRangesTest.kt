package com.lipon.rakho.core.time

import com.lipon.rakho.core.model.PaymentMethod
import com.lipon.rakho.core.model.Sale
import com.lipon.rakho.core.money.Money
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate
import java.time.ZoneOffset

/**
 * Every range boundary is a Dhaka calendar boundary, and every bucket sum is
 * paisa-exact: the dashboard trend, Reports KPIs, top-sellers and CSV export
 * all share these predicates, so they can never disagree.
 */
class SalesRangesTest {

    private val today: LocalDate = LocalDate.of(2026, 10, 9)

    private fun sale(date: LocalDate, paisa: Long, hour: Int = 10): Sale = Sale(
        id = "$date-$hour-$paisa",
        invoiceNumber = "INV-$date",
        soldAt = date.atTime(hour, 0).atZone(DhakaTime.ZONE).toInstant(),
        total = Money(paisa),
        paymentMethod = PaymentMethod.CASH,
    )

    private fun rangeTotal(range: SalesRange, sales: List<Sale>): Long =
        SalesRanges.filterForRange(sales, range, today).fold(0L) { acc, s -> acc + s.total.paisa }

    @Test
    fun `range boundaries are exact Dhaka calendar days`() {
        assertEquals(today, SalesRanges.startDate(SalesRange.LAST_1H, today))
        assertEquals(today, SalesRanges.startDate(SalesRange.LAST_24H, today))
        assertEquals(LocalDate.of(2026, 10, 3), SalesRanges.startDate(SalesRange.LAST_7D, today))
        assertEquals(LocalDate.of(2026, 9, 10), SalesRanges.startDate(SalesRange.LAST_30D, today))
        assertEquals(LocalDate.of(2025, 10, 10), SalesRanges.startDate(SalesRange.LAST_1Y, today))
        assertEquals(today, SalesRanges.endDate(SalesRange.LAST_1Y, today))
    }

    @Test
    fun `last 7 days includes the boundary day and excludes the day before`() {
        val sales = listOf(
            sale(LocalDate.of(2026, 10, 3), 100_00),
            sale(LocalDate.of(2026, 10, 2), 999_00),
        )
        assertEquals(100_00L, rangeTotal(SalesRange.LAST_7D, sales))
    }

    @Test
    fun `last 24h holds exactly today's sales`() {
        val sales = listOf(
            sale(today, 500_00, hour = 9),
            sale(today.minusDays(1), 999_00, hour = 9),
        )
        assertEquals(500_00L, rangeTotal(SalesRange.LAST_24H, sales))
        // Hourly shape: 24 buckets, newest (current hour) highlighted.
        val buckets = SalesRanges.buckets(sales, SalesRange.LAST_24H, today)
        assertEquals(24, buckets.size)
        assertTrue(buckets.last().highlighted)
        assertEquals(500_00L, buckets.fold(0L) { acc, b -> acc + b.total.paisa })
    }

    @Test
    fun `bucket sums equal the filtered total for every range`() {
        val sales = listOf(
            sale(today, 500_00, hour = 9),
            sale(today, 300_00, hour = 14),
            sale(LocalDate.of(2026, 10, 1), 200_00),
            sale(LocalDate.of(2026, 8, 15), 700_00),
            sale(LocalDate.of(2026, 3, 10), 400_00),
            sale(LocalDate.of(2025, 6, 5), 600_00),
            sale(LocalDate.of(2024, 12, 31), 999_00),
        )
        for (range in SalesRange.entries) {
            val expected = rangeTotal(range, sales)
            val bucketed = SalesRanges.buckets(sales, range, today).fold(0L) { acc, b -> acc + b.total.paisa }
            assertEquals("range $range", expected, bucketed)
        }
        // Spot-check the spread: 7D holds Oct 3–9 (Oct 1 falls outside);
        // 1Y holds everything from 2025-10-10.
        assertEquals(800_00L, rangeTotal(SalesRange.LAST_7D, sales))
        assertEquals(2_100_00L, rangeTotal(SalesRange.LAST_1Y, sales))
    }

    @Test
    fun `hourly labels use the 12-hour clock`() {
        assertEquals("12 AM", SalesRanges.hourLabel(0))
        assertEquals("9 AM", SalesRanges.hourLabel(9))
        assertEquals("12 PM", SalesRanges.hourLabel(12))
        assertEquals("3 PM", SalesRanges.hourLabel(15))
        assertEquals("11 PM", SalesRanges.hourLabel(23))
    }

    @Test
    fun `smart axis strips meridiem noise and names recent weekdays`() {
        assertEquals("9", SalesRanges.smartAxisLabel("9 PM", SalesRange.LAST_24H))
        assertEquals("12 AM", SalesRanges.smartAxisLabel("12 AM", SalesRange.LAST_24H))
        assertEquals("Now", SalesRanges.smartAxisLabel("Now", SalesRange.LAST_24H))
        assertEquals("Today", SalesRanges.smartAxisLabel("Today", SalesRange.LAST_7D))
        // 3 days before Oct 9 2026 is Tuesday Oct 6.
        assertEquals("Tue", SalesRanges.smartAxisLabel("06 Oct", SalesRange.LAST_7D))
        // A far date keeps its slim form.
        assertEquals("10 Sep", SalesRanges.smartAxisLabel("10 Sep", SalesRange.LAST_30D))
    }

    @Test
    fun `daily buckets label only first middles and today`() {
        val buckets = SalesRanges.buckets(emptyList(), SalesRange.LAST_30D, today)
        assertEquals(30, buckets.size)
        val labelled = buckets.filter { it.label.isNotEmpty() }
        assertEquals(3, labelled.size)
        assertEquals("10 Sep", labelled[0].label)
        assertEquals("Today", labelled.last().label)
        assertTrue(buckets.last().highlighted)
    }

    @Test
    fun `last hour draws six buckets with only now labelled`() {
        val buckets = SalesRanges.buckets(emptyList(), SalesRange.LAST_1H, today)
        assertEquals(6, buckets.size)
        assertEquals(listOf("Now"), buckets.map { it.label }.filter { it.isNotEmpty() })
        assertTrue(buckets.last().highlighted)
        assertTrue(buckets.dropLast(1).none { it.highlighted })
    }

    @Test
    fun `24h labels only start middles and now`() {
        val buckets = SalesRanges.buckets(emptyList(), SalesRange.LAST_24H, today)
        assertEquals(24, buckets.size)
        assertEquals(4, buckets.count { it.label.isNotEmpty() })
        assertEquals("Now", buckets.last().label)
    }

    @Test
    fun `sales timestamped in UTC land on the right Dhaka day`() {
        // 2026-10-02 20:30 UTC == 2026-10-03 02:30 Dhaka → inside LAST_7D.
        val utcSale = Sale(
            id = "utc-1",
            invoiceNumber = "INV-UTC",
            soldAt = LocalDate.of(2026, 10, 2).atTime(20, 30).atZone(ZoneOffset.UTC).toInstant(),
            total = Money(50_00),
            paymentMethod = PaymentMethod.CASH,
        )
        assertEquals(50_00L, rangeTotal(SalesRange.LAST_7D, listOf(utcSale)))
    }
}
