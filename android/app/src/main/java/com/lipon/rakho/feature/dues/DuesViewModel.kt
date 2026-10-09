package com.lipon.rakho.feature.dues

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.lipon.rakho.core.model.CustomerDue
import com.lipon.rakho.core.money.Money
import com.lipon.rakho.core.money.MoneyFormat
import com.lipon.rakho.data.firebase.FirestoreCustomer
import com.lipon.rakho.data.repo.CustomersRepository
import com.lipon.rakho.data.repo.DuesLedgerEntry
import com.lipon.rakho.data.repo.DuesRepository
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

sealed interface DuesMessage {
    data class Settled(val customer: String, val amount: Money) : DuesMessage
    data object EntryRemoved : DuesMessage
    data class Invalid(val reason: String) : DuesMessage
}

data class DuesUiState(
    val loading: Boolean = true,
    val total: Money = Money.ZERO,
    val customerCount: Int = 0,
    val customers: List<CustomerDue> = emptyList(),
    val message: DuesMessage? = null,
    /** Customer currently being settled (bottom sheet / dialog). */
    val settling: CustomerDue? = null,
    /** Customer whose ledger is being reviewed for a correction. */
    val reviewing: CustomerDue? = null,
    val ledger: List<DuesLedgerEntry> = emptyList(),
    /** Money bucketed by how long the oldest due has been outstanding. */
    val agingFresh: Money = Money.ZERO,
    val agingMid: Money = Money.ZERO,
    val agingOver30: Money = Money.ZERO,
    /** The cloud phone book that makes reminders possible. */
    val book: List<FirestoreCustomer> = emptyList(),
    val shopName: String = "",
) {
    val hasOverdue: Boolean get() = agingOver30.paisa > 0
}

/** Everything the reminder message needs, resolved the way the ledger sees it. */
data class BakiReminderDraft(
    val name: String,
    val phone: String,
    val amount: String,
    val days: Long,
)

/**
 * The baki (credit) book screen state.
 *
 * Deliberately simple: who owes, how much, since when — a one-tap "received
 * payment" flow, and a one-tap WhatsApp reminder for anything older than a
 * week, because chasing baki politely and on time is how shops keep money.
 */
class DuesViewModel(
    private val dues: DuesRepository,
    private val customers: CustomersRepository,
    sessionStore: com.lipon.rakho.data.session.SessionStore,
) : ViewModel() {

    private val message = MutableStateFlow<DuesMessage?>(null)
    private val settling = MutableStateFlow<CustomerDue?>(null)
    private val reviewing = MutableStateFlow<CustomerDue?>(null)
    private val ledger = MutableStateFlow<List<DuesLedgerEntry>>(emptyList())

    private val shopName = sessionStore.state.map { it.shopName }
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), "")

    val state: StateFlow<DuesUiState> = combine(
        dues.observeDues(),
        combine(message, settling) { msg, settle -> msg to settle },
        combine(reviewing, ledger) { review, entries -> review to entries },
        combine(customers.customers, shopName) { book, shop -> book to shop },
    ) { summary, (msg, settlingCustomer), (reviewingCustomer, entries), (book, shop) ->
        DuesUiState(
            loading = false,
            total = summary.total,
            customerCount = summary.customerCount,
            customers = summary.entries,
            message = msg,
            settling = settlingCustomer,
            reviewing = reviewingCustomer,
            ledger = entries,
            agingFresh = summary.agingFresh,
            agingMid = summary.agingMid,
            agingOver30 = summary.agingOver30,
            book = book,
            shopName = shop,
        )
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), DuesUiState())

    fun openSettle(customer: CustomerDue) {
        settling.value = customer
    }
    fun dismissSettle() {
        settling.value = null
    }

    /** Opens one customer's ledger so a wrong entry can be found and removed. */
    fun openLedger(customer: CustomerDue) {
        reviewing.value = customer
        viewModelScope.launch {
            ledger.value = dues.entriesFor(customer.customer)
        }
    }

    fun dismissLedger() {
        reviewing.value = null
        ledger.value = emptyList()
    }

    /** Removes a wrongly-entered ledger row; the summary recomputes instantly. */
    fun removeEntry(entryId: String) {
        val customer = reviewing.value ?: return
        viewModelScope.launch {
            dues.removeEntry(entryId)
            ledger.value = dues.entriesFor(customer.customer)
            message.value = DuesMessage.EntryRemoved
        }
    }

    fun consumeMessage() {
        message.value = null
    }

    /** Records a payment received from a customer, applied to their oldest dues. */
    fun settle(customer: CustomerDue, amount: Money) {
        if (amount.isZero || amount.isNegative) {
            message.value = DuesMessage.Invalid("enter an amount")
            return
        }
        viewModelScope.launch {
            dues.settle(customer.customer, amount)
            settling.value = null
            message.value = DuesMessage.Settled(customer.customer, amount)
        }
    }

    /** Adds or edits a phone-book entry; names are how the ledger keys them. */
    fun saveCustomer(customerId: String?, name: String, phone: String) {
        if (name.isBlank()) return
        viewModelScope.launch { customers.save(customerId, name, phone) }
    }

    /** The book's number for a ledger name, "" when unknown. */
    fun phoneFor(name: String): String = customers.phoneFor(name)

    fun deleteCustomer(customerId: String) {
        viewModelScope.launch { customers.delete(customerId) }
    }

    /**
     * The reminder payload for one debtor. Days outstanding are computed the
     * same way the aging buckets do it, so the message can never disagree
     * with what the screen shows.
     */
    fun reminderDraft(due: CustomerDue): BakiReminderDraft {
        val days = (System.currentTimeMillis() - due.dueSinceMillis) / 86_400_000L
        return BakiReminderDraft(
            name = due.customer,
            phone = customers.phoneFor(due.customer),
            amount = MoneyFormat.format(due.amount),
            days = days.coerceAtLeast(1L),
        )
    }
}
