package bd.rakho.pharmacy.core.time

import java.time.Clock
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.format.DateTimeParseException
import java.time.temporal.ChronoUnit

/** Pharmacy business dates always follow Dhaka time, never the device's zone. */
object DhakaTime {

    val ZONE: ZoneId = ZoneId.of("Asia/Dhaka")

    private val displayFormatter: DateTimeFormatter = DateTimeFormatter.ofPattern("dd MMM yyyy")
    private val shortFormatter: DateTimeFormatter = DateTimeFormatter.ofPattern("dd MMM")

    fun today(clock: Clock = Clock.system(ZONE)): LocalDate = LocalDate.now(clock)

    fun now(clock: Clock = Clock.system(ZONE)): Instant = clock.instant()

    fun format(date: LocalDate): String = date.format(displayFormatter)

    fun formatShort(date: LocalDate): String = date.format(shortFormatter)

    fun parseDate(raw: String?): LocalDate? {
        if (raw.isNullOrBlank()) return null
        return try {
            LocalDate.parse(raw.take(10))
        } catch (_: DateTimeParseException) {
            null
        }
    }
}

/** How a batch's expiry reads to a pharmacist. */
enum class ExpiryStatus { EXPIRED, EXPIRES_TODAY, EXPIRING_SOON, HEALTHY }

object ExpiryRules {

    /** Batches inside this window are surfaced on the expiry radar. */
    const val EXPIRING_SOON_DAYS: Long = 90

    fun daysUntil(expiry: LocalDate, today: LocalDate): Long =
        ChronoUnit.DAYS.between(today, expiry)

    fun status(expiry: LocalDate, today: LocalDate, soonDays: Long = EXPIRING_SOON_DAYS): ExpiryStatus {
        val days = daysUntil(expiry, today)
        return when {
            days < 0 -> ExpiryStatus.EXPIRED
            days == 0L -> ExpiryStatus.EXPIRES_TODAY
            days <= soonDays -> ExpiryStatus.EXPIRING_SOON
            else -> ExpiryStatus.HEALTHY
        }
    }

    /** FEFO may only allocate stock that has not expired. */
    fun isSellable(expiry: LocalDate, today: LocalDate): Boolean = expiry >= today
}
