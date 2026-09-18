package bd.rakho.pharmacy.core

import bd.rakho.pharmacy.core.time.DhakaTime
import bd.rakho.pharmacy.core.time.ExpiryRules
import bd.rakho.pharmacy.core.time.ExpiryStatus
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate

class ExpiryRulesTest {

    private val today = LocalDate.of(2026, 9, 18)

    @Test
    fun `yesterday is expired and today expires today`() {
        assertEquals(
            ExpiryStatus.EXPIRED,
            ExpiryRules.status(LocalDate.of(2026, 9, 17), today),
        )
        assertEquals(
            ExpiryStatus.EXPIRES_TODAY,
            ExpiryRules.status(today, today),
        )
    }

    @Test
    fun `the constant window decides expiring soon`() {
        val edge = today.plusDays(ExpiryRules.EXPIRING_SOON_DAYS)
        assertEquals(ExpiryStatus.EXPIRING_SOON, ExpiryRules.status(edge, today))
        assertEquals(
            ExpiryStatus.HEALTHY,
            ExpiryRules.status(edge.plusDays(1), today),
        )
    }

    @Test
    fun `only stock expiring today or later may be sold`() {
        assertFalse(ExpiryRules.isSellable(LocalDate.of(2026, 9, 17), today))
        assertTrue(ExpiryRules.isSellable(today, today))
    }

    @Test
    fun `days until expiry is negative for expired stock`() {
        assertEquals(-3L, ExpiryRules.daysUntil(LocalDate.of(2026, 9, 15), today))
        assertEquals(0L, ExpiryRules.daysUntil(today, today))
    }

    @Test
    fun `parses the ISO dates the API returns and rejects junk`() {
        assertEquals(LocalDate.of(2027, 3, 1), DhakaTime.parseDate("2027-03-01"))
        assertEquals(LocalDate.of(2027, 3, 1), DhakaTime.parseDate("2027-03-01T00:00:00Z"))
        assertNull(DhakaTime.parseDate(""))
        assertNull(DhakaTime.parseDate(null))
        assertNull(DhakaTime.parseDate("31-12-2027"))
    }

    @Test
    fun `business dates follow Dhaka time regardless of the device`() {
        assertEquals("Asia/Dhaka", DhakaTime.ZONE.id)
        assertEquals("01 Mar 2027", DhakaTime.format(LocalDate.of(2027, 3, 1)))
    }
}
