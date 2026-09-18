package com.lipon.rakho.di

import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.lipon.rakho.feature.addmedicine.AddMedicineViewModel
import com.lipon.rakho.feature.billing.SubscriptionViewModel
import com.lipon.rakho.feature.dashboard.DashboardViewModel
import com.lipon.rakho.feature.onboarding.OnboardingViewModel
import com.lipon.rakho.feature.pos.PosViewModel
import com.lipon.rakho.feature.receive.ReceiveViewModel
import com.lipon.rakho.feature.reports.ReportsViewModel
import com.lipon.rakho.feature.settings.SettingsViewModel
import com.lipon.rakho.feature.stock.StockViewModel

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
