package com.lipon.rakho.data.repo

import com.lipon.rakho.core.result.AppError
import com.lipon.rakho.data.remote.RakhoApi
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import retrofit2.Retrofit
import retrofit2.converter.kotlinx.serialization.asConverterFactory
import java.io.IOException
import java.util.concurrent.TimeUnit

/**
 * Strictly verifies a candidate API key against the server before accepting it.
 *
 * Formerly part of BillingRepository; the subscription half is gone (Rakho is
 * free for everyone) and only this key check remains, so the class is named for
 * what it actually does. The probe uses the key-scoped pharmacy endpoint: a bad
 * key answers 401/403, a good one answers 200.
 */
class KeyVerifier(
    private val json: Json,
) {

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
            testApi.pharmacy()
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
