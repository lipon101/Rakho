package com.lipon.rakho.ui.nav

import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.ShoppingCart
import androidx.compose.material.icons.filled.Star
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import com.lipon.rakho.R
import com.lipon.rakho.data.session.SessionState
import com.lipon.rakho.di.ContainerHolder
import com.lipon.rakho.feature.addmedicine.AddMedicineScreen
import com.lipon.rakho.feature.billing.SubscriptionScreen
import com.lipon.rakho.feature.dashboard.DashboardScreen
import com.lipon.rakho.feature.dues.DuesScreen
import com.lipon.rakho.feature.onboarding.OnboardingScreen
import com.lipon.rakho.feature.pos.PosScreen
import com.lipon.rakho.feature.receive.ReceiveScreen
import com.lipon.rakho.feature.reports.ReportsScreen
import com.lipon.rakho.feature.settings.SettingsScreen
import com.lipon.rakho.feature.stock.StockScreen
import com.lipon.rakho.ui.components.LoadingState

object Routes {
    const val ONBOARDING = "onboarding"
    const val DASHBOARD = "dashboard"
    const val POS = "pos"
    const val STOCK = "stock"
    const val DUES = "dues"
    const val REPORTS = "reports"
    const val RECEIVE = "receive"
    const val ADD_MEDICINE = "add_medicine"
    const val SUBSCRIPTION = "subscription"
    const val SETTINGS = "settings"
}

private data class Tab(val route: String, val labelRes: Int, val icon: ImageVector)

private val tabs = listOf(
    Tab(Routes.DASHBOARD, R.string.nav_home, Icons.Filled.Home),
    Tab(Routes.POS, R.string.nav_sell, Icons.Filled.ShoppingCart),
    Tab(Routes.STOCK, R.string.nav_stock, Icons.AutoMirrored.Filled.List),
    Tab(Routes.REPORTS, R.string.nav_reports, Icons.Filled.Star),
)

@Composable
fun RakhoRoot() {
    val container = remember { ContainerHolder.get() }
    val ready by container.ready.collectAsStateWithLifecycle()
    val session by container.sessionStore.state
        .collectAsStateWithLifecycle(initialValue = SessionState())

    if (!ready) {
        LoadingState()
        return
    }

    val navController = rememberNavController()
    val startRoute = if (session.isReady) Routes.DASHBOARD else Routes.ONBOARDING

    Scaffold(
        bottomBar = { RakhoBottomBar(navController) },
    ) { padding ->
        NavHost(
            navController = navController,
            startDestination = startRoute,
            modifier = Modifier.padding(bottom = padding.calculateBottomPadding()),
        ) {
            composable(Routes.ONBOARDING) {
                OnboardingScreen(
                    onConnected = {
                        navController.navigate(Routes.DASHBOARD) {
                            popUpTo(Routes.ONBOARDING) { inclusive = true }
                        }
                    },
                )
            }
            composable(Routes.DASHBOARD) {
                DashboardScreen(
                    onSell = { navController.navigate(Routes.POS) },
                    onReceive = { navController.navigate(Routes.RECEIVE) },
                    onAddMedicine = { navController.navigate(Routes.ADD_MEDICINE) },
                    onOpenStock = { navController.navigate(Routes.STOCK) },
                    onOpenDues = { navController.navigate(Routes.DUES) },
                    onOpenSettings = { navController.navigate(Routes.SETTINGS) },
                    onOpenSubscription = { navController.navigate(Routes.SUBSCRIPTION) },
                    onConnect = { navController.navigate(Routes.SETTINGS) },
                )
            }
            composable(Routes.POS) { PosScreen(onDone = { navController.popBackStack() }) }
            composable(Routes.STOCK) { StockScreen(onReceive = { navController.navigate(Routes.RECEIVE) }) }
            composable(Routes.DUES) { DuesScreen(onBack = { navController.popBackStack() }) }
            composable(Routes.REPORTS) { ReportsScreen() }
            composable(Routes.RECEIVE) { ReceiveScreen(onSaved = { navController.popBackStack() }) }
            composable(Routes.ADD_MEDICINE) {
                AddMedicineScreen(onSaved = { navController.popBackStack() })
            }
            composable(Routes.SUBSCRIPTION) {
                SubscriptionScreen(onBack = { navController.popBackStack() })
            }
            composable(Routes.SETTINGS) {
                SettingsScreen(
                    onBack = { navController.popBackStack() },
                    onOpenSubscription = { navController.navigate(Routes.SUBSCRIPTION) },
                )
            }
        }
    }
}

@Composable
private fun RakhoBottomBar(navController: NavHostController) {
    val backStackEntry by navController.currentBackStackEntryAsState()
    val currentRoute = backStackEntry?.destination?.route
    val hiddenRoutes = setOf(
        Routes.ONBOARDING,
        Routes.RECEIVE,
        Routes.ADD_MEDICINE,
        Routes.SUBSCRIPTION,
        Routes.DUES,
    )
    if (currentRoute in hiddenRoutes) return

    NavigationBar {
        tabs.forEach { tab ->
            NavigationBarItem(
                selected = currentRoute == tab.route,
                onClick = {
                    if (currentRoute != tab.route) {
                        navController.navigate(tab.route) {
                            popUpTo(Routes.DASHBOARD) { saveState = true }
                            launchSingleTop = true
                            restoreState = true
                        }
                    }
                },
                icon = { Icon(tab.icon, contentDescription = null) },
                label = { Text(stringResource(tab.labelRes)) },
            )
        }
        NavigationBarItem(
            selected = currentRoute == Routes.SETTINGS,
            onClick = { navController.navigate(Routes.SETTINGS) },
            icon = { Icon(Icons.Filled.Settings, contentDescription = null) },
            label = { Text(stringResource(R.string.nav_settings)) },
        )
    }
}
