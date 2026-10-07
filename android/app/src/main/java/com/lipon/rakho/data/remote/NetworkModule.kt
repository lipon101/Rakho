package com.lipon.rakho.data.remote

import com.lipon.rakho.BuildConfig
import com.lipon.rakho.data.session.SessionStore
import kotlinx.serialization.json.Json
import okhttp3.Interceptor
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Response
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.kotlinx.serialization.asConverterFactory
import java.util.concurrent.TimeUnit

/** Adds the pharmacy tenant key to every request. */
class AuthInterceptor(private val session: SessionStore) : Interceptor {

    override fun intercept(chain: Interceptor.Chain): Response {
        val key = session.apiKeyOrNull()
        val request = if (key.isNullOrBlank()) {
            chain.request()
        } else {
            chain.request().newBuilder()
                .header(HEADER_PHARMACY_KEY, key)
                .build()
        }
        return chain.proceed(request)
    }

    companion object {
        const val HEADER_PHARMACY_KEY = "X-Pharmacy-Key"
    }
}

object NetworkModule {

    val json: Json = Json {
        ignoreUnknownKeys = true
        explicitNulls = false
        isLenient = true
        encodeDefaults = true
    }

    fun okHttp(session: SessionStore): OkHttpClient = OkHttpClient.Builder()
        .addInterceptor(AuthInterceptor(session))
        .apply {
            if (BuildConfig.DEBUG) {
                addInterceptor(
                    HttpLoggingInterceptor().apply { level = HttpLoggingInterceptor.Level.BASIC },
                )
            }
        }
        .connectTimeout(20, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .retryOnConnectionFailure(true)
        .build()

    /**
     * [baseUrlOverride] lets a self-hosted pharmacy point the app at its own
     * Rakho server without shipping a new build.
     */
    fun retrofit(session: SessionStore, baseUrlOverride: String? = null): Retrofit {
        val base = (baseUrlOverride ?: BuildConfig.API_BASE_URL).ensureTrailingSlash()
        return Retrofit.Builder()
            .baseUrl(base)
            .client(okHttp(session))
            .addConverterFactory(json.asConverterFactory("application/json".toMediaType()))
            .build()
    }

    fun api(session: SessionStore, baseUrlOverride: String? = null): RakhoApi =
        retrofit(session, baseUrlOverride).create(RakhoApi::class.java)

    private fun String.ensureTrailingSlash(): String = if (endsWith("/")) this else "$this/"
}
