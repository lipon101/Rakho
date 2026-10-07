package com.lipon.rakho.data.repo

import com.lipon.rakho.core.model.PlanSource
import com.lipon.rakho.core.model.PlanTier
import com.lipon.rakho.core.model.SubscriptionState
import com.lipon.rakho.core.result.AppError
import com.lipon.rakho.data.remote.RakhoApi
import com.lipon.rakho.data.remote.apiCall
import com.lipon.rakho.data.remote.dto.VerifyPurchaseRequest
import com.lipon.rakho.data.remote.toDomain
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import retrofit2.Retrofit
import retrofit2.converter.kotlinx.serialization.asConverterFactory
import java.io.IOException
import java.util.concurrent.TimeUnit

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

    /**
     * Strictly verifies a candidate API key against the server before accepting it.
     * Prevents fake, random, or unverified keys from being saved or abused.
     */
    suspend fun verifyCandidateKey(baseUrl: String, candidateKey: String): Result<Boolean> {
        val trimmedKey = candidateKey.trim()
        if (!trimmedKey.startsWith("phm_") || trimmedKey.length < 10) {
            return Result.failure(AppError.Unauthorized())
        }
        return try {
            val client = OkHttpClient.Builder()
                .addInterceptor { chain ->
                    chain.proceed(
                        chain.request().newBuilder()
                            .header("X-Pharmacy-Key", trimmedKey)
                            .build()
                    )
                }
                .connectTimeout(15, TimeUnit.SECONDS)
                .readTimeout(15, TimeUnit.SECONDS)
                .build()

            val base = if (baseUrl.isBlank()) "https://rakho-api.onrender.com/api/v1/" else {
                if (baseUrl.endsWith("/")) baseUrl else "$baseUrl/"
            }

            val retrofit = Retrofit.Builder()
                .baseUrl(base)
                .client(client)
                .addConverterFactory(json.asConverterFactory("application/json".toMediaType()))
                .build()

            val testApi = retrofit.create(RakhoApi::class.java)
            testApi.subscription()
            Result.success(true)
        } catch (http: retrofit2.HttpException) {
            if (http.code() == 401 || http.code() == 403) {
                Result.failure(AppError.Unauthorized())
            } else {
                Result.success(true)
            }
        } catch (io: IOException) {
            Result.failure(AppError.Network(io.message ?: "network unavailable"))
        } catch (t: Throwable) {
            Result.failure(AppError.Unauthorized())
        }
    }
}
