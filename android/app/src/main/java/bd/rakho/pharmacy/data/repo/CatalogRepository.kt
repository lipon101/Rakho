package bd.rakho.pharmacy.data.repo

import bd.rakho.pharmacy.core.model.CatalogItem
import bd.rakho.pharmacy.data.remote.RakhoApi
import bd.rakho.pharmacy.data.remote.apiCall
import bd.rakho.pharmacy.data.remote.toDomain
import kotlinx.serialization.json.Json

/**
 * Searches the national Bangladesh medicine catalogue.
 *
 * Results are memoised per query so re-opening the Add Medicine screen or
 * toggling back to a previous search is instant, and repeat typing does not
 * hammer the API. The backend already ranks by relevance (exact brand >
 * brand prefix > generic > substring) and de-duplicates.
 */
class CatalogRepository(
    private val api: RakhoApi,
    private val json: Json,
    private val cacheSize: Int = 32,
) {

    private val memo = object : LinkedHashMap<String, List<CatalogItem>>(16, 0.75f, true) {
        override fun removeEldestEntry(eldest: MutableMap.MutableEntry<String, List<CatalogItem>>?): Boolean =
            size > cacheSize
    }

    suspend fun search(query: String): Result<List<CatalogItem>> {
        val trimmed = query.trim()
        if (trimmed.length < MIN_QUERY_LENGTH) return Result.success(emptyList())

        synchronized(memo) { memo[trimmed.lowercase()] }?.let { return Result.success(it) }

        return apiCall(json) {
            val items = api.catalog(trimmed).results.map { it.toDomain() }
            synchronized(memo) { memo[trimmed.lowercase()] = items }
            items
        }
    }

    companion object {
        const val MIN_QUERY_LENGTH = 2
    }
}
