package com.lipon.rakho.feature.addmedicine

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.lipon.rakho.core.model.CatalogItem
import com.lipon.rakho.core.money.Money
import com.lipon.rakho.core.result.AppError
import com.lipon.rakho.data.remote.dto.CreateMedicineRequest
import com.lipon.rakho.data.repo.CatalogRepository
import com.lipon.rakho.data.repo.InventoryRepository
import com.lipon.rakho.data.repo.WriteOutcome
import com.lipon.rakho.data.session.SessionStore
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

sealed interface AddMedicineMessage {
    data class Saved(val queued: Boolean) : AddMedicineMessage
    data object PriceRequired : AddMedicineMessage
    data object NameRequired : AddMedicineMessage
    data class Failed(val text: String) : AddMedicineMessage
}

data class AddMedicineUiState(
    val query: String = "",
    val results: List<CatalogItem> = emptyList(),
    val selected: CatalogItem? = null,
    val searching: Boolean = false,
    val manualMode: Boolean = false,
    val manualName: String = "",
    val manualGeneric: String = "",
    val manualStrength: String = "",
    val manualDosageForm: String = "",
    val priceText: String = "",
    val thresholdText: String = "10",
    val busy: Boolean = false,
    val message: AddMedicineMessage? = null,
) {
    val price: Money get() = Money.parse(priceText)
    val threshold: Int get() = thresholdText.filter { it.isDigit() }.toIntOrNull()?.coerceIn(1, 9999) ?: 10
    val canSave: Boolean get() = priceText.isNotBlank() && (selected != null || manualName.isNotBlank())
}

class AddMedicineViewModel(
    private val catalog: CatalogRepository,
    private val inventory: InventoryRepository,
    private val sessionStore: SessionStore,
) : ViewModel() {

    private val _state = MutableStateFlow(AddMedicineUiState())
    val state: StateFlow<AddMedicineUiState> = _state.asStateFlow()

    private var searchJob: Job? = null

    /**
     * Debounced catalogue search — the backend ranks exact brand matches first,
     * so a short pause while typing is all that is needed to get the right hit.
     * The catalogue endpoint is public, so this also works before connecting a
     * key; any failure (including no internet) falls back to manual entry.
     */
    fun onQueryChange(value: String) {
        _state.value = _state.value.copy(query = value)
        searchJob?.cancel()
        if (value.trim().length < CatalogRepository.MIN_QUERY_LENGTH) {
            _state.value = _state.value.copy(results = emptyList(), searching = false)
            return
        }
        searchJob = viewModelScope.launch {
            _state.value = _state.value.copy(searching = true)
            delay(280)
            catalog.search(value).fold(
                onSuccess = { items ->
                    _state.value = _state.value.copy(
                        results = items,
                        searching = false,
                        // Nothing matched and nothing is cached: manual entry is
                        // always one tap away, never a dead end.
                        manualMode = items.isEmpty() && _state.value.selected == null,
                    )
                },
                onFailure = {
                    _state.value = _state.value.copy(
                        results = emptyList(),
                        searching = false,
                        manualMode = true,
                    )
                },
            )
        }
    }

    fun select(item: CatalogItem) {
        _state.value = _state.value.copy(
            selected = item,
            query = item.displayName,
            results = emptyList(),
            manualMode = false,
        )
    }

    fun clearSelection() {
        _state.value = _state.value.copy(selected = null, query = "", results = emptyList())
    }

    fun enableManualMode(enabled: Boolean) {
        _state.value = _state.value.copy(
            manualMode = enabled,
            selected = if (enabled) null else _state.value.selected,
        )
    }

    fun onManualChange(
        name: String? = null,
        generic: String? = null,
        strength: String? = null,
        dosageForm: String? = null,
    ) {
        val current = _state.value
        _state.value = current.copy(
            manualName = name ?: current.manualName,
            manualGeneric = generic ?: current.manualGeneric,
            manualStrength = strength ?: current.manualStrength,
            manualDosageForm = dosageForm ?: current.manualDosageForm,
        )
    }

    fun onPriceChange(value: String) {
        _state.value = _state.value.copy(priceText = value.filter { it.isDigit() || it == '.' }.take(9))
    }

    fun onThresholdChange(value: String) {
        _state.value = _state.value.copy(thresholdText = value.filter { it.isDigit() }.take(4))
    }

    fun consumeMessage() {
        _state.value = _state.value.copy(message = null)
    }

    fun save() {
        val current = _state.value
        if (current.busy) return
        if (current.selected == null && current.manualName.isBlank()) {
            _state.value = current.copy(message = AddMedicineMessage.NameRequired)
            return
        }
        if (current.priceText.isBlank()) {
            _state.value = current.copy(message = AddMedicineMessage.PriceRequired)
            return
        }
        val request = CreateMedicineRequest(
            brandName = current.selected?.brandName ?: current.manualName.trim(),
            genericName = current.selected?.genericName ?: current.manualGeneric.trim(),
            strength = current.selected?.strength ?: current.manualStrength.trim(),
            dosageForm = current.selected?.dosageForm ?: current.manualDosageForm.trim(),
            defaultSellingPrice = current.price.toBigDecimal().toPlainString(),
            lowStockThreshold = current.threshold,
            catalogMedicine = current.selected?.id,
        )

        _state.value = current.copy(busy = true)
        viewModelScope.launch {
            sessionStore.ensureDeviceId()
            inventory.addMedicine(request).fold(
                onSuccess = { outcome ->
                    _state.value = AddMedicineUiState(
                        message = AddMedicineMessage.Saved(outcome == WriteOutcome.Queued),
                    )
                },
                onFailure = { error ->
                    _state.value = _state.value.copy(
                        busy = false,
                        message = when (error) {
                            is AppError.Network -> AddMedicineMessage.Saved(queued = true)
                            is AppError.Validation -> AddMedicineMessage.Failed(error.detail)
                            else -> AddMedicineMessage.Failed(error.message ?: "error")
                        },
                    )
                },
            )
        }
    }
}
