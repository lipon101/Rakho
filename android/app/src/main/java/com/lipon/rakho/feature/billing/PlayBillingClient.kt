package com.lipon.rakho.feature.billing

import android.app.Activity
import android.content.Context
import com.android.billingclient.api.AcknowledgePurchaseParams
import com.android.billingclient.api.BillingClient
import com.android.billingclient.api.BillingClientStateListener
import com.android.billingclient.api.BillingFlowParams
import com.android.billingclient.api.BillingResult
import com.android.billingclient.api.PendingPurchasesParams
import com.android.billingclient.api.ProductDetails
import com.android.billingclient.api.Purchase
import com.android.billingclient.api.PurchasesUpdatedListener
import com.android.billingclient.api.QueryProductDetailsParams
import com.android.billingclient.api.QueryProductDetailsResult
import com.android.billingclient.api.QueryPurchasesParams
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withTimeoutOrNull
import kotlin.coroutines.resume

/** Subscription products declared in Play Console. */
object BillingProducts {
    const val PRO_MONTHLY = "rakho_pro_monthly"
    const val PRO_YEARLY = "rakho_pro_yearly"
    val ALL = listOf(PRO_MONTHLY, PRO_YEARLY)
}

/**
 * UI-facing offer, ready to render without touching the billing SDK again.
 *
 * [productDetails] is the object Play returned from the product query and is
 * what the purchase flow must be launched with — Billing 9 does not allow
 * hand-building ProductDetails.
 */
data class SubscriptionOffer(
    val productId: String,
    val title: String,
    val description: String,
    val formattedPrice: String,
    val basePlanId: String?,
    val offerToken: String?,
    val isYearly: Boolean,
    val productDetails: ProductDetails?,
)

sealed interface BillingEvent {
    data class Purchases(val purchases: List<Purchase>) : BillingEvent
    data class Failure(val code: Int, val message: String) : BillingEvent
}

/**
 * Thin, coroutine-friendly wrapper over Google Play Billing.
 *
 * Deliberately thin: it only talks to Play. Every purchase is handed to the
 * backend, which verifies it against the Play Developer API and owns the
 * entitlement — the app never decides on its own that a pharmacy is Pro.
 */
class PlayBillingClient(private val context: Context) {

    private var client: BillingClient? = null

    private val _events = MutableSharedFlow<BillingEvent>(extraBufferCapacity = 8)

    /** Purchase results as they arrive from Play, collected by the UI layer. */
    val events: SharedFlow<BillingEvent> = _events.asSharedFlow()

    private val purchasesUpdatedListener = PurchasesUpdatedListener { result, purchases ->
        val event = if (result.responseCode == BillingClient.BillingResponseCode.OK) {
            BillingEvent.Purchases(purchases.orEmpty())
        } else {
            BillingEvent.Failure(result.responseCode, result.debugMessage)
        }
        _events.tryEmit(event)
    }

    fun isReady(): Boolean = client?.isReady == true

    /** Connects (idempotent) and returns whether Play Billing is usable. */
    suspend fun connect(): Boolean {
        client?.let { if (it.isReady) return true }
        val billingClient = client ?: BillingClient.newBuilder(context)
            .setListener(purchasesUpdatedListener)
            .enablePendingPurchases(PendingPurchasesParams.newBuilder().enableOneTimeProducts().build())
            .enableAutoServiceReconnection()
            .build()
            .also { client = it }

        if (billingClient.isReady) return true
        return suspendCancellableCoroutine { continuation ->
            billingClient.startConnection(object : BillingClientStateListener {
                override fun onBillingSetupFinished(result: BillingResult) {
                    if (continuation.isActive) {
                        continuation.resume(result.responseCode == BillingClient.BillingResponseCode.OK)
                    }
                }

                override fun onBillingServiceDisconnected() {
                    if (continuation.isActive) continuation.resume(false)
                }
            })
        }
    }

    suspend fun queryOffers(): List<SubscriptionOffer> {
        if (!connect()) return emptyList()
        val billingClient = client ?: return emptyList()
        val params = QueryProductDetailsParams.newBuilder()
            .setProductList(
                BillingProducts.ALL.map { id ->
                    QueryProductDetailsParams.Product.newBuilder()
                        .setProductId(id)
                        .setProductType(BillingClient.ProductType.SUBS)
                        .build()
                },
            )
            .build()

        val deferred = CompletableDeferred<List<ProductDetails>>()
        billingClient.queryProductDetailsAsync(params) { result, queryResult ->
            deferred.complete(
                if (result.responseCode == BillingClient.BillingResponseCode.OK) {
                    queryResult.productDetailsList
                } else {
                    emptyList()
                },
            )
        }
        val details = withTimeoutOrNull(15_000) { deferred.await() }.orEmpty()
        return details.map { product ->
            val offer = product.subscriptionOfferDetails?.firstOrNull()
            val phase = offer?.pricingPhases?.pricingPhaseList?.firstOrNull()
            SubscriptionOffer(
                productId = product.productId,
                title = product.name,
                description = product.description,
                formattedPrice = phase?.formattedPrice.orEmpty(),
                basePlanId = offer?.basePlanId,
                offerToken = offer?.offerToken,
                isYearly = product.productId == BillingProducts.PRO_YEARLY,
                productDetails = product,
            )
        }
    }

    /** Launches the Play purchase sheet. Returns false if it could not start. */
    fun launchPurchase(activity: Activity, offer: SubscriptionOffer): Boolean {
        val billingClient = client?.takeIf { it.isReady } ?: return false
        val token = offer.offerToken ?: return false
        val details = offer.productDetails ?: return false
        val productDetailsParams = BillingFlowParams.ProductDetailsParams.newBuilder()
            .setProductDetails(details)
            .setOfferToken(token)
            .build()

        val flowParams = BillingFlowParams.newBuilder()
            .setProductDetailsParamsList(listOf(productDetailsParams))
            .build()
        return billingClient.launchBillingFlow(activity, flowParams).responseCode ==
            BillingClient.BillingResponseCode.OK
    }

    /** Active subscriptions already owned by this Play account (restore path). */
    suspend fun queryActivePurchases(): List<Purchase> {
        if (!connect()) return emptyList()
        val billingClient = client ?: return emptyList()
        val deferred = CompletableDeferred<List<Purchase>>()
        val params = QueryPurchasesParams.newBuilder()
            .setProductType(BillingClient.ProductType.SUBS)
            .build()
        billingClient.queryPurchasesAsync(params) { result, purchases ->
            deferred.complete(
                if (result.responseCode == BillingClient.BillingResponseCode.OK) purchases else emptyList(),
            )
        }
        return withTimeoutOrNull(15_000) { deferred.await() }.orEmpty()
    }

    /** Acknowledges a verified subscription so Play does not auto-refund it. */
    suspend fun acknowledge(purchase: Purchase): Boolean {
        if (purchase.isAcknowledged) return true
        val billingClient = client ?: return false
        val deferred = CompletableDeferred<Boolean>()
        billingClient.acknowledgePurchase(
            AcknowledgePurchaseParams.newBuilder()
                .setPurchaseToken(purchase.purchaseToken)
                .build(),
        ) { result ->
            deferred.complete(result.responseCode == BillingClient.BillingResponseCode.OK)
        }
        return withTimeoutOrNull(15_000) { deferred.await() } ?: false
    }

    fun endConnection() {
        client?.endConnection()
        client = null
    }
}
