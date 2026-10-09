package com.lipon.rakho.data.repo

/**
 * Plain request objects the screens build for pharmacy writes.
 *
 * Money is carried as decimal strings exactly as the counter typed it; the
 * repositories parse them into [com.lipon.rakho.core.money.Money] once.
 */
data class CreateMedicineRequest(
    val brandName: String,
    val genericName: String = "",
    val strength: String = "",
    val dosageForm: String = "",
    val defaultSellingPrice: String,
    val lowStockThreshold: Int,
    val catalogMedicine: Long? = null,
    val barcode: String = "",
)

/** Editing a medicine the shop already keeps. All fields are optional. */
data class UpdateMedicineRequest(
    val brandName: String? = null,
    val genericName: String? = null,
    val strength: String? = null,
    val dosageForm: String? = null,
    val barcode: String? = null,
    val defaultSellingPrice: String? = null,
    val lowStockThreshold: Int? = null,
)

/**
 * Correcting a received batch. The quantity is an absolute counted value,
 * never a delta, so a retried write can never apply the change twice.
 */
data class UpdateBatchRequest(
    val batchNumber: String? = null,
    val expiryDate: String? = null,
    val unitCost: String? = null,
    val sellingPrice: String? = null,
    val quantityAvailable: Int? = null,
)

data class PurchaseItemRequest(
    val medicine: String,
    val batchNumber: String,
    val expiryDate: String,
    val quantity: Int,
    val unitCost: String,
    val sellingPrice: String,
    val supplierName: String = "",
    val notes: String = "",
)
