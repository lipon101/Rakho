package com.lipon.rakho.data.repo

import com.lipon.rakho.core.model.CustomerDue
import com.lipon.rakho.core.model.DuesSummary
import com.lipon.rakho.core.money.Money
import com.lipon.rakho.data.firebase.FirestoreData
import com.lipon.rakho.data.firebase.FirestoreDueEntry
import com.lipon.rakho.data.firebase.FirestoreRepository
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

/** One row of a customer's credit ledger: a credit sale (+) or a payment (−). */
data class DuesLedgerEntry(
    val id: String,
    val amount: Money,
    val createdAtMillis: Long,
    val invoiceNumber: String,
    val note: String,
)

/**
 * The baki (credit) book, now in the cloud.
 *
 * Bangladesh pharmacies run largely on credit: a regular customer takes
 * medicine now and pays later. Rakho records the due at sale time (booked by
 * [SalesRepository] in the same write as the sale itself), keeps it on a
 * per-customer ledger, and marks it settled the moment money arrives.
 *
 * Entries live in Firestore under the pharmacy, so the book survives a lost
 * phone and is readable from a second device. The ledger stays append-only —
 * payments are negative entries, never edits — so "paid 200 of 500" history
 * stays visible. Summaries are derived on device from the shared dues flow:
 * one listener, no per-screen reads.
 */
class DuesRepository(
    private val firestore: FirestoreRepository,
    private val data: FirestoreData,
) {

    /**
     * Records a standalone due. Credit sales book their own due inside
     * [SalesRepository.recordSale]; this is for manual entries the shopkeeper
     * adds for old baki that predates Rakho.
     */
    suspend fun recordDue(customer: String, invoiceNumber: String, amount: Money, note: String) {
        if (amount.isZero) return
        firestore.addDueEntry(
            customer = sanitizeCustomer(customer),
            invoiceNumber = invoiceNumber,
            amountPaisa = amount.paisa,
            note = note,
        )
    }

    /**
     * Records a payment against a customer's dues. Settlements are entered
     * per customer (how shopkeepers actually work: "Kamal bhai paid 500"),
     * and reduce the oldest dues first when the summary is computed.
     */
    suspend fun settle(customer: String, amount: Money, note: String = "") {
        require(!amount.isZero) { "Payment amount must not be zero" }
        firestore.settleDue(
            customer = sanitizeCustomer(customer),
            amountPaisa = amount.paisa,
            note = note,
        )
    }

    /** Removes a wrongly-entered entry (only same-day corrections are shown). */
    suspend fun removeEntry(entryId: String) {
        firestore.removeDueEntry(entryId)
    }

    /** One customer's ledger, newest first. */
    suspend fun entriesFor(customer: String): List<DuesLedgerEntry> =
        data.dues.value
            .filter { it.customer == sanitizeCustomer(customer) }
            .sortedByDescending { it.createdAt }
            .map {
                DuesLedgerEntry(
                    id = it.id,
                    amount = Money(it.amountPaisa),
                    createdAtMillis = it.createdAt,
                    invoiceNumber = it.invoiceNumber,
                    note = it.note,
                )
            }

    /** Who owes what, oldest due first. */
    fun observeDues(): Flow<DuesSummary> = data.dues.map { computeSummary(it) }

    /** One-shot read for widgets and reports. */
    suspend fun duesSummary(): DuesSummary = computeSummary(data.dues.value)

    /**
     * Summary over a caller-supplied snapshot — used by the daily reminder
     * worker, which reads the ledger once without keeping a UI listener alive.
     */
    fun summarize(entries: List<FirestoreDueEntry>): DuesSummary = computeSummary(entries)

    private fun computeSummary(entries: List<FirestoreDueEntry>): DuesSummary {
        val byCustomer = entries.groupBy { sanitizeCustomer(it.customer) }
        val now = System.currentTimeMillis()
        val day = 86_400_000L
        val customers = byCustomer.map { (name, list) ->
            val balance = list.sumOf { it.amountPaisa }
            val oldest = list.minOf { it.createdAt }
            // One ledger row per customer: the running balance and the
            // oldest unpaid item define who to chase first.
            CustomerDue(
                customer = name,
                invoiceNumber = list.lastOrNull { it.amountPaisa > 0 }?.invoiceNumber.orEmpty(),
                amount = Money(balance),
                dueSinceMillis = oldest,
                note = list.maxByOrNull { it.createdAt }?.note.orEmpty(),
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
