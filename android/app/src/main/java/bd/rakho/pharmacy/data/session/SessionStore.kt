package bd.rakho.pharmacy.data.session

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import java.util.UUID
import java.util.concurrent.atomic.AtomicReference

private val Context.dataStore: DataStore<Preferences> by preferencesDataStore(name = "rakho_session")

/** Persisted pharmacy session: credentials, shop identity and preferences. */
data class SessionState(
    val apiKey: String = "",
    val shopName: String = "",
    val currency: String = "BDT",
    val languageCode: String = "",
    val deviceId: String = "",
    val notificationsEnabled: Boolean = true,
    val serverBaseUrl: String = "",
    val lastSyncAtMillis: Long = 0L,
) {
    val isConnected: Boolean get() = apiKey.isNotBlank()
}

class SessionStore(private val context: Context) {

    private val cachedKey = AtomicReference<String?>(null)

    /**
     * Non-suspending read used by the OkHttp interceptor. Kept hot by
     * [apiKeyOrNull] being primed on first flow collection and on every save.
     */
    fun apiKeyOrNull(): String? = cachedKey.get()

    suspend fun prime() {
        cachedKey.set(current().apiKey)
    }

    val state: Flow<SessionState> = context.dataStore.data.map { prefs ->
        SessionState(
            apiKey = prefs[KEY_API_KEY].orEmpty(),
            shopName = prefs[KEY_SHOP_NAME].orEmpty(),
            currency = prefs[KEY_CURRENCY] ?: "BDT",
            languageCode = prefs[KEY_LANGUAGE].orEmpty(),
            deviceId = prefs[KEY_DEVICE_ID].orEmpty(),
            notificationsEnabled = prefs[KEY_NOTIFICATIONS] ?: true,
            serverBaseUrl = prefs[KEY_BASE_URL].orEmpty(),
            lastSyncAtMillis = prefs[KEY_LAST_SYNC]?.toLongOrNull() ?: 0L,
        ).also { cachedKey.set(it.apiKey) }
    }

    suspend fun current(): SessionState = state.first()

    suspend fun saveCredentials(apiKey: String, shopName: String) {
        context.dataStore.edit { prefs ->
            prefs[KEY_API_KEY] = apiKey.trim()
            if (shopName.isNotBlank()) prefs[KEY_SHOP_NAME] = shopName.trim()
        }
        cachedKey.set(apiKey.trim())
    }

    suspend fun updateShopName(name: String) {
        context.dataStore.edit { it[KEY_SHOP_NAME] = name }
    }

    suspend fun updateLanguage(code: String) {
        context.dataStore.edit { prefs ->
            if (code.isBlank()) prefs.remove(KEY_LANGUAGE) else prefs[KEY_LANGUAGE] = code
        }
    }

    suspend fun updateNotifications(enabled: Boolean) {
        context.dataStore.edit { it[KEY_NOTIFICATIONS] = enabled }
    }

    suspend fun updateBaseUrl(url: String) {
        context.dataStore.edit { prefs ->
            if (url.isBlank()) prefs.remove(KEY_BASE_URL) else prefs[KEY_BASE_URL] = url.trim()
        }
    }

    suspend fun markSynced(atMillis: Long) {
        context.dataStore.edit { it[KEY_LAST_SYNC] = atMillis.toString() }
    }

    suspend fun ensureDeviceId(): String {
        val existing = current().deviceId
        if (existing.isNotBlank()) return existing
        val generated = UUID.randomUUID().toString()
        context.dataStore.edit { it[KEY_DEVICE_ID] = generated }
        return generated
    }

    suspend fun disconnect() {
        context.dataStore.edit { prefs ->
            prefs.remove(KEY_API_KEY)
            prefs.remove(KEY_LAST_SYNC)
        }
        cachedKey.set(null)
    }

    private companion object {
        val KEY_API_KEY = stringPreferencesKey("api_key")
        val KEY_SHOP_NAME = stringPreferencesKey("shop_name")
        val KEY_CURRENCY = stringPreferencesKey("currency")
        val KEY_LANGUAGE = stringPreferencesKey("language")
        val KEY_DEVICE_ID = stringPreferencesKey("device_id")
        val KEY_NOTIFICATIONS = booleanPreferencesKey("notifications_enabled")
        val KEY_BASE_URL = stringPreferencesKey("server_base_url")
        val KEY_LAST_SYNC = stringPreferencesKey("last_sync_at")
    }
}
