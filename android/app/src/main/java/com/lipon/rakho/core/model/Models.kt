package com.lipon.rakho.core.model

import com.lipon.rakho.core.money.Money
import java.time.Instant
import java.time.LocalDate

/**
 * A pharmacy's sellable medicine (tenant-scoped).
 *
 * [localId] is set only for medicines created while the app has never been
 * connected (the free local-only mode). It is a client-generated UUID and is
 * replaced by a real server id once the pharmacy connects and syncs.
 */
data class Medicine(
    val id: String,
    val brandName: String,
    val genericName: String = "",
    val strength: String = "",
    val dosageForm: String = "",
    val barcode: String = "",
    val defaultSellingPrice: Money = Money.ZERO,
    val lowStockThreshold: Int = 10,
    val availableQuantity: Int = 0,
    val isActive: Boolean = true,
    val localId: String? = null,
) {
    val displayName: String
        get() = listOf(brandName, strength).filter { it.isNotBlank() }.joinToString(" ")

    val isLocalOnly: Boolean get() = localId != null
}

/** A received stock batch. Expiry drives FEFO ordering. */
data class Batch(
    val id: String,
    val medicineId: String,
    val medicineName: String,
    val medicineStrength: String = "",
    val batchNumber: String,
    val expiryDate: LocalDate,
    val unitCost: Money,
    val sellingPrice: Money,
    val quantityReceived: Int,
    val quantityAvailable: Int,
) {
    val stockValue: Money get() = unitCost * quantityAvailable
}

/** A sale line's allocation of quantity across specific batches. */
data class BatchAllocation(
    val batchId: String,
    val batchNumber: String,
    val expiryDate: LocalDate,
    val quantity: Int,
    /** Cost per unit captured at sale time; zero when unavailable. */
    val unitCost: Money = Money.ZERO,
)

/** One line in the POS cart, resolved to concrete batch allocations. */
data class CartLine(
    val medicineId: String,
    val medicineName: String,
    val unitPrice: Money,
    val quantity: Int,
    val allocations: List<BatchAllocation>,
)

enum class PaymentMethod { CASH, BKASH, NAGAD, CARD, CREDIT }

data class Sale(
    val id: String,
    val invoiceNumber: String,
    val soldAt: Instant,
    val total: Money,
    val paymentMethod: PaymentMethod,
    val lines: List<CartLine> = emptyList(),
    val note: String = "",
)

/** Catalogue entry from the national Bangladesh medicine dataset. */
data class CatalogItem(
    val id: Long,
    val brandName: String,
    val genericName: String = "",
    val strength: String = "",
    val dosageForm: String = "",
    val manufacturerName: String = "",
) {
    val displayName: String
        get() = listOf(brandName, strength).filter { it.isNotBlank() }.joinToString(" ")
}

/** A batch that is expired or expiring, with days remaining. */
data class ExpiryAlert(
    val batch: Batch,
    val daysUntilExpiry: Long,
) {
    val isExpired: Boolean get() = daysUntilExpiry < 0
}

data class LowStockAlert(
    val medicineId: String,
    val name: String,
    val available: Int,
    val threshold: Int,
)

data class DashboardStats(
    val todaySales: Money = Money.ZERO,
    val todayProfit: Money = Money.ZERO,
    val todaySaleCount: Int = 0,
    val stockValue: Money = Money.ZERO,
    val medicineCount: Int = 0,
    val expiredCount: Int = 0,
    val expiringSoonCount: Int = 0,
    val lowStockCount: Int = 0,
    val expiringValue: Money = Money.ZERO,
    val duesTotal: Money = Money.ZERO,
    val duesCount: Int = 0,
)

/**
 * The baki (credit) book — who owes the shop how much.
 *
 * Entries are derived from credit sales (amount owed) and settled payments
 * (amount reduced), so the numbers always reconcile with the sales ledger.
 */
data class CustomerDue(
    val customer: String,
    val invoiceNumber: String,
    val amount: Money,
    val dueSinceMillis: Long,
    val note: String = "",
)

data class DuesSummary(
    val total: Money = Money.ZERO,
    val customerCount: Int = 0,
    val entries: List<CustomerDue> = emptyList(),
    /** Money owed by customers whose oldest due is 30+ / 8-29 / 0-7 days old. */
    val agingOver30: Money = Money.ZERO,
    val agingMid: Money = Money.ZERO,
    val agingFresh: Money = Money.ZERO,
)

/** Total sold on one calendar day (Dhaka time), for trend charts. */
data class DayTotal(
    val date: LocalDate,
    val total: Money,
)

enum class PlanTier { FREE, PRO, BUSINESS }

enum class PlanSource { NONE, TRIAL, PLAY, WEB, MANUAL }

/** What the pharmacy is entitled to right now (authoritative server-side). */
data class SubscriptionState(
    val tier: PlanTier = PlanTier.FREE,
    val source: PlanSource = PlanSource.NONE,
    val validUntil: LocalDate? = null,
    val productId: String? = null,
) {
    val isPro: Boolean get() = tier != PlanTier.FREE
}

data class PharmacyProfile(
    val name: String,
    val currency: String = "BDT",
    val address: String = "",
    val phone: String = "",
)

/** Localised filters used by the stock screen. */
enum class StockFilter { ALL, EXPIRING, EXPIRED, LOW }

enum class PendingOperationType { SALE, PURCHASE, WASTAGE, MEDICINE }

data class PendingOperation(
    val id: Long,
    val type: PendingOperationType,
    val payload: String,
    val createdAt: Instant,
    val attempts: Int = 0,
    val lastError: String? = null,
)
