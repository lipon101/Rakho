package bd.rakho.pharmacy.core

import bd.rakho.pharmacy.core.money.Money
import bd.rakho.pharmacy.core.money.MoneyFormat
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.math.BigDecimal

class MoneyTest {

    @Test
    fun `adds and multiplies without floating point drift`() {
        val price = Money.parse("2.50")
        assertEquals(Money.parse("25.00"), price * 10)
        assertEquals(Money.parse("5.00"), price + price)
    }

    @Test
    fun `parses every shape the API and the keyboard produce`() {
        assertEquals(Money.of(12), Money.parse("12"))
        assertEquals(Money.of(12, 50), Money.parse("12.50"))
        assertEquals(Money.of(1234, 50), Money.parse("1,234.5"))
        assertEquals(Money.of(0), Money.parse(""))
        assertEquals(Money.of(0), Money.parse(null))
        assertEquals(Money.of(0), Money.parse("৳"))
        assertEquals(Money.of(0), Money.parse("abc"))
        // A Bangla keyboard emits Bangla digits; they must parse as the same
        // amount, not silently become zero.
        assertEquals(Money.of(123), Money.parse("১২৩"))
        assertEquals(Money.of(12, 50), Money.parse("১২.৫"))
    }

    @Test
    fun `formats with lakh style grouping used on Bangladeshi receipts`() {
        assertEquals("৳12,34,567.00", MoneyFormat.format(Money.of(1234567)))
        assertEquals("৳1,234.50", MoneyFormat.format(Money.parse("1234.5")))
        assertEquals("৳999.00", MoneyFormat.format(Money.of(999)))
        assertEquals("৳12,34,567", MoneyFormat.format(Money.of(1234567), withDecimals = false))
    }

    @Test
    fun `formats negatives with a leading sign`() {
        assertEquals("-৳5.00", MoneyFormat.format(Money.of(-5)))
    }

    @Test
    fun `never splits a taka into more than 100 paisa`() {
        val value = Money.parse("0.99")
        assertEquals(99, value.paisa)
        assertFalse(value.isNegative)
        assertTrue(Money.ZERO.isZero)
    }

    @Test
    fun `rounds half up when applying a percentage`() {
        // 10% of ৳12.35 is ৳1.235 -> ৳1.24
        assertEquals(Money.parse("1.24"), MoneyFormat.percentOf(Money.parse("12.35"), 10))
    }

    @Test
    fun `decimal conversion round-trips`() {
        val money = Money.ofDecimal(BigDecimal("3499.99"))
        assertEquals("3499.99", money.toBigDecimal().toPlainString())
    }
}
