package com.lipon.rakho.feature.auth

import androidx.annotation.StringRes
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.lipon.rakho.R
import com.lipon.rakho.core.cloud.CloudServices
import com.lipon.rakho.data.firebase.AuthRepository
import com.lipon.rakho.data.firebase.AuthResult
import com.lipon.rakho.data.firebase.FirestoreRepository
import com.lipon.rakho.data.session.SessionStore
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

data class AuthUiState(
    val email: String = "",
    val password: String = "",
    val confirmPassword: String = "",
    val shopName: String = "",
    val isLogin: Boolean = true,
    val loading: Boolean = false,
    /** Resource id, so every message the counter reads can be in their language. */
    @StringRes val error: Int? = null,
    val success: Boolean = false,
    val showForgotPassword: Boolean = false,
    val resetEmailSent: Boolean = false,
)

class AuthViewModel(
    private val authRepo: AuthRepository,
    private val firestoreRepo: FirestoreRepository,
    private val sessionStore: SessionStore,
) : ViewModel() {

    private val _state = MutableStateFlow(AuthUiState())
    val state: StateFlow<AuthUiState> = _state.asStateFlow()

    fun onEmailChange(value: String) { _state.value = _state.value.copy(email = value, error = null) }
    fun onPasswordChange(value: String) { _state.value = _state.value.copy(password = value, error = null) }
    fun onConfirmPasswordChange(value: String) { _state.value = _state.value.copy(confirmPassword = value, error = null) }
    fun onShopNameChange(value: String) { _state.value = _state.value.copy(shopName = value, error = null) }
    fun toggleMode() { _state.value = _state.value.copy(isLogin = !_state.value.isLogin, error = null) }
    fun showForgotPassword() { _state.value = _state.value.copy(showForgotPassword = true, error = null) }
    fun dismissForgotPassword() { _state.value = _state.value.copy(showForgotPassword = false) }
    fun consumeError() { _state.value = _state.value.copy(error = null) }

    fun submit() {
        val s = _state.value
        if (s.loading) return

        // Basic validation
        if (s.email.isBlank()) {
            _state.value = s.copy(error = R.string.auth_err_email)
            return
        }
        if (s.password.isBlank()) {
            _state.value = s.copy(error = R.string.auth_err_password)
            return
        }
        if (!s.isLogin) {
            if (s.password.length < 6) {
                _state.value = s.copy(error = R.string.auth_err_short_password)
                return
            }
            if (s.password != s.confirmPassword) {
                _state.value = s.copy(error = R.string.auth_err_no_match)
                return
            }
            if (s.shopName.isBlank()) {
                _state.value = s.copy(error = R.string.auth_err_shop)
                return
            }
        }

        _state.value = s.copy(loading = true, error = null)

        viewModelScope.launch {
            val result = if (s.isLogin) {
                authRepo.signInWithEmail(s.email, s.password)
            } else {
                authRepo.createAccount(s.email, s.password)
            }

            when (result) {
                AuthResult.Success -> {
                    val shop = s.shopName.trim().ifBlank { "My Pharmacy" }
                    if (!s.isLogin) {
                        runCatching {
                            firestoreRepo.ensurePharmacyProfile(shop)
                            authRepo.updateDisplayName(shop)
                        }
                        sessionStore.updateShopName(shop)
                        CloudServices.track("sign_up")
                    } else {
                        // Ensure the profile document exists (created elsewhere
                        // or on an older build) without overwriting its name.
                        runCatching { firestoreRepo.ensurePharmacyProfile(shop) }
                        val cloudName =
                            runCatching { firestoreRepo.getProfile()?.name }.getOrNull().orEmpty()
                        sessionStore.updateShopName(cloudName.ifBlank { shop })
                        CloudServices.track("login")
                    }
                    val deviceId = sessionStore.ensureDeviceId()
                    CloudServices.identify(deviceId, authRepo.userId)
                    _state.value = _state.value.copy(loading = false, success = true)
                }
                AuthResult.EmailAlreadyInUse -> {
                    _state.value = _state.value.copy(
                        loading = false,
                        error = R.string.auth_err_email_exists,
                    )
                }
                AuthResult.InvalidCredentials -> {
                    _state.value = _state.value.copy(
                        loading = false,
                        error = if (s.isLogin) R.string.auth_err_invalid_creds else R.string.auth_err_invalid_email,
                    )
                }
                is AuthResult.Error -> {
                    // Firebase's own text is developer-facing; the shop gets
                    // the plain generic instead.
                    _state.value = _state.value.copy(loading = false, error = R.string.error_generic)
                }
            }
        }
    }

    fun sendPasswordReset() {
        val email = _state.value.email
        if (email.isBlank()) {
            _state.value = _state.value.copy(error = R.string.auth_err_email_first)
            return
        }
        viewModelScope.launch {
            _state.value = _state.value.copy(loading = true)
            when (val result = authRepo.sendPasswordReset(email)) {
                AuthResult.Success -> {
                    _state.value = _state.value.copy(
                        loading = false,
                        resetEmailSent = true,
                        showForgotPassword = false,
                    )
                }
                is AuthResult.Error -> {
                    _state.value = _state.value.copy(loading = false, error = R.string.error_generic)
                }
                else -> {
                    _state.value = _state.value.copy(
                        loading = false,
                        error = R.string.auth_err_reset_failed,
                    )
                }
            }
        }
    }
}
