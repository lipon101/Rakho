package bd.rakho.pharmacy.feature.settings

import android.content.Context
import android.os.Build
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import bd.rakho.pharmacy.core.model.PharmacyProfile
import bd.rakho.pharmacy.core.model.SubscriptionState
import bd.rakho.pharmacy.core.result.AppError
import bd.rakho.pharmacy.data.repo.InventoryRepository
import bd.rakho.pharmacy.data.repo.SyncPhase
import bd.rakho.pharmacy.data.repo.SyncRepository
import bd.rakho.pharmacy.data.repo.SyncStatus
import bd.rakho.pharmacy.data.session.SessionState
import bd.rakho.pharmacy.data.session.SessionStore
import bd.rakho.pharmacy.di.AppContainer
import bd.rakho.pharmacy.work.ReminderScheduler
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

data class SettingsUiState(
    val profile: PharmacyProfile = PharmacyProfile(name = ""),
    val session: SessionState = SessionState(),
    val sync: SyncStatus = SyncStatus(),
    val subscription: SubscriptionState = SubscriptionState(),
    val showApiKey: Boolean = false,
    val saving: Boolean = false,
    val saved: Boolean = false,
)

class SettingsViewModel(
    private val sessionStore: SessionStore,
    private val sync: SyncRepository,
    private val container: AppContainer,
    private val inventory: InventoryRepository,
) : ViewModel() {

    private val showApiKey = MutableStateFlow(false)
    private val saving = MutableStateFlow(false)
    private val saved = MutableStateFlow(false)
    private val subscription = MutableStateFlow(SubscriptionState())

    val state: StateFlow<SettingsUiState> = combine(
        inventory.observeProfile(),
        combine(sessionStore.state, sync.status) { session, syncStatus -> session to syncStatus },
        combine(showApiKey, saving) { show, isSaving -> show to isSaving },
        combine(saved, subscription) { wasSaved, sub -> wasSaved to sub },
    ) { profile, syncData, visibility, status ->
        val (session, syncStatus) = syncData
        val (show, isSaving) = visibility
        val (wasSaved, sub) = status
        SettingsUiState(
            profile = profile ?: PharmacyProfile(name = session.shopName),
            session = session,
            sync = syncStatus,
            subscription = sub,
            showApiKey = show,
            saving = isSaving,
            saved = wasSaved,
        )
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), SettingsUiState())

    init {
        viewModelScope.launch { inventory.refreshProfile() }
        viewModelScope.launch { container.billing.entitlement().onSuccess { subscription.value = it } }
    }

    fun toggleApiKeyVisibility() {
        showApiKey.value = !showApiKey.value
    }

    fun saveProfile(name: String, phone: String, address: String) {
        if (saving.value) return
        saving.value = true
        viewModelScope.launch {
            inventory.updateProfile(name, phone, address)
                .onSuccess {
                    sessionStore.updateShopName(name)
                    saved.value = true
                }
            saving.value = false
        }
    }

    fun syncNow() {
        viewModelScope.launch { sync.syncNow() }
    }

    fun setNotifications(context: Context, enabled: Boolean) {
        viewModelScope.launch {
            sessionStore.updateNotifications(enabled)
            if (enabled) {
                ReminderScheduler.schedule(context)
            } else {
                ReminderScheduler.cancel(context)
            }
        }
    }

    /** Applies a per-app language on Android 13+, where the platform supports it. */
    fun setLanguage(context: Context, languageCode: String) {
        viewModelScope.launch {
            sessionStore.updateLanguage(languageCode)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                val manager = context.getSystemService(android.app.LocaleManager::class.java)
                val locales = if (languageCode.isBlank()) {
                    android.os.LocaleList.getEmptyLocaleList()
                } else {
                    android.os.LocaleList(java.util.Locale.forLanguageTag(languageCode))
                }
                manager?.applicationLocales = locales
            }
        }
    }

    /** Points the app at a self-hosted Rakho server (enterprise/distributor use). */
    fun setServerUrl(url: String) {
        viewModelScope.launch {
            sessionStore.updateBaseUrl(url)
            container.reconfigureApi(url)
            sync.syncNow()
        }
    }

    fun disconnect() {
        viewModelScope.launch {
            sessionStore.disconnect()
            container.cache.clearAll()
        }
    }

    /** Human-readable sync failure reason, or null when everything is fine. */
    fun syncError(): String? {
        val status = state.value.sync
        return when (status.phase) {
            SyncPhase.ERROR, SyncPhase.OFFLINE -> status.lastError
            else -> null
        }
    }

    fun isUnauthorized(error: AppError?): Boolean = error is AppError.Unauthorized
}
