package bd.rakho.pharmacy.di

import android.content.Context
import bd.rakho.pharmacy.data.local.LocalCache
import bd.rakho.pharmacy.data.remote.NetworkModule
import bd.rakho.pharmacy.data.remote.RakhoApi
import bd.rakho.pharmacy.data.repo.BillingRepository
import bd.rakho.pharmacy.data.repo.CatalogRepository
import bd.rakho.pharmacy.data.repo.InventoryRepository
import bd.rakho.pharmacy.data.repo.SalesRepository
import bd.rakho.pharmacy.data.repo.SyncRepository
import bd.rakho.pharmacy.data.session.SessionStore
import bd.rakho.pharmacy.feature.billing.PlayBillingClient
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.serialization.json.Json

/**
 * Dependency graph for the app.
 *
 * Deliberately hand-wired instead of using an annotation processor: the graph is
 * small, everything is explicit, and the build stays fast and free of
 * processor/compiler version coupling.
 *
 * [initialize] must run once before any screen reads a repository — it loads the
 * persisted session (including an optional self-hosted server URL) and only then
 * builds the HTTP client.
 */
class AppContainer(private val context: Context) {

    val json: Json = NetworkModule.json
    val sessionStore = SessionStore(context)
    val cache = LocalCache(context, json)

    private val _ready = MutableStateFlow(false)
    val ready: StateFlow<Boolean> = _ready.asStateFlow()

    lateinit var api: RakhoApi
        private set
    lateinit var inventory: InventoryRepository
        private set
    lateinit var salesReopository: SalesRepository
        private set
    lateinit var catalog: CatalogRepository
        private set
    lateinit var sync: SyncRepository
        private set
    lateinit var billing: BillingRepository
        private set
    lateinit var playBilling: PlayBillingClient
        private set

    suspend fun initialize() {
        if (_ready.value) return
        sessionStore.prime()
        val customBaseUrl = sessionStore.current().serverBaseUrl.ifBlank { null }

        api = NetworkModule.api(sessionStore, customBaseUrl)
        inventory = InventoryRepository(api, cache, json)
        salesReopository = SalesRepository(api, cache, inventory, json)
        catalog = CatalogRepository(api, json)
        sync = SyncRepository(api, cache, inventory, salesReopository, sessionStore, json)
        billing = BillingRepository(api, json)
        playBilling = PlayBillingClient(context)

        _ready.value = true
    }

    /** Rebuilds the HTTP client after the server URL changes in settings. */
    suspend fun reconfigureApi(baseUrl: String?) {
        api = NetworkModule.api(sessionStore, baseUrl?.ifBlank { null })
        inventory = InventoryRepository(api, cache, json)
        salesReopository = SalesRepository(api, cache, inventory, json)
        catalog = CatalogRepository(api, json)
        sync = SyncRepository(api, cache, inventory, salesReopository, sessionStore, json)
        billing = BillingRepository(api, json)
    }
}

/** Set once in [bd.rakho.pharmacy.RakhoApp] so ViewModels can reach the graph. */
object ContainerHolder {
    private var container: AppContainer? = null

    fun install(container: AppContainer) {
        this.container = container
    }

    fun get(): AppContainer = requireNotNull(container) {
        "AppContainer not installed. Did RakhoApp run?"
    }
}
