package com.lipon.rakho.core.result

/**
 * Every failure the app can surface, typed so the UI can react correctly
 * (an invalid API key needs a reconnect prompt, not a generic error).
 */
sealed class AppError(message: String) : Exception(message) {

    /** No connectivity or the request never completed. */
    class Network(message: String = "network unavailable") : AppError(message)

    /** 401/403 — the pharmacy key is missing, revoked or wrong. */
    class Unauthorized(message: String = "unauthorized") : AppError(message)

    /** 4xx validation problem; [detail] comes from the API error envelope. */
    class Validation(val detail: String) : AppError(detail)

    /** 5xx or unexpected status. */
    class Server(val code: Int, val detail: String?) : AppError("server $code")

    class Unknown(override val cause: Throwable?) : AppError(cause?.message ?: "unknown")

    class NotFound(detail: String = "not found") : AppError(detail)
}
