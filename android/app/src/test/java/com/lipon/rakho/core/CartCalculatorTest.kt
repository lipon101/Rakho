package com.lipon.rakho.core

import com.lipon.rakho.core.domain.CartCalculator
import com.lipon.rakho.core.model.BatchAllocation
import com.lipon.rakho.core.model.CartLine
import com.lipon.rakho.core.money.Money
import org.junit.Assert.assertEquals
import org.junit.Test
import java.time.LocalDate

class CartCalculatorTest {

    private fun line(name: String, price: String, quantity: Int) = CartLine(
        medicineId = name,
        medicineName = name,
        unitPrice = Money.parse(price),
        quantity = quantity,
        allocations = listOf(
            BatchAllocation(
                batchId = "$name-b1",
                batchNumber = "B1",
                expiryDate = LocalDate.of(2027, 1, 1),
                quantity = quantity,
            ),
        ),
    )

    @Test
    fun `sums line totals from price times quantity`() {
        val lines = listOf(line("Napa", "2.50", 4), line("Seclo", "12.00", 2))
        assertEquals(Money.parse("34.00"), CartCalculator.subtotal(lines))
    }

    @Test
    fun `percentage discount and fixed discount are combined`() {
        val lines = listOf(line("Napa", "100.00", 2))
        val totals = CartCalculator.totals(
            lines,
            discountAmount = Money.parse("20.00"),
            discountPercent = 10,
        )
        assertEquals(Money.parse("200.00"), totals.subtotal)
        assertEquals(Money.parse("40.00"), totals.discount)
        assertEquals(Money.parse("160.00"), totals.total)
    }

    @Test
    fun `discount can never push the total below zero`() {
        val lines = listOf(line("Napa", "50.00", 1))
        val totals = CartCalculator.totals(
            lines,
            discountAmount = Money.parse("9999.00"),
            discountPercent = 100,
        )
        assertEquals(Money.parse("50.00"), totals.discount)
        assertEquals(Money.ZERO, totals.total)
    }

    @Test
    fun `change due is clamped at zero and credit is what is still owed`() {
        val total = Money.parse("250.00")
        assertEquals(Money.parse("50.00"), CartCalculator.changeDue(total, Money.parse("300.00")))
        assertEquals(Money.ZERO, CartCalculator.changeDue(total, Money.parse("100.00")))
        assertEquals(Money.parse("150.00"), CartCalculator.creditRemainder(total, Money.parse("100.00")))
    }

    @Test
    fun `counts every unit in the cart`() {
        val lines = listOf(line("Napa", "2.50", 4), line("Seclo", "12.00", 2))
        assertEquals(6, CartCalculator.itemCount(lines))
    }

    @Test
    fun `empty cart totals are zero`() {
        val totals = CartCalculator.totals(emptyList(), discountPercent = 15)
        assertEquals(Money.ZERO, totals.subtotal)
        assertEquals(Money.ZERO, totals.total)
    }
}
