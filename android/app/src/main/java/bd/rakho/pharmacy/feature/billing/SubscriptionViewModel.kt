package bd.rakho.pharmacy.feature.billing

import android.app.Activity
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import bd.rakho.pharmacy.BuildConfig
import bd.rakho.pharmacy.core.model.SubscriptionState
import bd.rakho.pharmacy.data.repo.BillingRepository
import bd.rakho.pharmacy.data.session.SessionStore
import com.android.billingclient.api.Purchase
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

sealed interface SubscriptionMessage {
    data object Unavailable : SubscriptionMessage
    data object Verifying : SubscriptionMessage
    data object Activated : SubscriptionMessage
    data object PurchaseFailed : SubscriptionMessage
    data object NothingToRestore : SubscriptionMessage
}

data class SubscriptionUiState(
    val loading: Boolean = true,
    val offers: List<SubscriptionOffer> = emptyList(),
    val selectedProductId: String? = null,
    val entitlement: SubscriptionState = SubscriptionState(),
    val busy: Boolean = false,
    val message: SubscriptionMessage? = null,
) {
    val selectedOffer: SubscriptionOffer?
        get() = offers.firstOrNull { it.productId == selectedProductId } ?: offers.firstOrNull()
}

/**
 * Owns the Play purchase flow.
 *
 * The app never grants Pro by itself: Play returns the purchase, the backend
 * verifies it against the Google Play Developer API and returns the
 * entitlement, and only then is it shown as active. That keeps a single source
 * of truth for what a pharmacy has paid for, across Play, web and manual deals.
 */
class SubscriptionViewModel(
    private val playBilling: PlayBillingClient,
    private val billing: BillingRepository,
    @Suppress("unused") private val sessionStore: SessionStore,
) : ViewModel() {

    private val _state = MutableStateFlow(SubscriptionUiState())
    val state: StateFlow<SubscriptionUiState> = _state.asStateFlow()

    init {
        load()
        viewModelScope.launch {
            playBilling.events.collect { event ->
                when (event) {
                    is BillingEvent.Purchases -> handlePurchases(event.purchases)
                    is BillingEvent.Failure -> _state.value = _state.value.copy(
                        busy = false,
                        message = SubscriptionMessage.PurchaseFailed,
                    )
                }
            }
        }
    }

    fun load() {
        _state.value = _state.value.copy(loading = true)
        viewModelScope.launch {
            val offers = playBilling.queryOffers()
            val entitlement = billing.entitlement().getOrNull() ?: SubscriptionState()
            _state.value = _state.value.copy(
                loading = false,
                offers = offers,
                selectedProductId = _state.value.selectedProductId
                    ?: offers.firstOrNull { it.isYearly }?.productId
                    ?: offers.firstOrNull()?.productId,
                entitlement = entitlement,
                message = if (offers.isEmpty()) SubscriptionMessage.Unavailable else _state.value.message,
            )
        }
    }

    fun select(productId: String) {
        _state.value = _state.value.copy(selectedProductId = productId)
    }

    fun subscribe(activity: Activity) {
        val offer = _state.value.selectedOffer
        if (offer == null) {
            _state.value = _state.value.copy(message = SubscriptionMessage.Unavailable)
            return
        }
        _state.value = _state.value.copy(busy = true, message = null)
        val launched = playBilling.launchPurchase(activity, offer)
        if (!launched) {
            _state.value = _state.value.copy(busy = false, message = SubscriptionMessage.Unavailable)
        }
    }

    /** Re-checks Play for an existing subscription (new device, reinstall). */
    fun restore() {
        _state.value = _state.value.copy(busy = true, message = null)
        viewModelScope.launch {
            val purchases = playBilling.queryActivePurchases()
            if (purchases.isEmpty()) {
                _state.value = _state.value.copy(
                    busy = false,
                    message = SubscriptionMessage.NothingToRestore,
                )
                return@launch
            }
            handlePurchases(purchases)
        }
    }

    fun consumeMessage() {
        _state.value = _state.value.copy(message = null)
    }

    private suspend fun handlePurchases(purchases: List<Purchase>) {
        val purchase = purchases.firstOrNull() ?: run {
            _state.value = _state.value.copy(busy = false)
            return
        }
        _state.value = _state.value.copy(message = SubscriptionMessage.Verifying)
        val productId = purchase.products.firstOrNull().orEmpty()

        billing.verifyPurchase(
            purchaseToken = purchase.purchaseToken,
            productId = productId,
            packageName = BuildConfig.APPLICATION_ID,
        ).fold(
            onSuccess = { entitlement ->
                // Only acknowledge what the server has confirmed, so an
                // unverified purchase is auto-refunded by Play instead of
                // silently unlocking the app.
                playBilling.acknowledge(purchase)
                _state.value = _state.value.copy(
                    busy = false,
                    entitlement = entitlement,
                    message = SubscriptionMessage.Activated,
                )
            },
            onFailure = {
                _state.value = _state.value.copy(
                    busy = false,
                    message = SubscriptionMessage.PurchaseFailed,
                )
            },
        )
    }
}
