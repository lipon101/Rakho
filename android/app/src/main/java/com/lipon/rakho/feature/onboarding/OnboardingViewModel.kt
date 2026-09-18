package com.lipon.rakho.feature.onboarding

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.lipon.rakho.core.result.AppError
import com.lipon.rakho.data.repo.InventoryRepository
import com.lipon.rakho.data.repo.SyncRepository
import com.lipon.rakho.data.session.SessionStore
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

data class OnboardingUiState(
    val shopName: String = "",
    val apiKey: String = "",
    val keyMode: Boolean = false,
    val busy: Boolean = false,
    val error: OnboardingError? = null,
    val finished: Boolean = false,
)

enum class OnboardingError { INVALID_KEY, NETWORK, EMPTY_FIELDS }

class OnboardingViewModel(
    private val sessionStore: SessionStore,
    private val sync: SyncRepository,
    private val inventory: InventoryRepository,
) : ViewModel() {

    private val _state = MutableStateFlow(OnboardingUiState())
    val state: StateFlow<OnboardingUiState> = _state.asStateFlow()

    fun onShopNameChange(value: String) {
        _state.value = _state.value.copy(shopName = value, error = null)
    }

    fun onApiKeyChange(value: String) {
        _state.value = _state.value.copy(apiKey = value, error = null)
    }

    /** Shows the optional API-key entry; the app is usable without it. */
    fun openKeyMode() {
        _state.value = _state.value.copy(keyMode = true, error = null)
    }

    fun closeKeyMode() {
        _state.value = _state.value.copy(keyMode = false, apiKey = "", error = null)
    }

    /**
     * Saves the credentials and tries one sync. A rejected key is a hard error;
     * no connectivity is not — everything recorded meanwhile is queued.
     */
    fun connect() {
        val current = _state.value
        if (current.apiKey.isBlank() || current.shopName.isBlank()) {
            _state.value = current.copy(error = OnboardingError.EMPTY_FIELDS)
            return
        }
        _state.value = current.copy(busy = true, error = null)
        viewModelScope.launch {
            sessionStore.saveCredentials(current.apiKey, current.shopName)
            val result = sync.syncNow()
            val error = result.exceptionOrNull()
            _state.value = when (error) {
                null -> _state.value.copy(busy = false, finished = true)
                is AppError.Unauthorized -> _state.value.copy(
                    busy = false,
                    error = OnboardingError.INVALID_KEY,
                )
                is AppError.Network -> _state.value.copy(busy = false, error = OnboardingError.NETWORK)
                else -> _state.value.copy(busy = false, error = OnboardingError.NETWORK)
            }
        }
    }

    /**
     * Starts the free local-only mode with just a pharmacy name. Everything
     * works on-device; connecting a key later uploads it all automatically.
     */
    fun startFree() {
        val current = _state.value
        if (current.shopName.isBlank()) {
            _state.value = current.copy(error = OnboardingError.EMPTY_FIELDS)
            return
        }
        viewModelScope.launch {
            sessionStore.startLocalOnly(current.shopName)
            _state.value = _state.value.copy(finished = true)
        }
    }
}
