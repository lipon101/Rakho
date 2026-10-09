package com.lipon.rakho.ui.nav

import androidx.compose.foundation.layout.padding
import androidx.compose.ui.unit.dp
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.BarChart
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Inventory2
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.ShoppingCart
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.lipon.rakho.R
import com.lipon.rakho.di.ContainerHolder
import com.lipon.rakho.di.RakhoViewModelFactory
import com.lipon.rakho.feature.addmedicine.AddMedicineScreen
import com.lipon.rakho.feature.auth.AuthScreen
import com.lipon.rakho.feature.auth.AuthViewModel
import com.lipon.rakho.feature.barcode.BarcodeScannerScreen
import com.lipon.rakho.feature.dashboard.DashboardScreen
import com.lipon.rakho.feature.dues.DuesScreen
import com.lipon.rakho.feature.expenses.ExpenseScreen
import com.lipon.rakho.feature.pos.PosScreen
import com.lipon.rakho.feature.purchases.PurchaseHistoryScreen
import com.lipon.rakho.feature.receive.ReceiveScreen
import com.lipon.rakho.feature.reports.ReportsScreen
import com.lipon.rakho.feature.settings.SettingsScreen
import com.lipon.rakho.feature.stock.StockScreen
import com.lipon.rakho.ui.components.LoadingState
import androidx.lifecycle.viewmodel.compose.viewModel

object Routes {
    const val AUTH = "auth"
    const val DASHBOARD = "dashboard"
    const val POS = "pos"
    const val STOCK = "stock"
    const val STOCK_WITH_FILTER = "stock?filter={filter}"
    const val DUES = "dues"
    const val REPORTS = "reports"
    const val RECEIVE = "receive"
    const val ADD_MEDICINE = "add_medicine"
    const val SETTINGS = "settings"
    const val PURCHASE_HISTORY = "purchase_history"
    const val EXPENSES = "expenses"
    const val BARCODE_SCANNER = "barcode_scanner"
}

private data class Tab(val route: String, val labelRes: Int, val icon: ImageVector)

private val tabs = listOf(
    Tab(Routes.DASHBOARD, R.string.nav_home, Icons.Filled.Home),
    Tab(Routes.POS, R.string.nav_sell, Icons.Filled.ShoppingCart),
    Tab(Routes.STOCK, R.string.nav_stock, Icons.Filled.Inventory2),
    Tab(Routes.REPORTS, R.string.nav_reports, Icons.Filled.BarChart),
    Tab(Routes.SETTINGS, R.string.nav_settings, Icons.Filled.Settings),
)

/**
 * Full-screen flows that own their whole window — bottom bar is hidden.
 */
private val fullScreenRoutes = setOf(
    Routes.RECEIVE,
    Routes.ADD_MEDICINE,
    Routes.AUTH,
    Routes.BARCODE_SCANNER,
    Routes.PURCHASE_HISTORY,
    Routes.EXPENSES,
)

private fun NavHostController.open(route: String, asTab: Boolean) {
    navigate(route) {
        if (asTab) {
            popUpTo(Routes.DASHBOARD) { saveState = true }
            launchSingleTop = true
            restoreState = true
        } else {
            launchSingleTop = true
        }
    }
}

