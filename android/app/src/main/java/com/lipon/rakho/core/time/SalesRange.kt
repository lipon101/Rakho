package com.lipon.rakho.core.time

import com.lipon.rakho.core.model.DayTotal
import com.lipon.rakho.core.model.Sale
import com.lipon.rakho.core.money.Money
import java.time.LocalDate

/**
 * Minimal, premium sales ranges: last hour, last day, last week, last month,
 * last year. Every boundary is a Dhaka calendar boundary — a shopkeeper's
 * "day" starts at midnight in Dhaka. All money sums stay in paisa-exact
 * [Money] arithmetic; nothing is rounded for display until [MoneyFormat].
 */
enum class SalesRange {
    LAST_1H,
    LAST_24H,
    LAST_7D,
    LAST_30D,
    LAST_1Y,
}

/**
 * One chart bucket: a label ("2 PM", "12 Oct", "Mar") and its exact total.
 * Short ranges use small buckets; long ranges roll days up into weeks and
 * months so every range draws a readable chart. Hourly labels use the
 * 12-hour clock Bangladesh shops run on (10 AM, 3 PM — never 15:00).
 */
data class SalesBucket(
    val label: String,
    val total: Money,
    /** The newest bucket — drawn solid while older buckets stay tinted. */
    val highlighted: Boolean = false,
)

object SalesRanges {

    /** Start (inclusive) of [range] measured back from Dhaka [today]. */
    fun startDate(range: SalesRange, today: LocalDate): LocalDate = when (range) {
        SalesRange.LAST_1H, SalesRange.LAST_24H -> today
        SalesRange.LAST_7D -> today.minusDays(6)
        SalesRange.LAST_30D -> today.minusDays(29)
        SalesRange.LAST_1Y -> today.minusDays(364)
    }

    /** End (inclusive) of [range]: always today — every range ends now. */
    fun endDate(range: SalesRange, today: LocalDate): LocalDate = today

    /** Sales inside [range], in ledger order. One predicate, used by KPIs, mix, top-sellers and CSV alike. */
    fun filterForRange(sales: List<Sale>, range: SalesRange, today: LocalDate): List<Sale> {
        if (range == SalesRange.LAST_1H) {
            // Last 60 minutes exactly — the only sub-day range, so it cuts by
            // clock, not by calendar day, and always agrees with its buckets.
            val cutoff = DhakaTime.now().minusSeconds(3600)
            return sales.filter { !it.soldAt.isBefore(cutoff) }
        }
        val start = startDate(range, today)
        val end = endDate(range, today)
        return sales.filter { sale ->
            val date = sale.soldAt.atZone(DhakaTime.ZONE).toLocalDate()
            !date.isBefore(start) && !date.isAfter(end)
        }
    }

    /**
     * Buckets for the chart, oldest first, each labelled for its span:
     * 1H → last 60 minutes ("2:45 PM"), 24H → 24 hourly buckets ("2 PM"),
     * 7D/30D → daily ("12 Oct"), 1Y → monthly ("Mar").
     */
    fun buckets(sales: List<Sale>, range: SalesRange, today: LocalDate): List<SalesBucket> {
        val inRange = filterForRange(sales, range, today)
        return when (range) {
            SalesRange.LAST_1H -> minuteBuckets(inRange)
            SalesRange.LAST_24H -> hourlyBuckets(inRange)
            SalesRange.LAST_7D, SalesRange.LAST_30D ->
                dailyBuckets(inRange, startDate(range, today), endDate(range, today))
            SalesRange.LAST_1Y ->
                monthlyBuckets(inRange, startDate(range, today), endDate(range, today))
        }
    }

    /** Day totals across [range], oldest first — the dashboard's week-ready cousin. */
    fun dayTotals(sales: List<Sale>, range: SalesRange, today: LocalDate): List<DayTotal> {
        val byDay = filterForRange(sales, range, today)
            .groupBy { it.soldAt.atZone(DhakaTime.ZONE).toLocalDate() }
        val start = startDate(range, today)
        val end = endDate(range, today)
        val days = ArrayList<DayTotal>()
        var date = start
        while (!date.isAfter(end)) {
            val total = (byDay[date] ?: emptyList())
                .fold(Money.ZERO) { acc, sale -> acc + sale.total }
            days += DayTotal(date = date, total = total)
            date = date.plusDays(1)
        }
        return days
    }

    /** 12-hour clock the way Bangladeshi shops say it: 9 AM, 3 PM. */
    fun hourLabel(hour24: Int): String {
        val hour12 = when (hour24 % 12) {
            0 -> 12
            else -> hour24 % 12
        }
        val suffix = if (hour24 < 12) "AM" else "PM"
        return "$hour12 $suffix"
    }

