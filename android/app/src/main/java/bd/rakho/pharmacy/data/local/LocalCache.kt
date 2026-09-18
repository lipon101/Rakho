package bd.rakho.pharmacy.data.local

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import bd.rakho.pharmacy.core.model.PendingOperation
import bd.rakho.pharmacy.core.model.PendingOperationType
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import java.time.Instant

/**
 * Offline store for the pharmacy's working set.
 *
 * Pharmacy data is small (thousands of rows) and is always consumed as whole
 * lists — the POS searches, filters and re-orders in memory — so payloads are
 * cached as JSON documents keyed by name, while queued write operations live in
 * a real table because they are retried, counted and deleted individually.
 *
 * Every write bumps [revision], which repositories expose as flows so the UI
 * re-renders the moment fresh or locally-changed data lands.
 */
class LocalCache(
    context: Context,
    private val json: Json,
) : SQLiteOpenHelper(context.applicationContext, DB_NAME, null, DB_VERSION) {

    private val _revision = MutableStateFlow(0L)
    val revision: StateFlow<Long> = _revision.asStateFlow()

    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL(
            """
            CREATE TABLE $TABLE_CACHE (
                cache_key TEXT PRIMARY KEY NOT NULL,
                payload TEXT NOT NULL,
                updated_at INTEGER NOT NULL
            )
            """.trimIndent(),
        )
        db.execSQL(
            """
            CREATE TABLE $TABLE_PENDING (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                op_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT
            )
            """.trimIndent(),
        )
        db.execSQL("CREATE INDEX idx_pending_created ON $TABLE_PENDING(created_at)")
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
        // Cached payloads are always re-derivable from the API, but queued
        // operations are not — keep them across schema upgrades.
        db.execSQL("DROP TABLE IF EXISTS $TABLE_CACHE")
        onCreate(db)
    }

    override fun onConfigure(db: SQLiteDatabase) {
        super.onConfigure(db)
        db.setForeignKeyConstraintsEnabled(true)
    }

    private fun bump() {
        _revision.value = _revision.value + 1
    }

    // ---- JSON documents ---------------------------------------------------

    suspend fun <T> read(key: String, decode: (String) -> T): T? = withContext(Dispatchers.IO) {
        readableDatabase.query(
            TABLE_CACHE,
            arrayOf(COL_PAYLOAD),
            "$COL_KEY = ?",
            arrayOf(key),
            null,
            null,
            null,
        ).use { cursor ->
            if (cursor.moveToFirst()) {
                runCatching { decode(cursor.getString(0)) }.getOrNull()
            } else {
                null
            }
        }
    }

    suspend fun <T> write(key: String, value: T, encode: (T) -> String) {
        withContext(Dispatchers.IO) {
            val values = ContentValues().apply {
                put(COL_KEY, key)
                put(COL_PAYLOAD, encode(value))
                put(COL_UPDATED, System.currentTimeMillis())
            }
            writableDatabase.insertWithOnConflict(
                TABLE_CACHE,
                null,
                values,
                SQLiteDatabase.CONFLICT_REPLACE,
            )
        }
        bump()
    }

    suspend fun clearCache() = withContext(Dispatchers.IO) {
        writableDatabase.delete(TABLE_CACHE, null, null)
        Unit
    }.also { bump() }

    suspend fun clearAll() = withContext(Dispatchers.IO) {
        writableDatabase.delete(TABLE_CACHE, null, null)
        writableDatabase.delete(TABLE_PENDING, null, null)
        Unit
    }.also { bump() }

    suspend fun cachedAt(key: String): Long? = withContext(Dispatchers.IO) {
        readableDatabase.query(
            TABLE_CACHE,
            arrayOf(COL_UPDATED),
            "$COL_KEY = ?",
            arrayOf(key),
            null,
            null,
            null,
        ).use { cursor ->
            if (cursor.moveToFirst()) cursor.getLong(0) else null
        }
    }

    // ---- Queued write operations -----------------------------------------

    suspend fun enqueue(type: PendingOperationType, payload: String): Long =
        withContext(Dispatchers.IO) {
            val values = ContentValues().apply {
                put(COL_OP_TYPE, type.name)
                put(COL_OP_PAYLOAD, payload)
                put(COL_OP_CREATED, System.currentTimeMillis())
                put(COL_OP_ATTEMPTS, 0)
            }
            writableDatabase.insert(TABLE_PENDING, null, values)
        }.also { bump() }

    suspend fun pending(): List<PendingOperation> = withContext(Dispatchers.IO) {
        readableDatabase.query(
            TABLE_PENDING,
            arrayOf("id", COL_OP_TYPE, COL_OP_PAYLOAD, COL_OP_CREATED, COL_OP_ATTEMPTS, COL_OP_ERROR),
            null,
            null,
            null,
            null,
            "$COL_OP_CREATED ASC",
        ).use { cursor ->
            buildList {
                while (cursor.moveToNext()) {
                    add(
                        PendingOperation(
                            id = cursor.getLong(0),
                            type = runCatching<PendingOperationType> {
                                PendingOperationType.valueOf(cursor.getString(1))
                            }.getOrDefault(PendingOperationType.SALE),
                            payload = cursor.getString(2),
                            createdAt = Instant.ofEpochMilli(cursor.getLong(3)),
                            attempts = cursor.getInt(4),
                            lastError = cursor.getString(5),
                        ),
                    )
                }
            }
        }
    }

    suspend fun pendingCount(): Int = withContext(Dispatchers.IO) {
        readableDatabase.rawQuery("SELECT COUNT(*) FROM $TABLE_PENDING", null).use { cursor ->
            if (cursor.moveToFirst()) cursor.getInt(0) else 0
        }
    }

    suspend fun deleteOp(id: Long) = withContext(Dispatchers.IO) {
        writableDatabase.delete(TABLE_PENDING, "id = ?", arrayOf(id.toString()))
        Unit
    }.also { bump() }

    suspend fun recordFailure(id: Long, error: String) = withContext(Dispatchers.IO) {
        writableDatabase.execSQL(
            "UPDATE $TABLE_PENDING SET attempts = attempts + 1, last_error = ? WHERE id = ?",
            arrayOf<Any>(error.take(400), id),
        )
        Unit
    }.also { bump() }

    companion object {
        const val DB_NAME = "rakho_cache.db"
        private const val DB_VERSION = 1

        private const val TABLE_CACHE = "cache_entries"
        private const val TABLE_PENDING = "pending_ops"
        private const val COL_KEY = "cache_key"
        private const val COL_PAYLOAD = "payload"
        private const val COL_UPDATED = "updated_at"
        private const val COL_OP_TYPE = "op_type"
        private const val COL_OP_PAYLOAD = "payload"
        private const val COL_OP_CREATED = "created_at"
        private const val COL_OP_ATTEMPTS = "attempts"
        private const val COL_OP_ERROR = "last_error"

        /** Cache keys. */
        const val KEY_MEDICINES = "medicines"
        const val KEY_BATCHES = "batches"
        const val KEY_SALES = "sales"
        const val KEY_ALERTS = "alerts"
        const val KEY_DASHBOARD = "dashboard"
        const val KEY_PROFILE = "profile"
    }
}
