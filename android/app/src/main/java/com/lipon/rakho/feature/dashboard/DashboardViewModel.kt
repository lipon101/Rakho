package com.lipon.rakho.feature.dashboard

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.lipon.rakho.core.model.DashboardStats
import com.lipon.rakho.core.model.DayTotal
import com.lipon.rakho.core.model.PaymentMethod
import com.lipon.rakho.core.model.Sale
import com.lipon.rakho.core.money.Money
import com.lipon.rakho.core.time.DhakaTime
import com.lipon.rakho.data.repo.AlertSnapshot
import com.lipon.rakho.data.repo.DuesRepository
import com.lipon.rakho.data.repo.InventoryRepository
import com.lipon.rakho.data.repo.SalesRepository
import com.lipon.rakho.data.repo.SyncRepository
import com.lipon.rakho.data.repo.SyncStatus
import com.lipon.rakho.data.session.SessionStore
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

data class DashboardUiState(
    val shopName: String = "",
    val stats: DashboardStats = DashboardStats(),
    val alerts: AlertSnapshot = AlertSnapshot(),
    val sync: SyncStatus = SyncStatus(),
    val isLocalOnly: Boolean = false,
    val duesTotal: Money = Money.ZERO,
    val duesCount: Int = 0,
    /** Oldest-first dues, oldest due date included for aging display. */
    val duesOldestMillis: Long = 0L,
    /** Total sold per day, oldest first, covering the last 7 Dhaka days. */
    val weekSeries: List<DayTotal> = emptyList(),
    /** Sold total per payment method over the same 7 days. */
    val paymentMix: Map<PaymentMethod, Money> = emptyMap(),
) {
    /** The gentle upsell: connect a key, shown only in the free local mode. */
    val showConnectCard: Boolean get() = isLocalOnly
}

class DashboardViewModel(
    private val inventory: InventoryRepository,
    private val sync: SyncRepository,
    sessionStore: SessionStore,
    private val dues: DuesRepository,
    private val salesRepo: SalesRepository,
) : ViewModel() {

    val state: StateFlow<DashboardUiState> = combine(
        combine(
            inventory.observeDashboard(),
            inventory.observeAlerts(),
            sync.status,
        ) { stats, alerts, syncStatus -> Triple(stats, alerts, syncStatus) },
        sessionStore.state,
        combine(dues.observeDues(), salesRepo.observeSales()) { duesSummary, sales ->
            duesSummary to sales
        },
    ) { core, session, books ->
        val (stats, alerts, syncStatus) = core
        val (duesSummary, sales) = books
        val today = DhakaTime.today()
        DashboardUiState(
            shopName = session.shopName,
            stats = stats,
            alerts = alerts,
            sync = syncStatus,
            isLocalOnly = session.localOnly,
            duesTotal = duesSummary.total,
            duesCount = duesSummary.customerCount,
            duesOldestMillis = duesSummary.entries.firstOrNull()?.dueSinceMillis ?: 0L,
            weekSeries = weekSeries(sales, today),
            paymentMix = paymentMix(sales, today),
        )
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), DashboardUiState())

    /** Totals for the last 7 Dhaka calendar days, oldest first. */
    private fun weekSeries(sales: List<Sale>, today: java.time.LocalDate): List<DayTotal> {
        val zone = DhakaTime.ZONE
        val byDay = sales.groupBy { it.soldAt.atZone(zone).toLocalDate() }
        return (6 downTo 0).map { back ->
            val date = today.minusDays(back.toLong())
            DayTotal(
                date = date,
                total = (byDay[date] ?: emptyList())
                    .fold(Money.ZERO) { acc, sale -> acc + sale.total },
            )
        }
    }

    /** Per-method totals over the last 7 days, for the composition bar. */
    private fun paymentMix(sales: List<Sale>, today: java.time.LocalDate): Map<PaymentMethod, Money> {
        val cutoff = today.minusDays(6)
        return sales
            .filter { it.soldAt.atZone(DhakaTime.ZONE).toLocalDate() >= cutoff }
            .groupBy { it.paymentMethod }
            .mapValues { (_, daySales) ->
                daySales.fold(Money.ZERO) { acc, sale -> acc + sale.total }
            }
    }

    init {
        // [SyncRepository.pendingCount] is the flow that keeps the queued-work
        // counter on [SyncStatus] up to date, so it has to stay collected.
        viewModelScope.launch { sync.pendingCount.collect {} }
        refresh()
    }

    /** Triggers a full sync (pull + flush of anything done offline). */
    fun refresh() {
        viewModelScope.launch {
            sync.syncNow()
        }
    }
}
