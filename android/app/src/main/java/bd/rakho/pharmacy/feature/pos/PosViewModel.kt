package bd.rakho.pharmacy.feature.pos

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import bd.rakho.pharmacy.core.domain.BatchStock
import bd.rakho.pharmacy.core.domain.CartCalculator
import bd.rakho.pharmacy.core.domain.CartTotals
import bd.rakho.pharmacy.core.domain.FefoPlanner
import bd.rakho.pharmacy.core.domain.FefoResult
import bd.rakho.pharmacy.core.model.Batch
import bd.rakho.pharmacy.core.model.CartLine
import bd.rakho.pharmacy.core.model.Medicine
import bd.rakho.pharmacy.core.model.PaymentMethod
import bd.rakho.pharmacy.core.money.Money
import bd.rakho.pharmacy.core.result.AppError
import bd.rakho.pharmacy.core.time.DhakaTime
import bd.rakho.pharmacy.core.time.ExpiryRules
import bd.rakho.pharmacy.data.repo.InventoryRepository
import bd.rakho.pharmacy.data.repo.SalesRepository
import bd.rakho.pharmacy.data.session.SessionStore
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
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
    data class Recorded(val invoice: String) : PosMessage
    data object Queued : PosMessage
    data class Failed(val text: String) : PosMessage
    data object InsufficientStock : PosMessage
}

data class PosUiState(
    val query: String = "",
    val items: List<PosItem> = emptyList(),
    val cart: List<CartLine> = emptyList(),
    val totals: CartTotals = CartTotals(Money.ZERO, Money.ZERO, Money.ZERO),
    val discountPercent: Int = 0,
    val payment: PaymentMethod = PaymentMethod.CASH,
    val received: Money = Money.ZERO,
    val busy: Boolean = false,
    val message: PosMessage? = null,
) {
    val changeDue: Money get() = CartCalculator.changeDue(totals.total, received)
    val creditRemainder: Money get() = CartCalculator.creditRemainder(totals.total, received)
    val itemCount: Int get() = CartCalculator.itemCount(cart)
}

class PosViewModel(
    private val inventory: InventoryRepository,
    private val sales: SalesRepository,
    private val sessionStore: SessionStore,
) : ViewModel() {

    private val query = MutableStateFlow("")
    private val quantities = MutableStateFlow<Map<String, Int>>(emptyMap())
    private val discountPercent = MutableStateFlow(0)
    private val payment = MutableStateFlow(PaymentMethod.CASH)
    private val received = MutableStateFlow(Money.ZERO)
    private val busy = MutableStateFlow(false)
    private val message = MutableStateFlow<PosMessage?>(null)

    private val today: LocalDate get() = DhakaTime.today()

    /** Latest batch snapshot, so quantity limits can be checked synchronously. */
    @Volatile
    private var latestBatches: List<Batch> = emptyList()

    val state: StateFlow<PosUiState> = combine(
        query,
        combine(inventory.observeMedicines(), inventory.observeBatches()) { medicines, batches ->
            medicines to batches
        },
        quantities,
        combine(discountPercent, payment, received) { discount, pay, cash ->
            Triple(discount, pay, cash)
        },
        combine(message, busy) { msg, isBusy -> msg to isBusy },
    ) { searchQuery, stockData, wanted, checkout, status ->
        val (medicines, batches) = stockData
        val (discount, pay, cash) = checkout
        val (msg, isBusy) = status

        val items = buildItems(medicines, batches, searchQuery)
        val cart = buildCart(medicines, batches, wanted)
        PosUiState(
            query = searchQuery,
            items = items,
            cart = cart,
            totals = CartCalculator.totals(cart, discountPercent = discount),
            discountPercent = discount,
            payment = pay,
            received = cash,
            busy = isBusy,
            message = msg,
        )
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), PosUiState())

    fun onQueryChange(value: String) {
        query.value = value
    }

    fun onDiscountChange(value: String) {
        discountPercent.value = value.filter { it.isDigit() }.take(2).toIntOrNull()?.coerceIn(0, 100) ?: 0
    }

    fun onPaymentChange(method: PaymentMethod) {
        payment.value = method
    }

    fun onReceivedChange(text: String) {
        received.value = Money.parse(text)
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

    fun remove(medicineId: String) {
        quantities.value = quantities.value - medicineId
    }

    fun clearCart() {
        quantities.value = emptyMap()
        discountPercent.value = 0
        received.value = Money.ZERO
    }

    /**
     * Records the sale. Online it is written straight through; offline the same
     * FEFO plan is applied locally and queued, so the receipt is correct either
     * way and replay can never double-book.
     */
    fun checkout() {
        val current = state.value
        if (current.cart.isEmpty() || busy.value) return
        busy.value = true
        viewModelScope.launch {
            val deviceId = sessionStore.ensureDeviceId()
            val invoice = sales.nextInvoiceNumber(deviceId)
            sales.recordSale(
                lines = current.cart,
                paymentMethod = payment.value,
                note = "",
                invoiceNumber = invoice,
            ).fold(
                onSuccess = { record ->
                    message.value = if (record.queued) PosMessage.Queued else PosMessage.Recorded(invoice)
                    clearCart()
                },
                onFailure = { error ->
                    message.value = when (error) {
                        is AppError.Validation -> PosMessage.InsufficientStock
                        is AppError.Network -> PosMessage.Queued
                        else -> PosMessage.Failed(error.message ?: "error")
                    }
                },
            )
            busy.value = false
        }
    }

    // ---- Cart construction ------------------------------------------------

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
        val needle = searchQuery.trim().lowercase()
        return medicines
            .asSequence()
            .filter { it.isActive }
            .filter { medicine ->
                needle.isEmpty() ||
                    medicine.brandName.lowercase().contains(needle) ||
                    medicine.genericName.lowercase().contains(needle) ||
                    medicine.strength.lowercase().contains(needle)
            }
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
            .take(80)
            .toList()
    }

    /** Re-derives cart lines with FEFO so displayed batches match what is sold. */
    private fun buildCart(
        medicines: List<Medicine>,
        batches: List<Batch>,
        wanted: Map<String, Int>,
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
                    unitPrice = medicine.defaultSellingPrice,
                    quantity = quantity,
                    allocations = plan.allocations,
                )
                is FefoResult.InsufficientStock -> Unit
            }
        }
        return lines.sortedBy { it.medicineName }
    }
}
