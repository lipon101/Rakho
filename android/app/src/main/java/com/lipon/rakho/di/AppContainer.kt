package com.lipon.rakho.di

import android.content.Context
import com.lipon.rakho.data.firebase.AuthRepository
import com.lipon.rakho.data.firebase.FirestoreData
import com.lipon.rakho.data.firebase.FirestoreRepository
import com.lipon.rakho.data.repo.CatalogRepository
import com.lipon.rakho.data.repo.CustomersRepository
import com.lipon.rakho.data.repo.DuesRepository
import com.lipon.rakho.data.repo.InventoryRepository
import com.lipon.rakho.data.repo.SalesRepository
import com.lipon.rakho.data.repo.SyncRepository
import com.lipon.rakho.data.session.SessionStore
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.serialization.json.Json

/**
 * Dependency graph for the app: Firebase Auth + Firestore, nothing else.
 *
 * [FirestoreData] holds the one shared listener per collection that every
 * screen reads through, kept alive by [scope] for the whole process. Queries
 * resolve the pharmacy uid at collection time, so building this graph before
 * anyone has signed in is safe; the auth-gated UI only ever collects these
 * flows while signed in.
 *
 * [initialize] must run once before any screen reads a repository.
 */
class AppContainer(private val context: Context) {

    val sessionStore = SessionStore(context)

    val authRepo = AuthRepository()
    val firestoreRepo = FirestoreRepository()

    /** Process-lifetime scope backing the shared Firestore flows. */
    val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    val firestoreData = FirestoreData(firestoreRepo, scope)

    val inventory = InventoryRepository(firestoreRepo, firestoreData, sessionStore)
    val salesRepository = SalesRepository(firestoreRepo, firestoreData)
    val dues = DuesRepository(firestoreRepo, firestoreData)
    val customers = CustomersRepository(firestoreRepo, firestoreData)
    val sync = SyncRepository(firestoreData, sessionStore, scope)
    val catalog = CatalogRepository(JSON, ::loadBundledCatalog)

    private val _ready = MutableStateFlow(false)
    val ready: StateFlow<Boolean> = _ready.asStateFlow()

    suspend fun initialize() {
        if (_ready.value) return
        // Installs that predate the Firebase-only build may still hold legacy
        // API-key/server-URL/local-only prefs; nothing reads them anymore.
        runCatching { sessionStore.clearLegacyKeys() }
        sessionStore.ensureDeviceId()
        _ready.value = true

        // Warm up the medicine catalogue in the background (bundled asset, offline).
        scope.launch { runCatching { catalog.warmUp() } }
    }

    /** Reads the bundled Bangladesh medicine catalogue (search is offline). */
    private suspend fun loadBundledCatalog(): String? =
        runCatching {
            context.assets.open(CATALOG_ASSET).bufferedReader().use { it.readText() }
        }.getOrNull()

    private companion object {
        const val CATALOG_ASSET = "catalog/medicines.json"

        /** Catalogue JSON only — Firebase data never passes through kotlinx. */
        val JSON = Json { ignoreUnknownKeys = true }
    }
}

/** Set once in [com.lipon.rakho.RakhoApp] so ViewModels can reach the graph. */
object ContainerHolder {
    private var container: AppContainer? = null

    fun install(container: AppContainer) {
        this.container = container
    }

    fun get(): AppContainer = requireNotNull(container) {
        "AppContainer not installed. Did RakhoApp run?"
    }
}
