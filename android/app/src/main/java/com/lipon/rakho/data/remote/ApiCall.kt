package com.lipon.rakho.data.remote

import com.lipon.rakho.core.result.AppError
import kotlinx.coroutines.CancellationException
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import retrofit2.HttpException
import java.io.IOException

/**
 * Runs an API call and converts any failure into a typed [AppError] so the UI
 * can distinguish "wrong API key" from "no internet" from "server broke".
 */
suspend fun <T> apiCall(json: Json, block: suspend () -> T): Result<T> = try {
    Result.success(block())
} catch (cancellation: CancellationException) {
    throw cancellation
} catch (http: HttpException) {
    Result.failure(http.toAppError(json))
} catch (io: IOException) {
    Result.failure(AppError.Network(io.message ?: "network unavailable"))
} catch (other: Throwable) {
    Result.failure(AppError.Unknown(other))
}

private fun HttpException.toAppError(json: Json): AppError = when (code()) {
    401, 403 -> AppError.Unauthorized()
    404 -> AppError.NotFound(extractDetail(json) ?: "not found")
    in 400..499 -> AppError.Validation(extractDetail(json) ?: "Request rejected (${code()})")
    else -> AppError.Server(code(), extractDetail(json))
}

/**
 * Pulls a human-readable message out of the API error envelope:
 * {"error": {"detail": "..."}} or {"error": "..."} or {"detail": "..."}.
 */
internal fun extractDetail(json: Json, body: String? = null): String? {
    val raw = body ?: return null
    if (raw.isBlank()) return null
    return try {
        val root = json.parseToJsonElement(raw)
        val node = (root as? JsonObject)?.get("error") ?: root
        when (node) {
            is JsonPrimitive -> node.content
            is JsonObject -> {
                val detail = node["detail"] ?: node["message"] ?: node["lines"] ?: node["medicine"]
                when (detail) {
                    is JsonPrimitive -> detail.content
                    is JsonArray -> detail.firstOrNull()?.let { (it as? JsonPrimitive)?.content }
                    else -> null
                }
            }
            else -> null
        }
    } catch (_: Throwable) {
        // Non-JSON error page (e.g. a proxy 502) — fall back to a short snippet.
        raw.takeIf { it.isNotBlank() }?.take(160)
    }
}

internal fun HttpException.detailOrNull(json: Json): String? =
    try {
        extractDetail(json, response()?.errorBody()?.string())
    } catch (_: Throwable) {
        null
    }

internal fun JsonObject.firstPrimitiveContent(): String? =
    entries.firstOrNull()?.value?.let { (it as? JsonPrimitive)?.content }
