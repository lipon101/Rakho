package com.lipon.rakho.data.repo

import com.lipon.rakho.core.model.CatalogItem
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

/**
 * Searches the Bangladesh medicine catalogue bundled with the app
 * (assets/catalog/medicines.json — ~21,000 real registered brands with
 * generic, strength, form and manufacturer).
 *
 * Fully on-device by design: the file is decoded once, held in memory, and
 * every keystroke is a ranked scan. No network, no API key, no rate limit and
 * no cold-start delay — a shopkeeper with no signal gets the same instant
 * suggestions as anyone else. Ranking: exact brand, then brand prefix
 * (shortest first), then brand substring, generic prefix/substring, then
 * manufacturer, so "napa" offers Napa before Napa Extend before Naproxen.
 */
class CatalogRepository(
    private val json: Json,
    private val loadRawCatalog: suspend () -> String?,
) {
    @Volatile
    private var indexed: List<Indexed>? = null

    suspend fun search(query: String): Result<List<CatalogItem>> {
        val trimmed = query.trim()
        if (trimmed.length < MIN_QUERY_LENGTH) return Result.success(emptyList())
        val items = ensureLoaded() ?: return Result.success(emptyList())
        return Result.success(rank(items, trimmed))
    }

    /** True once the bundled catalogue has been decoded (diagnostics/tests). */
    val isLoaded: Boolean get() = indexed != null

    /**
     * Decodes the bundled file ahead of the first keystroke. Called once in
     * the background at startup so the first search of the app's life feels
     * exactly like the thousandth.
     */
    suspend fun warmUp() {
        ensureLoaded()
    }

    private suspend fun ensureLoaded(): List<Indexed>? {
        indexed?.let { return it }
        val raw = withContext(Dispatchers.IO) {
            runCatching { loadRawCatalog() }.getOrNull()
        } ?: return null
        val parsed = withContext(Dispatchers.Default) {
            runCatching {
                json.decodeFromString<List<Seed>>(raw).map { seed ->
                    Indexed(
                        item = CatalogItem(
                            id = seed.id,
                            brandName = seed.brand,
                            genericName = seed.generic,
                            strength = seed.strength,
                            dosageForm = seed.form,
                            manufacturerName = seed.maker,
                        ),
                        brand = seed.brand.lowercase(),
                        generic = seed.generic.lowercase(),
                        maker = seed.maker.lowercase(),
                    )
                }
            }.getOrNull()
        } ?: return null
        indexed = parsed
        return parsed
    }

    /** Lowercased projections beside each item so ranking never re-allocates. */
    private data class Indexed(
        val item: CatalogItem,
        val brand: String,
        val generic: String,
        val maker: String,
    )

    /** Short keys keep the bundled asset small; every field is optional. */
    @Serializable
    private data class Seed(
        @SerialName("i") val id: Long = 0,
        @SerialName("b") val brand: String,
        @SerialName("g") val generic: String = "",
        @SerialName("s") val strength: String = "",
        @SerialName("f") val form: String = "",
        @SerialName("m") val maker: String = "",
    )

    companion object {
        const val MIN_QUERY_LENGTH = 2
        const val MAX_RESULTS = 25

        private fun rank(items: List<Indexed>, query: String, limit: Int = MAX_RESULTS): List<CatalogItem> {
            val q = query.lowercase()
            val scored = ArrayList<Triple<Int, Int, CatalogItem>>(limit + 8)
            for (entry in items) {
                val tier = when {
                    entry.brand == q -> 0
                    entry.brand.startsWith(q) -> 1
                    entry.brand.contains(q) -> 2
                    entry.generic.startsWith(q) -> 3
                    entry.generic.contains(q) -> 4
                    entry.maker.isNotEmpty() && entry.maker.contains(q) -> 5
                    else -> continue
                }
                scored.add(Triple(tier, entry.item.brandName.length, entry.item))
            }
            if (scored.isEmpty()) return emptyList()
            scored.sortWith(compareBy({ it.first }, { it.second }, { it.third.brandName }))
            return scored.asSequence().map { it.third }.take(limit).toList()
        }
    }
}
