package com.lipon.rakho.data.remote.dto

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class ListEnvelope<T>(
    val count: Int = 0,
    val results: List<T> = emptyList(),
)

@Serializable
data class HealthDto(
    val status: String = "",
    val database: String = "",
    val version: String = "",
)

@Serializable
data class MedicineDto(
    val id: String,
    @SerialName("brand_name") val brandName: String = "",
    @SerialName("generic_name") val genericName: String = "",
    val strength: String = "",
    @SerialName("dosage_form") val dosageForm: String = "",
    @SerialName("manufacturer_name") val manufacturerName: String = "",
    val barcode: String = "",
    @SerialName("default_selling_price") val defaultSellingPrice: String = "0.00",
    @SerialName("low_stock_threshold") val lowStockThreshold: Int = 10,
    @SerialName("available_quantity") val availableQuantity: Int = 0,
    @SerialName("is_active") val isActive: Boolean = true,
)

@Serializable
data class BatchDto(
    val id: String,
    val medicine: String,
    @SerialName("medicine_name") val medicineName: String = "",
    @SerialName("medicine_strength") val medicineStrength: String = "",
    @SerialName("batch_number") val batchNumber: String = "",
    @SerialName("expiry_date") val expiryDate: String = "",
    @SerialName("unit_cost") val unitCost: String = "0.00",
    @SerialName("selling_price") val sellingPrice: String = "0.00",
    @SerialName("quantity_received") val quantityReceived: Int = 0,
    @SerialName("quantity_available") val quantityAvailable: Int = 0,
    // Present on locally-created batches; server responses omit it.
    @SerialName("supplier_name") val supplierName: String = "",
)

@Serializable
data class SaleAllocationDto(
    val batch: String = "",
    @SerialName("batch_number") val batchNumber: String = "",
    @SerialName("expiry_date") val expiryDate: String = "",
    val quantity: Int = 0,
    @SerialName("unit_cost") val unitCost: String = "0.00",
)

@Serializable
data class SaleLineDto(
    val medicine: String = "",
    @SerialName("medicine_name") val medicineName: String = "",
    val quantity: Int = 0,
    @SerialName("unit_price") val unitPrice: String = "0.00",
    @SerialName("line_total") val lineTotal: String = "0.00",
    val allocations: List<SaleAllocationDto> = emptyList(),
)

@Serializable
data class SaleDto(
    val id: String,
    @SerialName("invoice_number") val invoiceNumber: String = "",
    @SerialName("sold_at") val soldAt: String = "",
    @SerialName("total_amount") val totalAmount: String = "0.00",
    @SerialName("payment_method") val paymentMethod: String = "cash",
    val note: String = "",
    val lines: List<SaleLineDto> = emptyList(),
)

@Serializable
data class PharmacyDto(
    val id: String = "",
    val name: String = "",
    val currency: String = "BDT",
    val address: String = "",
    val phone: String = "",
)

@Serializable
data class InventorySummaryDto(
    @SerialName("total_units") val totalUnits: Int = 0,
    @SerialName("total_value_bdt") val totalValue: String = "0",
    @SerialName("unique_medicines") val uniqueMedicines: Int = 0,
)

@Serializable
data class SalesSummaryDto(
    @SerialName("today_amount_bdt") val todayAmount: String = "0",
    @SerialName("today_count") val todayCount: Int = 0,
    @SerialName("week_amount_bdt") val weekAmount: String = "0",
    @SerialName("week_count") val weekCount: Int = 0,
)

@Serializable
data class AlertCountsDto(
    @SerialName("expired_batches") val expiredBatches: Int = 0,
    @SerialName("expiring_soon") val expiringSoon: Int = 0,
    @SerialName("low_stock_items") val lowStockItems: Int = 0,
)

@Serializable
data class DashboardDto(
    val pharmacy: PharmacyDto = PharmacyDto(),
    val inventory: InventorySummaryDto = InventorySummaryDto(),
    val sales: SalesSummaryDto = SalesSummaryDto(),
    val alerts: AlertCountsDto = AlertCountsDto(),
    @SerialName("generated_at") val generatedAt: String = "",
)

@Serializable
data class AlertOverviewDto(
    @SerialName("expired_count") val expiredCount: Int = 0,
    @SerialName("expiring_count") val expiringCount: Int = 0,
    @SerialName("low_stock_count") val lowStockCount: Int = 0,
    @SerialName("horizon_days") val horizonDays: Int = 90,
)

@Serializable
data class AlertsDto(
    val overview: AlertOverviewDto = AlertOverviewDto(),
    val expired: List<BatchDto> = emptyList(),
    @SerialName("expiring_soon") val expiringSoon: List<BatchDto> = emptyList(),
    @SerialName("low_stock") val lowStock: List<MedicineDto> = emptyList(),
)

@Serializable
data class CatalogItemDto(
    val id: Long,
    @SerialName("brand_name") val brandName: String = "",
    @SerialName("generic_name") val genericName: String = "",
    val strength: String = "",
    @SerialName("dosage_form") val dosageForm: String = "",
    @SerialName("manufacturer_name") val manufacturerName: String = "",
)

// ---- Requests -------------------------------------------------------------

@Serializable
data class CreateMedicineRequest(
    @SerialName("brand_name") val brandName: String,
    @SerialName("generic_name") val genericName: String = "",
    val strength: String = "",
    @SerialName("dosage_form") val dosageForm: String = "",
    @SerialName("default_selling_price") val defaultSellingPrice: String,
    @SerialName("low_stock_threshold") val lowStockThreshold: Int,
    @SerialName("catalog_medicine") val catalogMedicine: Long? = null,
)

@Serializable
data class PurchaseItemRequest(
    val medicine: String,
    @SerialName("batch_number") val batchNumber: String,
    @SerialName("expiry_date") val expiryDate: String,
    val quantity: Int,
    @SerialName("unit_cost") val unitCost: String,
    @SerialName("selling_price") val sellingPrice: String,
    @SerialName("supplier_name") val supplierName: String = "",
    val notes: String = "",
)

@Serializable
data class ReceivePurchaseRequest(
    val items: List<PurchaseItemRequest>,
)

@Serializable
data class SaleLineRequest(
    val medicine: String,
    val quantity: Int,
    @SerialName("unit_price") val unitPrice: String? = null,
)

@Serializable
data class CreateSaleRequest(
    @SerialName("invoice_number") val invoiceNumber: String,
    @SerialName("payment_method") val paymentMethod: String,
    val note: String = "",
    val lines: List<SaleLineRequest>,
)

@Serializable
data class WastageRequest(val note: String = "")

@Serializable
data class PurchaseResponseDto(
    val message: String = "",
    val batches: List<BatchDto> = emptyList(),
)

@Serializable
data class WastageResponseDto(
    val message: String = "",
    val batch: BatchDto? = null,
)

@Serializable
data class PharmacyPatchRequest(
    val name: String? = null,
    val currency: String? = null,
    val address: String? = null,
    val phone: String? = null,
)

/** Entitlement as served by the Rakho backend (absent before it is deployed). */
@Serializable
data class SubscriptionDto(
    val plan: String = "free",
    val source: String = "none",
    @SerialName("valid_until") val validUntil: String? = null,
    @SerialName("product_id") val productId: String? = null,
    @SerialName("is_active") val isActive: Boolean = false,
)

@Serializable
data class VerifyPurchaseRequest(
    @SerialName("purchase_token") val purchaseToken: String,
    @SerialName("product_id") val productId: String,
    @SerialName("package_name") val packageName: String,
)
