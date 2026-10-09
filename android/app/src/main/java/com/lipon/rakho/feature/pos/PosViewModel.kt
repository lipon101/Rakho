package com.lipon.rakho.feature.pos

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.lipon.rakho.core.cloud.CloudServices
import com.lipon.rakho.core.domain.BatchStock
import com.lipon.rakho.core.domain.CartCalculator
import com.lipon.rakho.core.domain.CartTotals
import com.lipon.rakho.core.domain.FefoPlanner
import com.lipon.rakho.core.domain.FefoResult
import com.lipon.rakho.core.domain.MedicineSearch
import com.lipon.rakho.core.model.CatalogItem
import com.lipon.rakho.core.model.Batch
import com.lipon.rakho.core.model.CartLine
import com.lipon.rakho.core.model.Medicine
import com.lipon.rakho.core.model.PaymentMethod
import com.lipon.rakho.core.money.Money
import com.lipon.rakho.core.result.AppError
import com.lipon.rakho.core.time.DhakaTime
import com.lipon.rakho.core.time.ExpiryRules
import com.lipon.rakho.data.repo.CatalogRepository
import com.lipon.rakho.data.repo.CustomersRepository
import com.lipon.rakho.data.repo.InventoryRepository
import com.lipon.rakho.data.repo.SalesRepository
import com.lipon.rakho.data.session.SessionStore
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import java.time.LocalDate

/** A sellable medicine with the stock facts the counter needs at a glance. */
data class PosItem(
    val medicine: Medicine,
    val available: Int,
    val sellableAvailable: Int,
    val nearestExpiry: LocalDate?,
    val price: Money,
) {
    val isOutOfStock: Boolean get() = sellableAvailable <= 0
}

sealed interface PosMessage {
    data class Recorded(val invoice: String, val receipt: Receipt) : PosMessage
    data class Queued(val receipt: Receipt) : PosMessage
    data class Failed(val text: String) : PosMessage
    data object InsufficientStock : PosMessage
    data object CustomerRequired : PosMessage
}

/** One line of the receipt the shop can hand or send to a customer. */
data class ReceiptLine(
    val name: String,
    val quantity: Int,
    val unitPrice: Money,
    val lineTotal: Money,
)

/**
 * Everything a customer-facing receipt needs, captured at checkout time so
 * sharing works offline and after the cart has been cleared.
 */
data class Receipt(
    val invoice: String,
    val soldAtMillis: Long,
    val shopName: String,
    val lines: List<ReceiptLine>,
    val subtotal: Money,
    val discount: Money,
    val total: Money,
    val paymentMethod: PaymentMethod,
    val received: Money,
    val changeDue: Money,
    val credit: Money,
    val customerName: String,
)

data class PosUiState(
    val query: String = "",
    val items: List<PosItem> = emptyList(),
    val cart: List<CartLine> = emptyList(),
    /** Raw text the counter typed per line, so decimals are not reformatted mid-edit. */
    val linePrices: Map<String, String> = emptyMap(),
    val totals: CartTotals = CartTotals(Money.ZERO, Money.ZERO, Money.ZERO),
    val discountPercent: Int = 0,
    /** Absolute discount in taka; combines with [discountPercent], capped at the subtotal. */
    val discountAmountText: String = "",
    val payment: PaymentMethod = PaymentMethod.CASH,
    val received: Money = Money.ZERO,
    val busy: Boolean = false,
    val message: PosMessage? = null,
    val customerName: String = "",
    /**
     * Catalogue hits for the query (21k Bangladesh brands) — shown below
     * your stock when it has no match, so you can add the medicine
     * straight from the sale tab instead of leaving the counter.
     */
    val catalogHits: List<CatalogItem> = emptyList(),
    val catalogSearching: Boolean = false,
) {
    val discountAmount: Money get() = Money.parse(discountAmountText)
    val changeDue: Money get() = CartCalculator.changeDue(totals.total, received)
    val creditRemainder: Money get() = CartCalculator.creditRemainder(totals.total, received)
    val itemCount: Int get() = CartCalculator.itemCount(cart)
}

