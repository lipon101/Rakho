package com.lipon.rakho.data.repo

import com.lipon.rakho.data.firebase.FirestoreCustomer
import com.lipon.rakho.data.firebase.FirestoreData
import com.lipon.rakho.data.firebase.FirestoreRepository
import kotlinx.coroutines.flow.StateFlow

/**
 * The customer phone book behind the baki reminders.
 *
 * Dues are keyed by customer *name* (the ledger is append-only and names are
 * what shopkeepers type), so the book maps a name to a phone number for
 * WhatsApp reminders rather than rewriting the ledger to reference ids.
 * One shared listener, like every other collection — free-quota discipline.
 */
class CustomersRepository(
    private val firestore: FirestoreRepository,
    private val data: FirestoreData,
) {

    val customers: StateFlow<List<FirestoreCustomer>> = data.customers

    suspend fun save(customerId: String?, name: String, phone: String, note: String = "") {
        val cleanName = sanitizeName(name)
        if (cleanName.isBlank()) return
        firestore.saveCustomer(
            customerId = customerId,
            name = cleanName,
            phone = sanitizePhone(phone),
            note = note.trim(),
        )
    }

    suspend fun delete(customerId: String) {
        firestore.deleteCustomer(customerId)
    }

    /** Phone for a ledger name, matched the same way dues sanitize it. */
    fun phoneFor(name: String): String {
        val target = sanitizeName(name)
        return data.customers.value.firstOrNull { sanitizeName(it.name) == target }?.phone.orEmpty()
    }

    /** True when the name is already in the book (case/space-insensitive). */
    fun knows(name: String): Boolean {
        val target = sanitizeName(name)
        return target.isNotBlank() &&
            data.customers.value.any { sanitizeName(it.name) == target }
    }

    /**
     * A first credit sale for a new name files them in the book immediately,
     * so the very first baki is never the one that cannot be reminded. They
     * can add the phone later from the Dues screen.
     */
    suspend fun ensureKnown(name: String) {
        val clean = sanitizeName(name)
        if (clean.isBlank() || knows(clean)) return
        firestore.saveCustomer(customerId = null, name = clean, phone = "", note = "")
    }

    private fun sanitizeName(raw: String): String =
        raw.trim().replace(Regex("\\s+"), " ").take(60)

    /** Digits, optional leading +, max 16 — anything else is not a phone. */
    private fun sanitizePhone(raw: String): String =
        raw.filter { it.isDigit() || it == '+' }.take(16)
}
