package com.lipon.rakho.feature.dashboard

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.lipon.rakho.core.domain.SalesAnalytics
import com.lipon.rakho.core.model.DashboardStats
import com.lipon.rakho.core.model.PaymentMethod
import com.lipon.rakho.core.model.Sale
import com.lipon.rakho.core.money.Money
import com.lipon.rakho.core.time.DhakaTime
import com.lipon.rakho.core.time.SalesBucket
import com.lipon.rakho.core.time.SalesRange
import com.lipon.rakho.core.time.SalesRanges
import com.lipon.rakho.data.repo.AlertSnapshot
import com.lipon.rakho.data.repo.DuesRepository
import com.lipon.rakho.data.repo.InventoryRepository
import com.lipon.rakho.data.repo.SalesRepository
import com.lipon.rakho.data.repo.SyncRepository
import com.lipon.rakho.data.repo.SyncStatus
import com.lipon.rakho.data.session.SessionStore
import kotlinx.coroutines.flow.MutableStateFlow
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
    val duesTotal: Money = Money.ZERO,
    val duesCount: Int = 0,
    /** Oldest-first dues, oldest due date included for aging display. */
    val duesOldestMillis: Long = 0L,
    /** The pulse granularity the shop picked on the card (default: hourly). */
    val pulseRange: SalesRange = SalesRange.LAST_24H,
    /** Chart buckets for the selected pulse range, oldest first. */
    val pulseBuckets: List<SalesBucket> = emptyList(),
    /** Sold total across the selected pulse range. */
    val pulseTotal: Money = Money.ZERO,
    /** Today's true profit from FEFO costs; null when no cost-known sales. */
    val todayProfitTrue: Money? = null,
    /** Today's margin % over cost-known revenue; null when not computable. */
    val todayMarginPct: Double? = null,
)

class DashboardViewModel(
    private val inventory: InventoryRepository,
    private val sync: SyncRepository,
    sessionStore: SessionStore,
    private val dues: DuesRepository,
    private val salesRepo: SalesRepository,
) : ViewModel() {

    private val pulseRange = MutableStateFlow(SalesRange.LAST_24H)

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
        pulseRange,
    ) { core, session, books, range ->
        val (stats, alerts, syncStatus) = core
        val (duesSummary, sales) = books
        val today = DhakaTime.today()
        val todaySales = SalesRanges.filterForRange(sales, SalesRange.LAST_24H, today)
        val (profit, knownRevenue) = SalesAnalytics.profitAndKnownRevenue(todaySales)
        DashboardUiState(
            shopName = session.shopName,
            stats = stats,
            alerts = alerts,
            sync = syncStatus,
            duesTotal = duesSummary.total,
            duesCount = duesSummary.customerCount,
            duesOldestMillis = duesSummary.entries.firstOrNull()?.dueSinceMillis ?: 0L,
            pulseRange = range,
            pulseBuckets = SalesRanges.buckets(sales, range, today),
            pulseTotal = SalesRanges.filterForRange(sales, range, today)
                .fold(Money.ZERO) { acc, sale -> acc + sale.total },
            todayProfitTrue = if (knownRevenue.paisa > 0) profit else null,
            todayMarginPct = if (knownRevenue.paisa > 0) {
                profit.paisa * 100.0 / knownRevenue.paisa
            } else {
                null
            },
        )
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), DashboardUiState())

    fun onPulseRangeChange(range: SalesRange) {
        pulseRange.value = range
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
