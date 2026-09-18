package bd.rakho.pharmacy.data.remote

import bd.rakho.pharmacy.data.remote.dto.AlertsDto
import bd.rakho.pharmacy.data.remote.dto.BatchDto
import bd.rakho.pharmacy.data.remote.dto.CatalogItemDto
import bd.rakho.pharmacy.data.remote.dto.CreateMedicineRequest
import bd.rakho.pharmacy.data.remote.dto.CreateSaleRequest
import bd.rakho.pharmacy.data.remote.dto.DashboardDto
import bd.rakho.pharmacy.data.remote.dto.HealthDto
import bd.rakho.pharmacy.data.remote.dto.ListEnvelope
import bd.rakho.pharmacy.data.remote.dto.MedicineDto
import bd.rakho.pharmacy.data.remote.dto.PharmacyDto
import bd.rakho.pharmacy.data.remote.dto.PharmacyPatchRequest
import bd.rakho.pharmacy.data.remote.dto.PurchaseResponseDto
import bd.rakho.pharmacy.data.remote.dto.ReceivePurchaseRequest
import bd.rakho.pharmacy.data.remote.dto.SaleDto
import bd.rakho.pharmacy.data.remote.dto.SubscriptionDto
import bd.rakho.pharmacy.data.remote.dto.VerifyPurchaseRequest
import bd.rakho.pharmacy.data.remote.dto.WastageRequest
import bd.rakho.pharmacy.data.remote.dto.WastageResponseDto
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.PATCH
import retrofit2.http.POST
import retrofit2.http.Path
import retrofit2.http.Query

/**
 * Endpoints of the deployed Rakho API. All tenant calls carry the pharmacy key
 * via [AuthInterceptor].
 */
interface RakhoApi {

    @GET("health/")
    suspend fun health(): HealthDto

    @GET("inventory/medicines/")
    suspend fun medicines(@Query("q") query: String? = null): ListEnvelope<MedicineDto>

    @POST("inventory/medicines/")
    suspend fun createMedicine(@Body body: CreateMedicineRequest): MedicineDto

    @GET("inventory/batches/")
    suspend fun batches(
        @Query("active") active: String? = null,
        @Query("medicine") medicineId: String? = null,
    ): ListEnvelope<BatchDto>

    @POST("inventory/batches/{id}/write-off/")
    suspend fun writeOffBatch(
        @Path("id") batchId: String,
        @Body body: WastageRequest,
    ): WastageResponseDto

    @POST("inventory/purchases/")
    suspend fun receivePurchase(@Body body: ReceivePurchaseRequest): PurchaseResponseDto

    @GET("inventory/sales/")
    suspend fun sales(): ListEnvelope<SaleDto>

    @POST("inventory/sales/")
    suspend fun createSale(@Body body: CreateSaleRequest): SaleDto

    @GET("inventory/alerts/")
    suspend fun alerts(@Query("days") days: Int = 90): AlertsDto

    @GET("inventory/dashboard/")
    suspend fun dashboard(): DashboardDto

    @GET("inventory/pharmacy/")
    suspend fun pharmacy(): PharmacyDto

    @PATCH("inventory/pharmacy/")
    suspend fun patchPharmacy(@Body body: PharmacyPatchRequest): PharmacyDto

    @GET("catalog/medicines/")
    suspend fun catalog(@Query("q") query: String): ListEnvelope<CatalogItemDto>

    /** Entitlement for this pharmacy (added by the billing backend). */
    @GET("billing/subscription/")
    suspend fun subscription(): SubscriptionDto

    /** Server-side Play purchase verification. */
    @POST("billing/play/verify/")
    suspend fun verifyPlayPurchase(@Body body: VerifyPurchaseRequest): SubscriptionDto
}
