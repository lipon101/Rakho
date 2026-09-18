package com.lipon.rakho.data.repo

import com.lipon.rakho.core.model.CustomerDue
import com.lipon.rakho.core.model.DuesSummary
import com.lipon.rakho.core.money.Money
import com.lipon.rakho.data.local.LocalCache
import com.lipon.rakho.data.session.SessionStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.map
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json
import java.util.UUID

/**
 * The baki (credit) book.
 *
 * Bangladesh pharmacies run largely on credit: a regular customer takes
 * medicine now and pays later. Rakho records the due at sale time, keeps it
 * on a per-customer ledger, and marks it settled the moment money arrives —
 * fully offline, because baki happens at the counter, not in a datacentre.
 *
 * Entries live only on the device ([LocalCache.KEY_LOCAL_DUES]) by design:
 * a credit book is private commercial data, and nothing is lost — the same
 * device keeps it across syncs. Payment is recorded as one settlement entry
 * so the history ("paid 200 of 500") stays visible.
 */
class DuesRepository(
    private val cache: LocalCache,
    private val json: Json,
) {
    @Serializable
    private data class DueEntryDto(
        val id: String,
        val customer: String,
        @SerialName("invoice_number") val invoiceNumber: String,
        /** Positive = money owed (credit sale), negative = payment received. */
        val amountPaisa: Long,
        @SerialName("created_at") val createdAtMillis: Long,
        val note: String = "",
    )

    private val listSerializer = ListSerializer(DueEntryDto.serializer())
    private val _revision = MutableStateFlow(0L)
    val revision: StateFlow<Long> = _revision.asStateFlow()

    private fun bump() {
        _revision.value = _revision.value + 1
    }

    private suspend fun readEntries(): List<DueEntryDto> =
        cache.read(LocalCache.KEY_LOCAL_DUES) { json.decodeFromString(listSerializer, it) }
            .orEmpty()

    private suspend fun writeEntries(entries: List<DueEntryDto>) {
        cache.write(LocalCache.KEY_LOCAL_DUES, entries) { json.encodeToString(listSerializer, it) }
        bump()
    }

    /**
     * Records a credit sale as a new due. Called by [SalesRepository] when a
     * sale is booked with payment method CREDIT.
     */
    suspend fun recordDue(
        customer: String,
        invoiceNumber: String,
        amount: Money,
        note: String,
    ) {
        if (amount.isZero) return
        writeEntries(
            readEntries() + DueEntryDto(
                id = UUID.randomUUID().toString(),
                customer = sanitizeCustomer(customer),
                invoiceNumber = invoiceNumber,
                amountPaisa = amount.paisa,
                createdAtMillis = System.currentTimeMillis(),
                note = note,
            ),
        )
    }

    /**
     * Records a payment against a customer's dues. Settlements are entered
     * per customer (how shopkeepers actually work: "Kamal bhai paid 500"),
     * and are applied oldest-due-first so nothing goes stale silently.
     */
    suspend fun settle(customer: String, amount: Money, note: String = "") {
        require(!amount.isZero) { "Payment amount must not be zero" }
        writeEntries(
            readEntries() + DueEntryDto(
                id = UUID.randomUUID().toString(),
                customer = sanitizeCustomer(customer),
                invoiceNumber = "",
                amountPaisa = -amount.paisa,
                createdAtMillis = System.currentTimeMillis(),
                note = note.ifBlank { "payment" },
            ),
        )
    }

    /** Removes a wrongly-entered entry (only same-day corrections are shown). */
    suspend fun removeEntry(entryId: String) {
        writeEntries(readEntries().filterNot { it.id == entryId })
    }

    /** Who owes what, oldest due first. */
    fun observeDues(): Flow<DuesSummary> = combine(cache.revision, _revision) { _, _ -> }
        .map { computeSummary() }

    /** One-shot read for widgets and reports. */
    suspend fun duesSummary(): DuesSummary = computeSummary()

    private suspend fun computeSummary(): DuesSummary {
        val entries = readEntries()
        val byCustomer = entries.groupBy { it.customer }
        val now = System.currentTimeMillis()
        val day = 86_400_000L
        val customers = byCustomer.map { (name, list) ->
            val balance = list.sumOf { it.amountPaisa }
            val oldest = list.minOf { it.createdAtMillis }
            // One ledger row per customer: the running balance and the
            // oldest unpaid item define who to chase first.
            CustomerDue(
                customer = name,
                invoiceNumber = list.lastOrNull { it.amountPaisa > 0 }?.invoiceNumber.orEmpty(),
                amount = Money(balance),
                dueSinceMillis = oldest,
                note = list.lastOrNull()?.note.orEmpty(),
            )
        }
        var over30 = Money.ZERO
        var mid = Money.ZERO
        var fresh = Money.ZERO
        customers.filter { it.amount.paisa > 0 }.forEach { due ->
            val ageDays = (now - due.dueSinceMillis) / day
            when {
                ageDays >= 30 -> over30 += due.amount
                ageDays >= 8 -> mid += due.amount
                else -> fresh += due.amount
            }
        }
        return DuesSummary(
            total = Money(customers.filter { it.amount.paisa > 0 }.sumOf { it.amount.paisa }),
            customerCount = customers.count { it.amount.paisa > 0 },
            entries = customers.filter { it.amount.paisa != 0L }.sortedBy { it.dueSinceMillis },
            agingOver30 = over30,
            agingMid = mid,
            agingFresh = fresh,
        )
    }

    private fun sanitizeCustomer(raw: String): String =
        raw.trim().replace(Regex("\\s+"), " ").take(60).ifBlank { "Unknown" }
}
