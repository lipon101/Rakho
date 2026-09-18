package bd.rakho.pharmacy.data.repo

import bd.rakho.pharmacy.core.model.PlanSource
import bd.rakho.pharmacy.core.model.PlanTier
import bd.rakho.pharmacy.core.model.SubscriptionState
import bd.rakho.pharmacy.core.result.AppError
import bd.rakho.pharmacy.data.remote.RakhoApi
import bd.rakho.pharmacy.data.remote.apiCall
import bd.rakho.pharmacy.data.remote.dto.VerifyPurchaseRequest
import bd.rakho.pharmacy.data.remote.toDomain
import kotlinx.serialization.json.Json

/**
 * Subscription entitlements.
 *
 * The server is the single source of truth: a Play purchase is only trusted
 * after the backend has verified it with the Google Play Developer API. If the
 * billing endpoints are not live yet (fresh deployments return 404), the app
 * degrades to the free tier instead of erroring — so shipping the app never
 * depends on the backend being ahead of it.
 */
class BillingRepository(
    private val api: RakhoApi,
    private val json: Json,
) {

    suspend fun entitlement(): Result<SubscriptionState> = apiCall(json) {
        api.subscription().toDomain()
    }.recoverCatching { error ->
        if (error is AppError.NotFound) {
            SubscriptionState(tier = PlanTier.FREE, source = PlanSource.NONE)
        } else {
            throw error
        }
    }

    suspend fun verifyPurchase(
        purchaseToken: String,
        productId: String,
        packageName: String,
    ): Result<SubscriptionState> = apiCall(json) {
        api.verifyPlayPurchase(
            VerifyPurchaseRequest(
                purchaseToken = purchaseToken,
                productId = productId,
                packageName = packageName,
            ),
        ).toDomain()
    }
}
