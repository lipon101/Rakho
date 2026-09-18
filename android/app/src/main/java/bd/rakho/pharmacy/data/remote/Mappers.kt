package bd.rakho.pharmacy.data.remote

import bd.rakho.pharmacy.core.model.Batch
import bd.rakho.pharmacy.core.model.CatalogItem
import bd.rakho.pharmacy.core.model.CartLine
import bd.rakho.pharmacy.core.model.Medicine
import bd.rakho.pharmacy.core.model.PaymentMethod
import bd.rakho.pharmacy.core.model.PlanSource
import bd.rakho.pharmacy.core.model.PlanTier
import bd.rakho.pharmacy.core.model.Sale
import bd.rakho.pharmacy.core.model.SubscriptionState
import bd.rakho.pharmacy.core.money.Money
import bd.rakho.pharmacy.core.time.DhakaTime
import bd.rakho.pharmacy.data.remote.dto.BatchDto
import bd.rakho.pharmacy.data.remote.dto.CatalogItemDto
import bd.rakho.pharmacy.data.remote.dto.MedicineDto
import bd.rakho.pharmacy.data.remote.dto.SaleAllocationDto
import bd.rakho.pharmacy.data.remote.dto.SaleDto
import bd.rakho.pharmacy.data.remote.dto.SubscriptionDto
import java.time.Instant

/**
 * API DTOs -> domain models. Anything with an unparseable date is dropped
 * (returns null) rather than crashing the whole screen.
 */

fun MedicineDto.toDomain(): Medicine = Medicine(
    id = id,
    brandName = brandName,
    genericName = genericName,
    strength = strength,
    dosageForm = dosageForm,
    barcode = barcode,
    defaultSellingPrice = Money.parse(defaultSellingPrice),
    lowStockThreshold = lowStockThreshold,
    availableQuantity = availableQuantity,
    isActive = isActive,
)

fun BatchDto.toDomain(): Batch? {
    val expiry = DhakaTime.parseDate(expiryDate) ?: return null
    return Batch(
        id = id,
        medicineId = medicine,
        medicineName = medicineName,
        medicineStrength = medicineStrength,
        batchNumber = batchNumber,
        expiryDate = expiry,
        unitCost = Money.parse(unitCost),
        sellingPrice = Money.parse(sellingPrice),
        quantityReceived = quantityReceived,
        quantityAvailable = quantityAvailable,
    )
}

fun CatalogItemDto.toDomain(): CatalogItem = CatalogItem(
    id = id,
    brandName = brandName,
    genericName = genericName,
    strength = strength,
    dosageForm = dosageForm,
    manufacturerName = manufacturerName,
)

fun SaleDto.toDomain(): Sale = Sale(
    id = id,
    invoiceNumber = invoiceNumber,
    soldAt = runCatching { Instant.parse(soldAt) }.getOrElse { Instant.EPOCH },
    total = Money.parse(totalAmount),
    paymentMethod = paymentMethod.toPaymentMethod(),
    note = note,
    lines = lines.map { line ->
        CartLine(
            medicineId = line.medicine,
            medicineName = line.medicineName,
            unitPrice = Money.parse(line.unitPrice),
            quantity = line.quantity,
            allocations = line.allocations.map { it.toDomain() },
        )
    },
)

private fun SaleAllocationDto.toDomain() = bd.rakho.pharmacy.core.model.BatchAllocation(
    batchId = batch,
    batchNumber = batchNumber,
    expiryDate = DhakaTime.parseDate(expiryDate) ?: java.time.LocalDate.MIN,
    quantity = quantity,
)

fun String.toPaymentMethod(): PaymentMethod = when (lowercase()) {
    "bkash", "mobile_banking" -> PaymentMethod.BKASH
    "nagad" -> PaymentMethod.NAGAD
    "card" -> PaymentMethod.CARD
    "credit" -> PaymentMethod.CREDIT
    else -> PaymentMethod.CASH
}

fun PaymentMethod.toApiValue(): String = when (this) {
    PaymentMethod.CASH -> "cash"
    PaymentMethod.BKASH -> "mobile_banking"
    PaymentMethod.NAGAD -> "mobile_banking"
    PaymentMethod.CARD -> "card"
    PaymentMethod.CREDIT -> "credit"
}

fun SubscriptionDto.toDomain(): SubscriptionState = SubscriptionState(
    tier = when (plan.lowercase()) {
        "pro" -> PlanTier.PRO
        "business" -> PlanTier.BUSINESS
        else -> PlanTier.FREE
    },
    source = when (source.lowercase()) {
        "trial" -> PlanSource.TRIAL
        "play" -> PlanSource.PLAY
        "web" -> PlanSource.WEB
        "manual" -> PlanSource.MANUAL
        else -> PlanSource.NONE
    },
    validUntil = validUntil?.let { DhakaTime.parseDate(it) },
    productId = productId,
)
