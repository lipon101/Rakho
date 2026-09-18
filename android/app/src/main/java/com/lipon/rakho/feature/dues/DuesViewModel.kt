package com.lipon.rakho.feature.dues

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.lipon.rakho.core.model.CustomerDue
import com.lipon.rakho.core.money.Money
import com.lipon.rakho.data.repo.DuesRepository
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

sealed interface DuesMessage {
    data class Settled(val customer: String, val amount: Money) : DuesMessage
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
)

/**
 * The baki (credit) book screen state.
 *
 * Deliberately simple: who owes, how much, since when — and a one-tap
 * "received payment" flow, because at the counter speed is everything.
 */
class DuesViewModel(
    private val dues: DuesRepository,
    sessionStore: com.lipon.rakho.data.session.SessionStore,
) : ViewModel() {

    private val message = MutableStateFlow<DuesMessage?>(null)
    private val settling = MutableStateFlow<CustomerDue?>(null)

    val state: StateFlow<DuesUiState> = combine(
        dues.observeDues(),
        message,
        settling,
    ) { summary, msg, settlingCustomer ->
        DuesUiState(
            loading = false,
            total = summary.total,
            customerCount = summary.customerCount,
            customers = summary.entries,
            message = msg,
            settling = settlingCustomer,
        )
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), DuesUiState())

    fun openSettle(customer: CustomerDue) {
        settling.value = customer
    }

    fun dismissSettle() {
        settling.value = null
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
}
