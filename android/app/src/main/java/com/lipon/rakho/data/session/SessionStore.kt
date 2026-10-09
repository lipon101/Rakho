package com.lipon.rakho.data.session

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

private val Context.dataStore: DataStore<Preferences> by preferencesDataStore(name = "rakho_session")

/**
 * Device-local session: shop identity and preferences.
 *
 * Authentication lives in Firebase Auth and data lives in Firestore, so this
 * store no longer holds API keys or connection state — it only remembers
 * what must survive an app restart on this device (shop name for offline
 * first paint, language, notification preference, stable device id).
 */
data class SessionState(
    val shopName: String = "",
    val currency: String = "BDT",
    val languageCode: String = "",
    val deviceId: String = "",
    val notificationsEnabled: Boolean = true,
    val lastSyncAtMillis: Long = 0L,
    /** "system", "light" or "dark" — resolved into a scheme by RakhoTheme. */
    val themeMode: String = "system",
)

class SessionStore(private val context: Context) {

    val state: Flow<SessionState> = context.dataStore.data.map { prefs ->
        SessionState(
            shopName = prefs[KEY_SHOP_NAME].orEmpty(),
            currency = prefs[KEY_CURRENCY] ?: "BDT",
            languageCode = prefs[KEY_LANGUAGE].orEmpty(),
            deviceId = prefs[KEY_DEVICE_ID].orEmpty(),
            notificationsEnabled = prefs[KEY_NOTIFICATIONS] ?: true,
            lastSyncAtMillis = prefs[KEY_LAST_SYNC]?.toLongOrNull() ?: 0L,
            themeMode = prefs[KEY_THEME].orEmpty().ifBlank { "system" },
        )
    }

    suspend fun current(): SessionState = state.first()

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

    suspend fun updateThemeMode(mode: String) {
        context.dataStore.edit { it[KEY_THEME] = mode }
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

    /**
     * Full local reset — used by "Delete my account and data". Every pref on
     * this device is dropped, so the next launch bootstraps a brand-new
     * account exactly like a fresh install.
     */
    suspend fun reset() {
        context.dataStore.edit { it.clear() }
    }

    /**
     * One-time cleanup for installs that predate the Firebase-only build:
     * they may still hold legacy API-key / server-URL / local-only prefs that
     * nothing reads anymore. Dropping them keeps the store honest.
     */
    suspend fun clearLegacyKeys() {
        context.dataStore.edit { prefs ->
            prefs.remove(KEY_LEGACY_API_KEY)
            prefs.remove(KEY_LEGACY_BASE_URL)
            prefs.remove(KEY_LEGACY_LOCAL_ONLY)
        }
    }

    private companion object {
        val KEY_SHOP_NAME = stringPreferencesKey("shop_name")
        val KEY_CURRENCY = stringPreferencesKey("currency")
        val KEY_LANGUAGE = stringPreferencesKey("language")
        val KEY_DEVICE_ID = stringPreferencesKey("device_id")
        val KEY_NOTIFICATIONS = booleanPreferencesKey("notifications_enabled")
        val KEY_LAST_SYNC = stringPreferencesKey("last_sync_at")
        val KEY_THEME = stringPreferencesKey("theme_mode")

        val KEY_LEGACY_API_KEY = stringPreferencesKey("api_key")
        val KEY_LEGACY_BASE_URL = stringPreferencesKey("server_base_url")
        val KEY_LEGACY_LOCAL_ONLY = booleanPreferencesKey("local_only")
    }
}
