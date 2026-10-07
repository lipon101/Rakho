package com.lipon.rakho.data.remote

import com.lipon.rakho.core.result.AppError
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import retrofit2.HttpException
import retrofit2.Response

/**
 * Error mapping is load-bearing: the sync queue decides "already recorded,
 * treat as done" from [AppError.Validation.detail], and screens surface the
 * same detail to the pharmacist. A mapping that silently drops the API's
 * message turns both into generic noise.
 */
class ApiCallTest {

    private val json: Json = NetworkModule.json

    private fun httpException(code: Int, body: String): HttpException =
        HttpException(
            Response.error<Any>(code, body.toResponseBody("application/json".toMediaType())),
        )

    private fun failureOf(code: Int, body: String): AppError {
        val error = httpException(code, body)
        val result: Result<Unit> = runBlocking { apiCall(json) { throw error } }
        val failure = result.exceptionOrNull()
        assertTrue("expected a failure, got $result", failure is AppError)
        return failure as AppError
    }

    @Test
    fun `validation error carries the API detail message`() {
        val error = failureOf(400, """{"error":{"detail":"invoice already exists"}}""")
        assertTrue(error is AppError.Validation)
        assertEquals("invoice already exists", (error as AppError.Validation).detail)
    }

    @Test
    fun `duplicate invoice detection has real text to match`() {
        // SyncRepository replays a queued sale and recognises a duplicate by
        // this detail; a generic fallback would make every replay a failure.
        val error = failureOf(400, """{"error":{"detail":"Sale with this invoice number already exists."}}""")
        assertTrue((error as AppError.Validation).detail.contains("already exists", ignoreCase = true))
    }

    @Test
    fun `flat error envelope is unwrapped too`() {
        val error = failureOf(400, """{"error":"batch is expired"}""")
        assertEquals("batch is expired", (error as AppError.Validation).detail)
    }

    @Test
    fun `detail envelope without error key is unwrapped`() {
        val error = failureOf(422, """{"detail":"expiry_date is in the past"}""")
        assertEquals("expiry_date is in the past", (error as AppError.Validation).detail)
    }

    @Test
    fun `field error lists read the first message`() {
        val error = failureOf(400, """{"error":{"lines":["quantity is too large"]}}""")
        assertEquals("quantity is too large", (error as AppError.Validation).detail)
    }

    @Test
    fun `unparseable error body degrades to a short snippet`() {
        val error = failureOf(502, "<html><body>Bad Gateway from the proxy</body></html>")
        assertTrue(error is AppError.Server)
        assertEquals(502, (error as AppError.Server).code)
        assertTrue(error.detail!!.startsWith("<html>"))
        assertTrue(error.detail!!.length <= 160)
    }

    @Test
    fun `missing body falls back to a generic rejection`() {
        val error = failureOf(400, "")
        assertEquals("Request rejected (400)", (error as AppError.Validation).detail)
    }

    @Test
    fun `not found keeps a readable message`() {
        val error = failureOf(404, """{"error":{"detail":"batch not found"}}""")
        assertTrue(error is AppError.NotFound)
        assertEquals("batch not found", error.message)
    }

    @Test
    fun `io failures map to a network error so the queue retries`() {
        val result: Result<Unit> = runBlocking {
            apiCall(json) { throw java.io.IOException("connection reset") }
        }
        assertTrue(result.exceptionOrNull() is AppError.Network)
    }

    @Test
    fun `cancellation is rethrown instead of swallowed`() {
        var rethrown = false
        try {
            runBlocking { apiCall<Unit>(json) { throw kotlinx.coroutines.CancellationException("cancelled") } }
        } catch (_: kotlinx.coroutines.CancellationException) {
            rethrown = true
        }
        assertTrue("CancellationException must propagate", rethrown)
    }
}
