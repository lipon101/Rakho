package bd.rakho.pharmacy.feature.dashboard

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import bd.rakho.pharmacy.core.model.DashboardStats
import bd.rakho.pharmacy.core.model.PlanTier
import bd.rakho.pharmacy.core.model.SubscriptionState
import bd.rakho.pharmacy.data.repo.AlertSnapshot
import bd.rakho.pharmacy.data.repo.BillingRepository
import bd.rakho.pharmacy.data.repo.InventoryRepository
import bd.rakho.pharmacy.data.repo.SyncRepository
import bd.rakho.pharmacy.data.repo.SyncStatus
import bd.rakho.pharmacy.data.session.SessionStore
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
) {
    val showProUpsell: Boolean get() = subscription.tier == PlanTier.FREE
}

class DashboardViewModel(
    private val inventory: InventoryRepository,
    private val sync: SyncRepository,
    sessionStore: SessionStore,
    private val billing: BillingRepository,
) : ViewModel() {

    private val subscription = MutableStateFlow(SubscriptionState())

    val state: StateFlow<DashboardUiState> = combine(
        inventory.observeDashboard(),
        inventory.observeAlerts(),
        sync.status,
        sessionStore.state,
        subscription,
    ) { stats, alerts, syncStatus, session, sub ->
        DashboardUiState(
            shopName = session.shopName,
            stats = stats,
            alerts = alerts,
            sync = syncStatus,
            subscription = sub,
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
