package com.lipon.rakho.feature.dashboard

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.lipon.rakho.core.model.DashboardStats
import com.lipon.rakho.core.model.PlanTier
import com.lipon.rakho.core.money.Money
import com.lipon.rakho.core.model.SubscriptionState
import com.lipon.rakho.data.repo.AlertSnapshot
import com.lipon.rakho.data.repo.BillingRepository
import com.lipon.rakho.data.repo.DuesRepository
import com.lipon.rakho.data.repo.InventoryRepository
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
    val subscription: SubscriptionState = SubscriptionState(),
    val isLocalOnly: Boolean = false,
    val duesTotal: Money = Money.ZERO,
    val duesCount: Int = 0,
) {
    val showProUpsell: Boolean get() = subscription.tier == PlanTier.FREE

    /** The gentle upsell: connect a key, shown only in the free local mode. */
    val showConnectCard: Boolean get() = isLocalOnly
}

class DashboardViewModel(
    private val inventory: InventoryRepository,
    private val sync: SyncRepository,
    sessionStore: SessionStore,
    private val billing: BillingRepository,
    private val dues: DuesRepository,
) : ViewModel() {

    private val subscription = MutableStateFlow(SubscriptionState())

    val state: StateFlow<DashboardUiState> = combine(
        combine(
            inventory.observeDashboard(),
            inventory.observeAlerts(),
            sync.status,
        ) { stats, alerts, syncStatus -> Triple(stats, alerts, syncStatus) },
        combine(sessionStore.state, subscription) { session, sub -> session to sub },
        dues.observeDues(),
    ) { core, sessionSub, duesSummary ->
        val (stats, alerts, syncStatus) = core
        val (session, sub) = sessionSub
        DashboardUiState(
            shopName = session.shopName,
            stats = stats,
            alerts = alerts,
            sync = syncStatus,
            subscription = sub,
            isLocalOnly = session.localOnly,
            duesTotal = duesSummary.total,
            duesCount = duesSummary.customerCount,
        )
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), DashboardUiState())

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
            billing.entitlement().onSuccess { subscription.value = it }
        }
    }
}