@Composable
fun RakhoRoot() {
    val container = remember { ContainerHolder.get() }
    val ready by container.ready.collectAsStateWithLifecycle()

    if (!ready) {
        LoadingState()
        return
    }

    val authViewModel: AuthViewModel = viewModel(factory = RakhoViewModelFactory)

    // Reactive auth gate: Firebase Auth is the only way in. Signing in or out
    // changes the key below, which rebuilds the whole nav graph — no pharmacy
    // data screen can survive a sign-out, and no stale NavController can keep
    // the dashboard on screen.
    val authUser by container.authRepo.observeAuthState()
        .collectAsStateWithLifecycle(initialValue = container.authRepo.currentUser)

    key(authUser?.uid) {
        val navController = rememberNavController()
        val startRoute = if (authUser != null) Routes.DASHBOARD else Routes.AUTH

        Scaffold(
            bottomBar = { RakhoBottomBar(navController) },
        ) { padding ->
            NavHost(
                navController = navController,
                startDestination = startRoute,
                modifier = Modifier.padding(bottom = padding.calculateBottomPadding()),
            ) {
            // ── Auth ──────────────────────────────────────────────────────
            composable(Routes.AUTH) {
                AuthScreen(
                    viewModel = authViewModel,
                    onAuthenticated = {
                        navController.navigate(Routes.DASHBOARD) {
                            popUpTo(Routes.AUTH) { inclusive = true }
                        }
                    },
                )
            }

            // ── Main tabs ─────────────────────────────────────────────────
            composable(Routes.DASHBOARD) {
                DashboardScreen(
                    onSell = { navController.open(Routes.POS, asTab = true) },
                    onReceive = { navController.open(Routes.RECEIVE, asTab = false) },
                    onAddMedicine = { navController.open(Routes.ADD_MEDICINE, asTab = false) },
                    onOpenStock = { filter ->
                        val route = if (filter == null) {
                            Routes.STOCK
                        } else {
                            "stock?filter=${filter.name}"
                        }
                        navController.open(route, asTab = true)
                    },
                    onOpenDues = { navController.open(Routes.DUES, asTab = false) },
                    onOpenSettings = { navController.open(Routes.SETTINGS, asTab = true) },
                    onOpenReports = { navController.open(Routes.REPORTS, asTab = true) },
                    onOpenPurchaseHistory = { navController.open(Routes.PURCHASE_HISTORY, asTab = false) },
                    onOpenExpenses = { navController.open(Routes.EXPENSES, asTab = false) },
                )
            }
            composable(Routes.POS) {
                PosScreen(
                    onDone = { navController.open(Routes.DASHBOARD, asTab = true) },
                    onAddMedicine = { prefill ->
                        val encoded = java.net.URLEncoder.encode(prefill, "UTF-8")
                        navController.open("add_medicine?prefill=$encoded", asTab = false)
                    },
                    onScanBarcode = { navController.open(Routes.BARCODE_SCANNER, asTab = false) },
                )
            }
            composable(Routes.STOCK) {
                StockScreen(
                    onReceive = { navController.open(Routes.RECEIVE, asTab = false) },
                    onScanBarcode = { navController.open(Routes.BARCODE_SCANNER, asTab = false) },
                )
            }
            composable(
                route = Routes.STOCK_WITH_FILTER,
                arguments = listOf(
                    navArgument("filter") {
                        type = NavType.StringType
                        defaultValue = "ALL"
                    },
                ),
            ) { entry ->
                StockScreen(
                    onReceive = { navController.open(Routes.RECEIVE, asTab = false) },
                    onScanBarcode = { navController.open(Routes.BARCODE_SCANNER, asTab = false) },
                    initialFilter = runCatching {
                        com.lipon.rakho.core.model.StockFilter.valueOf(
                            entry.arguments?.getString("filter") ?: "ALL",
                        )
                    }.getOrDefault(com.lipon.rakho.core.model.StockFilter.ALL),
                )
            }
            composable(Routes.DUES) { DuesScreen(onBack = { navController.popBackStack() }) }
            composable(Routes.REPORTS) { ReportsScreen() }
            composable(Routes.RECEIVE) {
                ReceiveScreen(onSaved = { navController.popBackStack() })
            }
            composable(Routes.ADD_MEDICINE) {
                AddMedicineScreen(onSaved = { navController.popBackStack() })
            }
            composable(
                route = "add_medicine?prefill={prefill}",
                arguments = listOf(
                    navArgument("prefill") {
                        type = NavType.StringType
                        defaultValue = ""
                    },
                ),
            ) { entry ->
                val prefill = runCatching {
                    java.net.URLDecoder.decode(
                        entry.arguments?.getString("prefill").orEmpty(),
                        "UTF-8",
                    )
                }.getOrDefault("")
                AddMedicineScreen(
                    onSaved = { navController.popBackStack() },
                    initialQuery = prefill,
                )
            }
            composable(Routes.SETTINGS) {
                SettingsScreen(
                    onBack = { navController.popBackStack() },
                    onSignOut = {
                        navController.navigate(Routes.AUTH) {
                            popUpTo(0) { inclusive = true }
                        }
                    },
                )
            }

            // ── New screens ───────────────────────────────────────────────
            composable(Routes.PURCHASE_HISTORY) {
                PurchaseHistoryScreen(onBack = { navController.popBackStack() })
            }
            composable(Routes.EXPENSES) {
                ExpenseScreen(onBack = { navController.popBackStack() })
            }
            composable(
                route = "${Routes.BARCODE_SCANNER}?returnTo={returnTo}",
                arguments = listOf(
                    navArgument("returnTo") {
                        type = NavType.StringType
                        defaultValue = ""
                    },
                ),
            ) {
                BarcodeScannerScreen(
                    onScanned = { barcode ->
                        navController.previousBackStackEntry
                            ?.savedStateHandle
                            ?.set("scanned_barcode", barcode)
                        navController.popBackStack()
                    },
                    onDismiss = { navController.popBackStack() },
                )
            }
            composable(Routes.BARCODE_SCANNER) {
                BarcodeScannerScreen(
                    onScanned = { barcode ->
                        navController.previousBackStackEntry
                            ?.savedStateHandle
                            ?.set("scanned_barcode", barcode)
                        navController.popBackStack()
                    },
                    onDismiss = { navController.popBackStack() },
                )
            }
            }
        }
    }
}

@Composable
private fun RakhoBottomBar(navController: NavHostController) {
    val backStackEntry by navController.currentBackStackEntryAsState()
    val currentRoute = backStackEntry?.destination?.route
    if (currentRoute in fullScreenRoutes) return

    val itemColors = NavigationBarItemDefaults.colors(
        selectedIconColor = MaterialTheme.colorScheme.onPrimaryContainer,
        selectedTextColor = MaterialTheme.colorScheme.primary,
        indicatorColor = MaterialTheme.colorScheme.primaryContainer,
        unselectedIconColor = MaterialTheme.colorScheme.onSurfaceVariant,
        unselectedTextColor = MaterialTheme.colorScheme.onSurfaceVariant,
    )
    NavigationBar(
        containerColor = MaterialTheme.colorScheme.surface,
        tonalElevation = 2.dp,
    ) {
        tabs.forEach { tab ->
            NavigationBarItem(
                selected = currentRoute == tab.route,
                onClick = { navController.open(tab.route, asTab = true) },
                icon = { Icon(tab.icon, contentDescription = null) },
                label = { Text(stringResource(tab.labelRes)) },
                alwaysShowLabel = true,
                colors = itemColors,
            )
        }
    }
}
