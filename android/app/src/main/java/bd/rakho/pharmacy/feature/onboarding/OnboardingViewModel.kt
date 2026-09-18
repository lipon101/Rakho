package bd.rakho.pharmacy.feature.onboarding

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import bd.rakho.pharmacy.core.result.AppError
import bd.rakho.pharmacy.data.repo.InventoryRepository
import bd.rakho.pharmacy.data.repo.SyncRepository
import bd.rakho.pharmacy.data.session.SessionStore
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

data class OnboardingUiState(
    val shopName: String = "",
    val apiKey: String = "",
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

    /**
     * Saves the credentials and tries one sync. A rejected key is a hard error;
     * no connectivity is not — the pharmacy must be able to start working the
     * moment they install the app, even on a bad connection.
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

    /** Continue without a working connection; data syncs on the next attempt. */
    fun continueOffline() {
        val current = _state.value
        if (current.apiKey.isBlank() || current.shopName.isBlank()) {
            _state.value = current.copy(error = OnboardingError.EMPTY_FIELDS)
            return
        }
        viewModelScope.launch {
            sessionStore.saveCredentials(current.apiKey, current.shopName)
            _state.value = _state.value.copy(finished = true)
        }
    }
}
