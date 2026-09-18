package bd.rakho.pharmacy.di

import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import bd.rakho.pharmacy.feature.addmedicine.AddMedicineViewModel
import bd.rakho.pharmacy.feature.billing.SubscriptionViewModel
import bd.rakho.pharmacy.feature.dashboard.DashboardViewModel
import bd.rakho.pharmacy.feature.onboarding.OnboardingViewModel
import bd.rakho.pharmacy.feature.pos.PosViewModel
import bd.rakho.pharmacy.feature.receive.ReceiveViewModel
import bd.rakho.pharmacy.feature.reports.ReportsViewModel
import bd.rakho.pharmacy.feature.settings.SettingsViewModel
import bd.rakho.pharmacy.feature.stock.StockViewModel

/**
 * One factory for the whole app: every ViewModel is built from the explicitly
 * wired [AppContainer], which keeps construction testable and avoids
 * service-locator lookups scattered through screens.
 */
val RakhoViewModelFactory = viewModelFactory {
    initializer {
        val container = ContainerHolder.get()
        OnboardingViewModel(container.sessionStore, container.sync, container.inventory)
    }
    initializer {
        val container = ContainerHolder.get()
        DashboardViewModel(container.inventory, container.sync, container.sessionStore, container.billing)
    }
    initializer {
        val container = ContainerHolder.get()
        PosViewModel(container.inventory, container.salesReopository, container.sessionStore)
    }
    initializer {
        val container = ContainerHolder.get()
        StockViewModel(container.inventory)
    }
    initializer {
        val container = ContainerHolder.get()
        ReceiveViewModel(container.inventory, container.sessionStore)
    }
    initializer {
        val container = ContainerHolder.get()
        AddMedicineViewModel(container.catalog, container.inventory, container.sessionStore)
    }
    initializer {
        val container = ContainerHolder.get()
        ReportsViewModel(container.salesReopository, container.sessionStore)
    }
    initializer {
        val container = ContainerHolder.get()
        SubscriptionViewModel(container.playBilling, container.billing, container.sessionStore)
    }
    initializer {
        val container = ContainerHolder.get()
        SettingsViewModel(container.sessionStore, container.sync, container, container.inventory)
    }
}
