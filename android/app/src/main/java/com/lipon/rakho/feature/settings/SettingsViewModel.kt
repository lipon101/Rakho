package com.lipon.rakho.feature.settings

import android.content.Context
import android.os.Build
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.lipon.rakho.core.model.PharmacyProfile
import com.lipon.rakho.data.firebase.AuthRepository
import com.lipon.rakho.data.firebase.FirestoreRepository
import com.lipon.rakho.data.repo.InventoryRepository
import com.lipon.rakho.data.repo.SyncPhase
import com.lipon.rakho.data.repo.SyncRepository
import com.lipon.rakho.data.repo.SyncStatus
import com.lipon.rakho.data.session.SessionState
import com.lipon.rakho.data.session.SessionStore
import com.lipon.rakho.work.ReminderScheduler
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
    val accountEmail: String = "",
    val saving: Boolean = false,
    val saved: Boolean = false,
    /** True while "delete everything" runs; the UI locks the button on it. */
    val deleting: Boolean = false,
    val deleteFailed: Boolean = false,
)

/**
 * Settings for the Firebase-only build: shop identity, sync status,
 * notifications, language, and the account itself (sign out / delete).
 * There is no API key, server URL or "connect" flow anymore — the signed-in
 * Firebase account *is* the pharmacy's cloud connection.
 */
class SettingsViewModel(
    private val sessionStore: SessionStore,
    private val sync: SyncRepository,
    private val authRepo: AuthRepository,
    private val firestoreRepo: FirestoreRepository,
    private val inventory: InventoryRepository,
) : ViewModel() {

    private val saving = MutableStateFlow(false)
    private val saved = MutableStateFlow(false)
    private val deleting = MutableStateFlow(false)
    private val deleteFailed = MutableStateFlow(false)

    val state: StateFlow<SettingsUiState> = combine(
        inventory.observeProfile(),
        combine(sessionStore.state, sync.status) { session, syncStatus -> session to syncStatus },
        combine(saving, saved) { isSaving, wasSaved -> isSaving to wasSaved },
        combine(deleting, deleteFailed) { isDeleting, failed -> isDeleting to failed },
    ) { profile, sessionAndSync, saveFlags, deleteFlags ->
        val (session, syncStatus) = sessionAndSync
        val (isSaving, wasSaved) = saveFlags
        val (isDeleting, failed) = deleteFlags
        SettingsUiState(
            profile = profile ?: PharmacyProfile(name = session.shopName),
            session = session,
            sync = syncStatus,
            accountEmail = authRepo.email,
            saving = isSaving,
            saved = wasSaved,
            deleting = isDeleting,
            deleteFailed = failed,
        )
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), SettingsUiState())

    init {
        viewModelScope.launch { inventory.refreshProfile() }
    }

    fun consumeSaved() {
        saved.value = false
    }

    fun saveProfile(name: String, phone: String, address: String) {
        if (saving.value) return
        saving.value = true
        viewModelScope.launch {
            inventory.updateProfile(name, phone, address)
                .onSuccess { saved.value = true }
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

    /** Light-first brand, but the shopkeeper decides: system / light / dark. */
    fun setThemeMode(mode: String) {
        viewModelScope.launch { sessionStore.updateThemeMode(mode) }
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

    /** Signs out of Firebase; the shop's cloud data stays intact. */
    fun signOut(onDone: () -> Unit) {
        viewModelScope.launch {
            runCatching { authRepo.signOut() }
            onDone()
        }
    }

    /**
     * "Delete my account and data": wipes every Firestore document this
     * pharmacy owns, then removes the auth account, then resets this device.
     * Deletion runs even if the auth step fails (e.g. Firebase's recent-login
     * requirement) so the shop's data is never left behind.
     */
    fun deleteAccountAndData(onDone: () -> Unit) {
        if (deleting.value) return
        deleting.value = true
        viewModelScope.launch {
            val dataWiped = runCatching { firestoreRepo.deleteAllData() }.isSuccess
            val accountGone = dataWiped &&
                authRepo.deleteAccount() is com.lipon.rakho.data.firebase.AuthResult.Success
            runCatching { sessionStore.reset() }
            deleting.value = false
            deleteFailed.value = !(dataWiped && accountGone)
            onDone()
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
}
