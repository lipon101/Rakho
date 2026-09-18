package bd.rakho.pharmacy.feature.reports

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import bd.rakho.pharmacy.core.model.Sale
import bd.rakho.pharmacy.core.money.Money
import bd.rakho.pharmacy.core.money.MoneyFormat
import bd.rakho.pharmacy.core.time.DhakaTime
import bd.rakho.pharmacy.data.repo.SalesRepository
import bd.rakho.pharmacy.data.session.SessionStore
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import java.time.LocalDate

enum class ReportPeriod { TODAY, WEEK, MONTH }

data class TopItem(
    val name: String,
    val quantity: Int,
    val amount: Money,
)

data class ReportsUiState(
    val period: ReportPeriod = ReportPeriod.TODAY,
    val totalSales: Money = Money.ZERO,
    val billCount: Int = 0,
    val itemCount: Int = 0,
    val topItems: List<TopItem> = emptyList(),
) {
    val averageBill: Money
        get() = if (billCount == 0) Money.ZERO else Money(totalSales.paisa / billCount)
}

class ReportsViewModel(
    private val sales: SalesRepository,
    @Suppress("unused") private val sessionStore: SessionStore,
) : ViewModel() {

    private val period = MutableStateFlow(ReportPeriod.TODAY)
    private val allSales = MutableStateFlow<List<Sale>>(emptyList())

    val state: StateFlow<ReportsUiState> = combine(allSales, period) { salesList, activePeriod ->
        val filtered = filterForPeriod(salesList, activePeriod, DhakaTime.today())
        ReportsUiState(
            period = activePeriod,
            totalSales = filtered.fold(Money.ZERO) { acc, sale -> acc + sale.total },
            billCount = filtered.size,
            itemCount = filtered.sumOf { sale -> sale.lines.sumOf { it.quantity } },
            topItems = topItems(filtered),
        )
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), ReportsUiState())

    init {
        viewModelScope.launch { sales.observeSales().collect { allSales.value = it } }
        refresh()
    }

    fun onPeriodChange(value: ReportPeriod) {
        period.value = value
    }

    fun refresh() {
        viewModelScope.launch { sales.refreshSales() }
    }

    /**
     * CSV of the current period, in the shop's own money and date format, so it
     * can be opened in Excel and handed to an accountant or supplier as-is.
     */
    fun buildCsv(): String {
        val today = DhakaTime.today()
        val rows = filterForPeriod(allSales.value, period.value, today)
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

    private fun filterForPeriod(
        salesList: List<Sale>,
        activePeriod: ReportPeriod,
        today: LocalDate,
    ): List<Sale> = salesList.filter { sale ->
        val date = sale.soldAt.atZone(DhakaTime.ZONE).toLocalDate()
        when (activePeriod) {
            ReportPeriod.TODAY -> date == today
            ReportPeriod.WEEK -> !date.isBefore(today.minusDays(6))
            ReportPeriod.MONTH -> date.month == today.month && date.year == today.year
        }
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
