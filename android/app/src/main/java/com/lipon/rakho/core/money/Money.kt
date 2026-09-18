package com.lipon.rakho.core.money

import java.math.BigDecimal
import java.math.RoundingMode

/**
 * BDT money stored as integer paisa (1 taka = 100 paisa).
 *
 * Pharmacy prices carry two decimals (৳2.50), and totals must never drift, so
 * every amount is kept in minor units and all arithmetic is integer/decimal —
 * never floating point.
 */
@JvmInline
value class Money(val paisa: Long) : Comparable<Money> {

    operator fun plus(other: Money): Money = Money(paisa + other.paisa)

    operator fun minus(other: Money): Money = Money(paisa - other.paisa)

    operator fun times(quantity: Int): Money = Money(paisa * quantity)

    operator fun times(quantity: Long): Money = Money(paisa * quantity)

    /** Multiply by a ratio (discounts, tax) rounding half-up to the nearest paisa. */
    fun timesRatio(ratio: BigDecimal): Money =
        Money(
            BigDecimal(paisa).multiply(ratio).setScale(0, RoundingMode.HALF_UP).toLong(),
        )

    fun abs(): Money = Money(if (paisa < 0) -paisa else paisa)

    fun coerceAtLeast(minimum: Money): Money = if (paisa < minimum.paisa) minimum else this

    fun coerceAtMost(maximum: Money): Money = if (paisa > maximum.paisa) maximum else this

    val isZero: Boolean get() = paisa == 0L
    val isNegative: Boolean get() = paisa < 0L

    fun toBigDecimal(): BigDecimal = BigDecimal(paisa).movePointLeft(2)

    override fun compareTo(other: Money): Int = paisa.compareTo(other.paisa)

    companion object {
        val ZERO: Money = Money(0)

        fun of(taka: Long, paisa: Long = 0): Money = Money(taka * 100 + paisa)

        fun ofDecimal(value: BigDecimal): Money =
            Money(value.movePointRight(2).setScale(0, RoundingMode.HALF_UP).toLong())

        /**
         * Parses values coming from the API or user input: "2.00", "1,234.5",
         * "12", "৳12.50", null/blank (-> zero). Never throws.
         */
        fun parse(raw: String?): Money {
            if (raw.isNullOrBlank()) return ZERO
            val cleaned = raw.filter { it.isDigit() || it == '.' || it == '-' }
            if (cleaned.isBlank() || cleaned == "-" || cleaned == ".") return ZERO
            return try {
                ofDecimal(BigDecimal(cleaned))
            } catch (_: NumberFormatException) {
                ZERO
            }
        }
    }
}

/**
 * Formats money the way Bangladeshi receipts do: lakh/crore digit grouping
 * (12,34,567.00) with two decimals and the taka sign.
 */
object MoneyFormat {

    const val TAKA_SIGN = "৳"

    fun format(money: Money, withDecimals: Boolean = true, symbol: String = TAKA_SIGN): String {
        val negative = money.isNegative
        val absolute = money.abs().paisa
        val taka = absolute / 100
        val paisa = absolute % 100
        val grouped = groupLakhStyle(taka.toString())
        val decimals = if (withDecimals) "." + paisa.toString().padStart(2, '0') else ""
        return buildString {
            if (negative) append('-')
            if (symbol.isNotEmpty()) append(symbol)
            append(grouped)
            append(decimals)
        }
    }

    /** 1234567 -> 12,34,567 (last three digits, then pairs). */
    fun groupLakhStyle(digits: String): String {
        if (digits.length <= 3) return digits
        val head = digits.dropLast(3)
        val tail = digits.takeLast(3)
        val groupedHead = head.reversed().chunked(2).joinToString(",").reversed()
        return "$groupedHead,$tail"
    }

    /** Percentage helper that never exceeds 100%. */
    fun percentOf(money: Money, percent: Int): Money {
        val safePercent = percent.coerceIn(0, 100)
        if (safePercent == 0) return Money.ZERO
        return money.timesRatio(BigDecimal(safePercent).divide(BigDecimal(100)))
    }
}
