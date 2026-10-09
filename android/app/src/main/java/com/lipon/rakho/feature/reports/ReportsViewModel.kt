package com.lipon.rakho.feature.reports

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.lipon.rakho.core.domain.PaymentSlice
import com.lipon.rakho.core.domain.RangeAnalytics
import com.lipon.rakho.core.domain.SalesAnalytics
import com.lipon.rakho.core.domain.SlowMover
import com.lipon.rakho.core.model.Sale
import com.lipon.rakho.core.money.Money
import com.lipon.rakho.core.money.MoneyFormat
import com.lipon.rakho.core.time.DhakaTime
import com.lipon.rakho.core.time.SalesBucket
import com.lipon.rakho.core.time.SalesRange
import com.lipon.rakho.core.time.SalesRanges
import com.lipon.rakho.data.repo.DuesRepository
import com.lipon.rakho.data.repo.InventoryRepository
import com.lipon.rakho.data.repo.SalesRepository
import com.lipon.rakho.data.session.SessionStore
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

enum class ReportPeriod { TODAY, WEEK, MONTH }

/** Maps the legacy 3-period chip onto the minimal range for old callers. */
fun ReportPeriod.toSalesRange(): SalesRange = when (this) {
    ReportPeriod.TODAY -> SalesRange.LAST_24H
    ReportPeriod.WEEK -> SalesRange.LAST_7D
    ReportPeriod.MONTH -> SalesRange.LAST_30D
}

data class TopItem(
    val name: String,
    val quantity: Int,
    val amount: Money,
)

data class ReportsUiState(
    val period: SalesRange = SalesRange.LAST_7D,
    val analytics: RangeAnalytics = RangeAnalytics(
        total = Money.ZERO,
        billCount = 0,
        itemCount = 0,
        profit = Money.ZERO,
        marginPct = null,
        previousTotal = null,
        deltaPct = null,
        paymentSlices = emptyList(),
        slowMovers = emptyList(),
    ),
    val topItems: List<TopItem> = emptyList(),
    /** Chart buckets across the selected range (24H → hourly, long ranges → weekly/monthly). */
    val dailySeries: List<SalesBucket> = emptyList(),
) {
    val totalSales: Money get() = analytics.total
    val billCount: Int get() = analytics.billCount
    val itemCount: Int get() = analytics.itemCount
    val averageBill: Money
        get() = if (billCount == 0) Money.ZERO else Money(totalSales.paisa / billCount)
}

class ReportsViewModel(
    private val sales: SalesRepository,
    private val inventory: InventoryRepository,
    private val dues: DuesRepository,
    @Suppress("unused") private val sessionStore: SessionStore,
) : ViewModel() {

    private val period = MutableStateFlow(SalesRange.LAST_7D)
    private val allSales = MutableStateFlow<List<Sale>>(emptyList())

    val state: StateFlow<ReportsUiState> = combine(
        allSales,
        period,
        inventory.observeBatches(),
        inventory.observeMedicines(),
    ) { salesList, activePeriod, batches, medicines ->
        val today = DhakaTime.today()
        val filtered = SalesRanges.filterForRange(salesList, activePeriod, today)
        ReportsUiState(
            period = activePeriod,
            analytics = SalesAnalytics.analyze(salesList, batches, medicines, activePeriod, today),
            topItems = topItems(filtered),
            dailySeries = SalesRanges.buckets(salesList, activePeriod, today),
        )
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), ReportsUiState())

    init {
        viewModelScope.launch { sales.observeSales().collect { allSales.value = it } }
    }

    fun onPeriodChange(value: SalesRange) {
        period.value = value
    }

    /** Backwards-compatible overload for callers still on the legacy chips. */
    fun onPeriodChange(value: ReportPeriod) {
        period.value = value.toSalesRange()
    }

    /**
     * CSV of the current period, in the shop's own money and date format, so it
     * can be opened in Excel and handed to an accountant or supplier as-is.
     */
    fun buildCsv(): String {
        val today = DhakaTime.today()
        val rows = SalesRanges.filterForRange(allSales.value, period.value, today)
        val builder = StringBuilder("Invoice,Date,Payment,Items,Total BDT\n")
        rows.forEach { sale ->
            builder
                .append(escape(sale.invoiceNumber)).append(',')
                .append(sale.soldAt.atZone(DhakaTime.ZONE).toLocalDate()).append(',')
                .append(escape(sale.paymentMethod.name.lowercase())).append(',')
                .append(sale.lines.sumOf { it.quantity }).append(',')
                .append(MoneyFormat.format(sale.total, withDecimals = true, symbol = "")).append('\n')
        }
        return builder.toString()
    }

    private fun topItems(salesList: List<Sale>): List<TopItem> {
        val byName = mutableMapOf<String, TopItem>()
        salesList.forEach { sale ->
            sale.lines.forEach { line ->
                val existing = byName[line.medicineName]
                byName[line.medicineName] = TopItem(
                    name = line.medicineName,
                    quantity = (existing?.quantity ?: 0) + line.quantity,
                    amount = (existing?.amount ?: Money.ZERO) + (line.unitPrice * line.quantity),
                )
            }
        }
        return byName.values.sortedByDescending { it.quantity }.take(10)
    }

    private fun escape(value: String): String =
        if (value.contains(',') || value.contains('"')) {
            "\"" + value.replace("\"", "\"\"") + "\""
        } else {
            value
        }
}