    /**
     * Smart axis label: short clock hours without AM/PM noise on the hourly
     * view ("9", "3" with the meridiem only where the day flips), relative
     * day words on daily views ("Today", weekday), slim months on yearly.
     * Reads instantly in a shop — no mental 24h conversion, no clutter.
     */
    fun smartAxisLabel(raw: String, range: SalesRange): String {
        if (raw.isBlank() || raw == "Now" || raw == "Today") return raw
        return when (range) {
            SalesRange.LAST_24H -> {
                // "9 PM" → "9": the curve's own rhythm carries the meaning,
                // and the day-flip hour keeps its suffix ("12 AM").
                val parts = raw.trim().split(" ")
                if (parts.size == 2) {
                    val hour = parts[0].toIntOrNull() ?: return raw
                    val suffix = parts[1].uppercase()
                    if (hour == 12 && suffix == "AM") "12 AM" else hour.toString()
                } else {
                    raw
                }
            }
            SalesRange.LAST_7D, SalesRange.LAST_30D -> {
                // "10 Sep" → weekday when it is recent ("Mon"), date otherwise.
                runCatching {
                    val parsed = java.time.format.DateTimeFormatter
                        .ofPattern("dd MMM")
                        .withLocale(java.util.Locale.ENGLISH)
                        .parse(raw)
                    val monthDay = java.time.MonthDay.from(parsed)
                    val today = DhakaTime.today()
                    val year = if (monthDay.monthValue > today.monthValue) {
                        today.year - 1
                    } else {
                        today.year
                    }
                    val date = monthDay.atYear(year)
                    val daysAgo = java.time.temporal.ChronoUnit.DAYS
                        .between(date, today).toInt()
                    if (daysAgo in 1..6) {
                        date.dayOfWeek.getDisplayName(
                            java.time.format.TextStyle.SHORT,
                            java.util.Locale.ENGLISH,
                        )
                    } else {
                        raw
                    }
                }.getOrDefault(raw)
            }
            else -> raw
        }
    }

    /** Last 60 minutes in 6 buckets — labels stay empty except "Now". */
    private fun minuteBuckets(sales: List<Sale>): List<SalesBucket> {
        val zone = DhakaTime.ZONE
        val now = DhakaTime.now().atZone(zone)
        val byMinute = sales.groupBy {
            val zoned = it.soldAt.atZone(zone)
            java.time.temporal.ChronoUnit.MINUTES.between(zoned, now).coerceAtLeast(0) / 10
        }
        return (5 downTo 0).map { back ->
            val total = (byMinute[back.toLong()] ?: emptyList())
                .fold(Money.ZERO) { acc, sale -> acc + sale.total }
            SalesBucket(
                label = if (back == 0) "Now" else "",
                total = total,
                highlighted = back == 0,
            )
        }
    }

    /** Hourly buckets for the last 24h — only 4 slim labels: start, 2 middles, now. */
    private fun hourlyBuckets(sales: List<Sale>): List<SalesBucket> {
        val zone = DhakaTime.ZONE
        // "Last 24 hours" always draws today's hourly shape: every sale in the
        // filter is today's, so grouping by hour-of-day keeps buckets and the
        // range total in exact agreement on every device clock.
        val byHour = sales.groupBy { it.soldAt.atZone(zone).hour }
        val nowHour = DhakaTime.now().atZone(zone).hour
        return (23 downTo 0).map { back ->
            val hour = (nowHour - back + 48) % 24
            val total = (byHour[hour] ?: emptyList())
                .fold(Money.ZERO) { acc, sale -> acc + sale.total }
            val label = when (back) {
                0 -> "Now"
                23 -> hourLabel(hour)
                15, 7 -> hourLabel(hour)
                else -> ""
            }
            SalesBucket(
                label = label,
                total = total,
                highlighted = back == 0,
            )
        }
    }

    /** One bucket per Dhaka day — only first, middle(s) and "Today" labelled. */
    private fun dailyBuckets(sales: List<Sale>, start: LocalDate, end: LocalDate): List<SalesBucket> {
        val byDay = sales.groupBy { it.soldAt.atZone(DhakaTime.ZONE).toLocalDate() }
        val buckets = ArrayList<SalesBucket>()
        var date = start
        var index = 0
        // Count first so middles land evenly on any span (7 or 30 days).
        var span = 0
        var cursor = start
        while (!cursor.isAfter(end)) {
            span++
            cursor = cursor.plusDays(1)
        }
        while (!date.isAfter(end)) {
            val total = (byDay[date] ?: emptyList())
                .fold(Money.ZERO) { acc, sale -> acc + sale.total }
            val label = when {
                date == end -> "Today"
                index == 0 -> DhakaTime.formatShort(date)
                span > 10 && index == span / 2 -> DhakaTime.formatShort(date)
                span <= 10 && index % 2 == 0 -> DhakaTime.formatShort(date)
                else -> ""
            }
            buckets += SalesBucket(
                label = label,
                total = total,
                highlighted = date == end,
            )
            date = date.plusDays(1)
            index++
        }
        return buckets
    }

    private val monthFormatter: java.time.format.DateTimeFormatter =
        java.time.format.DateTimeFormatter.ofPattern("MMM")

    /** One bucket per calendar month — first, middle and current month only. */
    private fun monthlyBuckets(sales: List<Sale>, start: LocalDate, end: LocalDate): List<SalesBucket> {
        val byMonth = sales.groupBy {
            val date = it.soldAt.atZone(DhakaTime.ZONE).toLocalDate()
            date.year * 12 + date.monthValue
        }
        val buckets = ArrayList<SalesBucket>()
        var cursor = LocalDate.of(start.year, start.monthValue, 1)
        val last = LocalDate.of(end.year, end.monthValue, 1)
        var months = 0
        var probe = cursor
        while (!probe.isAfter(last)) {
            months++
            probe = probe.plusMonths(1)
        }
        var index = 0
        while (!cursor.isAfter(last)) {
            val key = cursor.year * 12 + cursor.monthValue
            val total = (byMonth[key] ?: emptyList())
                .fold(Money.ZERO) { acc, sale -> acc + sale.total }
            val label = when {
                cursor == last -> "Now"
                index == 0 -> cursor.format(monthFormatter)
                index == months / 2 -> cursor.format(monthFormatter)
                else -> ""
            }
            buckets += SalesBucket(
                label = label,
                total = total,
                highlighted = cursor == last,
            )
            cursor = cursor.plusMonths(1)
            index++
        }
        return buckets
    }
}
