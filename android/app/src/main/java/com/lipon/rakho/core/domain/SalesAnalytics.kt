package com.lipon.rakho.core.domain

import com.lipon.rakho.core.model.Batch
import com.lipon.rakho.core.model.Medicine
import com.lipon.rakho.core.model.PaymentMethod
import com.lipon.rakho.core.model.Sale
import com.lipon.rakho.core.money.Money
import com.lipon.rakho.core.time.DhakaTime
import com.lipon.rakho.core.time.SalesRange
import com.lipon.rakho.core.time.SalesRanges
import java.time.LocalDate

/** One payment method's share of the range: exact amount + percentage. */
data class PaymentSlice(
    val method: PaymentMethod,
    val amount: Money,
    /** 0–100, rounded half-up; slices always sum to 100 when total > 0. */
    val percent: Int,
)

/** A medicine with stock on hand but zero sales in the range — dead capital. */
data class SlowMover(
    val medicineId: String,
    val name: String,
    val unitsOnHand: Int,
    val valueOnHand: Money,
)

/** Everything the analysis studio needs for one range, from live data only. */
data class RangeAnalytics(
    val total: Money,
    val billCount: Int,
    val itemCount: Int,
    /** True profit from FEFO unit costs captured at sale time. */
    val profit: Money,
    /** Margin % = profit / revenue, null when there is no revenue. */
    val marginPct: Double?,
    /** Same-length window immediately before the range. */
    val previousTotal: Money?,
    /** % change vs previous window; null when not computable. */
    val deltaPct: Double?,
    val paymentSlices: List<PaymentSlice>,
    val slowMovers: List<SlowMover>,
)

/**
 * Business intelligence over live sales, batches and medicines — no
 * estimates, no static margins. Profit comes from the FEFO `unitCost`
 * captured on every sale line at checkout; lines without cost data (old
 * server sales) contribute revenue but are excluded from profit, and the
 * margin denominator only covers cost-known revenue so the % stays honest.
 */
object SalesAnalytics {

    fun analyze(
        sales: List<Sale>,
        batches: List<Batch>,
        medicines: List<Medicine>,
        range: SalesRange,
        today: LocalDate,
    ): RangeAnalytics {
        val filtered = SalesRanges.filterForRange(sales, range, today)
        val total = filtered.fold(Money.ZERO) { acc, sale -> acc + sale.total }
        val (profit, costKnownRevenue) = profitAndKnownRevenue(filtered)
        val margin = if (costKnownRevenue.paisa > 0) {
            profit.paisa * 100.0 / costKnownRevenue.paisa
        } else {
            null
        }
        val previousTotal = previousWindowTotal(sales, range, today)
        val delta = if (previousTotal != null && previousTotal.paisa > 0) {
            (total.paisa - previousTotal.paisa) * 100.0 / previousTotal.paisa
        } else {
            null
        }
        return RangeAnalytics(
            total = total,
            billCount = filtered.size,
            itemCount = filtered.sumOf { sale -> sale.lines.sumOf { it.quantity } },
            profit = profit,
            marginPct = margin,
            previousTotal = previousTotal,
            deltaPct = delta,
            paymentSlices = paymentSlices(filtered, total),
            slowMovers = slowMovers(filtered, batches, medicines),
        )
    }

    /**
     * True profit + the revenue it was computed from. A line's cost is the
     * sum of its FEFO allocations; a line with no allocations (legacy sale)
     * is cost-unknown and excluded from BOTH so the margin never dilutes.
     */
    fun profitAndKnownRevenue(sales: List<Sale>): Pair<Money, Money> {
        var profit = Money.ZERO
        var knownRevenue = Money.ZERO
        for (sale in sales) {
            for (line in sale.lines) {
                val revenue = line.unitPrice * line.quantity
                val allocated = line.allocations.sumOf { it.quantity }
                if (allocated <= 0) continue
                val cost = line.allocations.fold(Money.ZERO) { acc, a ->
                    acc + a.unitCost * a.quantity
                }
                profit += revenue - cost
                knownRevenue += revenue
            }
        }
        return profit to knownRevenue
    }

    /** Total over the same-length window immediately before [range]. */
    fun previousWindowTotal(
        sales: List<Sale>,
        range: SalesRange,
        today: LocalDate,
    ): Money? {
        if (range == SalesRange.LAST_1H) return null
        val start = SalesRanges.startDate(range, today)
        val end = SalesRanges.endDate(range, today)
        val lengthDays = java.time.temporal.ChronoUnit.DAYS.between(start, end) + 1
        val prevEnd = start.minusDays(1)
        val prevStart = prevEnd.minusDays(lengthDays - 1)
        return sales.filter { sale ->
            val date = sale.soldAt.atZone(DhakaTime.ZONE).toLocalDate()
            !date.isBefore(prevStart) && !date.isAfter(prevEnd)
        }.fold(Money.ZERO) { acc, sale -> acc + sale.total }
    }

    private fun paymentSlices(sales: List<Sale>, total: Money): List<PaymentSlice> {
        if (total.paisa <= 0) return emptyList()
        val byMethod = sales.groupBy { it.paymentMethod }
            .mapValues { (_, list) -> list.fold(Money.ZERO) { acc, s -> acc + s.total } }
            .filterValues { !it.isZero }
        if (byMethod.isEmpty()) return emptyList()
        // Largest-remainder rounding so the displayed % always sums to 100.
        val exact = byMethod.mapValues { (_, amount) -> amount.paisa * 100.0 / total.paisa }
        val floors = exact.mapValues { (_, pct) -> pct.toInt() }.toMutableMap()
        var remainder = 100 - floors.values.sum()
        val byFraction = exact.entries.sortedByDescending { it.value - it.value.toInt() }
        for (entry in byFraction) {
            if (remainder <= 0) break
            floors[entry.key] = floors.getValue(entry.key) + 1
            remainder--
        }
        return byMethod.entries
            .sortedByDescending { it.value.paisa }
            .map { (method, amount) -> PaymentSlice(method, amount, floors.getValue(method)) }
    }

    private fun slowMovers(
        sales: List<Sale>,
        batches: List<Batch>,
        medicines: List<Medicine>,
    ): List<SlowMover> {
        val soldIds = sales.flatMap { it.lines }.map { it.medicineId }.toSet()
        val byId = medicines.associateBy { it.id }
        return batches.groupBy { it.medicineId }
            .filter { (id, _) -> id !in soldIds }
            .mapNotNull { (id, own) ->
                val units = own.sumOf { it.quantityAvailable }
                if (units <= 0) return@mapNotNull null
                val medicine = byId[id]
                SlowMover(
                    medicineId = id,
                    name = medicine?.displayName ?: own.firstOrNull()?.medicineName.orEmpty(),
                    unitsOnHand = units,
                    valueOnHand = own.fold(Money.ZERO) { acc, b -> acc + b.stockValue },
                )
            }
            .sortedByDescending { it.valueOnHand.paisa }
            .take(10)
    }
}