class PosViewModel(
    private val inventory: InventoryRepository,
    private val sales: SalesRepository,
    private val sessionStore: SessionStore,
    private val catalog: CatalogRepository,
    private val customers: CustomersRepository,
) : ViewModel() {

    private val query = MutableStateFlow("")
    private val catalogHits = MutableStateFlow<List<CatalogItem>>(emptyList())
    private val catalogSearching = MutableStateFlow(false)
    private var catalogJob: Job? = null
    private val quantities = MutableStateFlow<Map<String, Int>>(emptyMap())

    /**
     * Per-line unit price overrides, keyed by medicine id.
     *
     * The counter haggles; the receipt has to show what was actually charged,
     * not the catalogue price. Cleared whenever the line leaves the cart.
     */
    private val linePrices = MutableStateFlow<Map<String, String>>(emptyMap())
    private val discountPercent = MutableStateFlow(0)
    private val discountAmountText = MutableStateFlow("")
    private val payment = MutableStateFlow(PaymentMethod.CASH)
    private val received = MutableStateFlow(Money.ZERO)
    private val customerName = MutableStateFlow("")
    private val busy = MutableStateFlow(false)
    private val message = MutableStateFlow<PosMessage?>(null)

    private val today: LocalDate get() = DhakaTime.today()

    /** Live phone book for credit-sale name suggestions. */
    val book = customers.customers

    /** Latest batch snapshot, so quantity limits can be checked synchronously. */
    @Volatile
    private var latestBatches: List<Batch> = emptyList()

    val state: StateFlow<PosUiState> = combine(
        combine(
            query,
            combine(inventory.observeMedicines(), inventory.observeBatches()) { medicines, batches ->
                medicines to batches
            },
            combine(quantities, linePrices) { wanted, prices -> CartEdits(wanted, prices) },
        ) { searchQuery, stockData, edits -> Triple(searchQuery, stockData, edits) },
        combine(
            combine(discountPercent, discountAmountText, payment, received) { percent, amountText, pay, cash ->
                DiscountCheckout(percent, amountText, pay, cash)
            },
            combine(message, busy, customerName) { msg, isBusy, customer ->
                Triple(msg, isBusy, customer)
            },
            combine(catalogHits, catalogSearching) { hits, searching -> hits to searching },
        ) { checkout, status, catalogData -> Triple(checkout, status, catalogData) },
    ) { search, checkoutData ->
        val (searchQuery, stockData, edits) = search
        val (checkout, status, catalogData) = checkoutData
        val (medicines, batches) = stockData
        val (wanted, prices) = edits
        val (discount, amountText, pay, cash) = checkout
        val (msg, isBusy, customer) = status
        val (hits, searching) = catalogData

        val items = buildItems(medicines, batches, searchQuery)
        val cart = buildCart(medicines, batches, wanted, prices)
        PosUiState(
            query = searchQuery,
            items = items,
            cart = cart,
            catalogHits = if (items.isEmpty() && searchQuery.isNotBlank()) hits else emptyList(),
            catalogSearching = searching && items.isEmpty() && searchQuery.isNotBlank(),
            linePrices = prices,
            totals = CartCalculator.totals(
                cart,
                discountAmount = Money.parse(amountText),
                discountPercent = discount,
            ),
            discountPercent = discount,
            discountAmountText = amountText,
            payment = pay,
            received = cash,
            busy = isBusy,
            message = msg,
            customerName = customer,
        )
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), PosUiState())

    private data class DiscountCheckout(
        val percent: Int,
        val amountText: String,
        val pay: PaymentMethod,
        val cash: Money,
    )

    private data class CartEdits(
        val quantities: Map<String, Int>,
        val prices: Map<String, String>,
    )

    fun onQueryChange(value: String) {
        query.value = value
        // Catalogue lookup runs alongside your stock: if your shelves have
        // no match, the 21k-brand fallback is already waiting below.
        catalogJob?.cancel()
        if (value.trim().length < CatalogRepository.MIN_QUERY_LENGTH) {
            catalogHits.value = emptyList()
            catalogSearching.value = false
            return
        }
        catalogJob = viewModelScope.launch {
            catalogSearching.value = true
            delay(280)
            catalog.search(value).fold(
                onSuccess = { items ->
                    catalogHits.value = items
                    catalogSearching.value = false
                },
                onFailure = {
                    catalogHits.value = emptyList()
                    catalogSearching.value = false
                },
            )
        }
    }

    fun onDiscountChange(value: String) {
        discountPercent.value = value.filter { it.isDigit() }.take(2).toIntOrNull()?.coerceIn(0, 100) ?: 0
    }

    /** Absolute discount in taka, for when the counter gives a flat ৳ off instead of a percentage. */
    fun onDiscountAmountChange(value: String) {
        discountAmountText.value = sanitizeAmount(value)
    }

    /** Digits and at most one dot with two decimals — nothing else reaches Money. */
    private fun sanitizeAmount(value: String): String {
        val cleaned = value.filter { it.isDigit() || it == '.' }
        val firstDot = cleaned.indexOf('.')
        if (firstDot < 0) return cleaned.take(7)
        val head = cleaned.substring(0, firstDot + 1)
        val tail = cleaned.substring(firstDot + 1).filter { it.isDigit() }.take(2)
        return (head + tail).take(9)
    }

    /**
     * Unit price for a single line, overriding the catalogue default.
     * An empty entry falls back to the catalogue price.
     */
    fun onLinePriceChange(medicineId: String, text: String) {
        linePrices.value = if (text.isBlank()) {
            linePrices.value - medicineId
        } else {
            linePrices.value + (medicineId to sanitizeAmount(text))
        }
    }

    fun onPaymentChange(method: PaymentMethod) {
        payment.value = method
    }

    fun onReceivedChange(text: String) {
        received.value = Money.parse(text)
    }

    fun onCustomerChange(name: String) {
        customerName.value = name.take(60)
    }

    fun consumeMessage() {
        message.value = null
    }

    /** Adds one unit, refusing politely when the shelf is empty or expired. */
    fun add(medicineId: String) {
        val current = state.value
        val desired = (quantities.value[medicineId] ?: 0) + 1
        if (desired > planAvailable(medicineId)) {
            message.value = PosMessage.InsufficientStock
            return
        }
        message.value = null
        quantities.value = quantities.value + (medicineId to desired)
    }

    fun setQuantity(medicineId: String, quantity: Int) {
        if (quantity <= 0) {
            quantities.value = quantities.value - medicineId
            return
        }
        val capped = quantity.coerceAtMost(planAvailable(medicineId))
        if (capped < quantity) message.value = PosMessage.InsufficientStock
        quantities.value = quantities.value + (medicineId to capped)
    }

    /** Drops the whole line and any price the counter had negotiated for it. */
    fun remove(medicineId: String) {
        quantities.value = quantities.value - medicineId
        linePrices.value = linePrices.value - medicineId
    }

    /** One unit less; the line disappears at zero instead of needing a delete. */
    fun decrement(medicineId: String) {
        val current = quantities.value[medicineId] ?: return
        setQuantity(medicineId, current - 1)
    }

    fun clearCart() {
        quantities.value = emptyMap()
        linePrices.value = emptyMap()
        discountPercent.value = 0
        discountAmountText.value = ""
        received.value = Money.ZERO
        customerName.value = ""
    }

    /**
     * Records the sale. Online it is written straight through; offline the same
     * FEFO plan is applied locally and queued, so the receipt is correct either
     * way and replay can never double-book.
     */
    fun checkout() {
        val current = state.value
        if (current.cart.isEmpty() || busy.value) return
        // A baki sale without a name is uncollectable — that is how shops
        // lose money. Require the customer before the sale is booked.
        if (payment.value == PaymentMethod.CREDIT && current.customerName.isBlank()) {
            message.value = PosMessage.CustomerRequired
            return
        }
        busy.value = true
        viewModelScope.launch {
            val deviceId = sessionStore.ensureDeviceId()
            val invoice = sales.nextInvoiceNumber(deviceId)
            sales.recordSale(
                lines = current.cart,
                paymentMethod = payment.value,
                note = "",
                invoiceNumber = invoice,
                discount = current.totals.discount,
                // A credit sale books its baki entry in the same Firestore
                // batch — the due can never exist without the sale or vice versa.
                customerName = if (payment.value == PaymentMethod.CREDIT) {
                    current.customerName.trim()
                } else {
                    ""
                },
            ).fold(
                onSuccess = { record ->
                    CloudServices.track(
                        "sale_recorded",
                        "payment" to payment.value.name.lowercase(),
                        "queued" to record.queued.toString(),
                    )
                    // A credit name not in the book is filed the moment the
                    // sale is booked — the first baki is never unreminderable.
                    if (payment.value == PaymentMethod.CREDIT && current.customerName.isNotBlank()) {
                        viewModelScope.launch { customers.ensureKnown(current.customerName) }
                    }
                    val receipt = buildReceipt(invoice, current, record.soldAtMillis)
                    message.value = if (record.queued) {
                        PosMessage.Queued(receipt)
                    } else {
                        PosMessage.Recorded(invoice, receipt)
                    }
                    clearCart()
                },
                onFailure = { error ->
                    message.value = when (error) {
                        is AppError.Validation -> PosMessage.InsufficientStock
                        // The cart is still intact here (clearCart only runs on
                        // success), so even the retry-later path can hand the
                        // customer a receipt for what they just bought.
                        is AppError.Network -> PosMessage.Queued(
                            buildReceipt(invoice, current, System.currentTimeMillis()),
                        )
                        else -> PosMessage.Failed(error.message ?: "error")
                    }
                },
            )
            busy.value = false
        }
    }

    // ---- Cart construction ------------------------------------------------

    /**
     * Snapshots the sale for sharing. Built before the cart clears and from
     * the same totals the customer agreed to, so the receipt can never differ
     * from what was charged — online or offline, connected or free mode.
     */
    private suspend fun buildReceipt(
        invoice: String,
        checkout: PosUiState,
        soldAtMillis: Long,
    ): Receipt {
        val totals = checkout.totals
        return Receipt(
            invoice = invoice,
            soldAtMillis = soldAtMillis,
            shopName = sessionStore.current().shopName,
            lines = checkout.cart.map { line ->
                ReceiptLine(
                    name = line.medicineName,
                    quantity = line.quantity,
                    unitPrice = line.unitPrice,
                    lineTotal = line.unitPrice * line.quantity,
                )
            },
            subtotal = totals.subtotal,
            discount = totals.discount,
            total = totals.total,
            paymentMethod = checkout.payment,
            received = checkout.received,
            changeDue = CartCalculator.changeDue(totals.total, checkout.received),
            credit = if (checkout.payment == PaymentMethod.CREDIT) totals.total else Money.ZERO,
            customerName = checkout.customerName,
        )
    }

    private fun planAvailable(medicineId: String): Int = latestBatches
        .filter { it.medicineId == medicineId && it.quantityAvailable > 0 }
        .filter { ExpiryRules.isSellable(it.expiryDate, today) }
        .sumOf { it.quantityAvailable }

    private fun buildItems(
        medicines: List<Medicine>,
        batches: List<Batch>,
        searchQuery: String,
    ): List<PosItem> {
        latestBatches = batches
        val byMedicine = batches.groupBy { it.medicineId }
        // Ranked live search over the whole pharmacy: every keystroke filters
        // every medicine (brand, generic, strength, form, maker, barcode), so
        // the right hit is never hidden behind a result cap.
        return MedicineSearch.rankActive(medicines, searchQuery)
            .map { medicine ->
                val own = byMedicine[medicine.id].orEmpty()
                val inStock = own.filter { it.quantityAvailable > 0 }
                val sellable = inStock.filter { ExpiryRules.isSellable(it.expiryDate, today) }
                PosItem(
                    medicine = medicine,
                    available = inStock.sumOf { it.quantityAvailable },
                    sellableAvailable = sellable.sumOf { it.quantityAvailable },
                    nearestExpiry = sellable.minOfOrNull { it.expiryDate },
                    price = medicine.defaultSellingPrice,
                )
            }
            .toList()
    }

    /** Re-derives cart lines with FEFO so displayed batches match what is sold. */
    private fun buildCart(
        medicines: List<Medicine>,
        batches: List<Batch>,
        wanted: Map<String, Int>,
        prices: Map<String, String>,
    ): List<CartLine> {
        val byId = medicines.associateBy { it.id }
        val byMedicine = batches.groupBy { it.medicineId }
        val lines = mutableListOf<CartLine>()
        for ((medicineId, quantity) in wanted) {
            val medicine = byId[medicineId] ?: continue
            val stock = byMedicine[medicineId].orEmpty().map { batch ->
                BatchStock(
                    batchId = batch.id,
                    batchNumber = batch.batchNumber,
                    expiryDate = batch.expiryDate,
                    quantityAvailable = batch.quantityAvailable,
                    unitCost = batch.unitCost,
                    sellingPrice = batch.sellingPrice,
                )
            }
            when (val plan = FefoPlanner.plan(stock, quantity, today)) {
                is FefoResult.Allocated -> lines += CartLine(
                    medicineId = medicineId,
                    medicineName = medicine.displayName,
                    // What the counter actually charged for this line, falling
                    // back to the catalogue price when no override was entered.
                    unitPrice = prices[medicineId]
                        ?.let { Money.parseOrNull(it) }
                        ?: medicine.defaultSellingPrice,
                    quantity = quantity,
                    allocations = plan.allocations,
                )
                is FefoResult.InsufficientStock -> Unit
            }
        }
        return lines.sortedBy { it.medicineName }
    }
}
