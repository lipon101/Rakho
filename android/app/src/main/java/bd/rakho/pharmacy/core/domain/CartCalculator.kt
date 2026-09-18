package bd.rakho.pharmacy.core.domain

import bd.rakho.pharmacy.core.model.CartLine
import bd.rakho.pharmacy.core.money.Money
import bd.rakho.pharmacy.core.money.MoneyFormat

data class CartTotals(
    val subtotal: Money,
    val discount: Money,
    val total: Money,
)

object CartCalculator {

    fun lineTotal(line: CartLine): Money = line.unitPrice * line.quantity

    fun subtotal(lines: List<CartLine>): Money =
        lines.fold(Money.ZERO) { acc, line -> acc + lineTotal(line) }

    /**
     * A sale can carry either an absolute discount or a percentage; the applied
     * discount is capped at the subtotal so a total can never go negative.
     */
    fun totals(
        lines: List<CartLine>,
        discountAmount: Money = Money.ZERO,
        discountPercent: Int = 0,
    ): CartTotals {
        val sub = subtotal(lines)
        val fromPercent = MoneyFormat.percentOf(sub, discountPercent)
        val discount = (discountAmount + fromPercent).coerceAtMost(sub)
        return CartTotals(subtotal = sub, discount = discount, total = sub - discount)
    }

    fun itemCount(lines: List<CartLine>): Int = lines.sumOf { it.quantity }

    /** Cash returned to the customer; never negative. */
    fun changeDue(total: Money, received: Money): Money =
        (received - total).coerceAtLeast(Money.ZERO)

    /** The part of the bill a customer still owes when paying partly in cash. */
    fun creditRemainder(total: Money, received: Money): Money =
        (total - received).coerceAtLeast(Money.ZERO)
}
