package com.lipon.rakho.data.repo

import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * The catalogue is the app's promise of "everything works out of the box":
 * suggestions must come from data shipped with the APK, ranked the way a
 * shopkeeper expects, and never fail — no network, no key, no empty screen.
 */
class CatalogRepositoryTest {

    private val json = Json { ignoreUnknownKeys = true }

    private fun repo(raw: String?) = CatalogRepository(json) { raw }

    private val sample = """
        [
            {"i":1,"b":"Napa","g":"Paracetamol","s":"500 mg","f":"Tablet","m":"Beximco Pharmaceuticals Ltd."},
            {"i":2,"b":"Napa Extend","g":"Paracetamol","s":"665 mg","f":"Tablet","m":"Beximco Pharmaceuticals Ltd."},
            {"i":3,"b":"Naproxen","g":"Naproxen","s":"250 mg","f":"Tablet","m":"Square Pharmaceuticals"},
            {"i":4,"b":"Seclo","g":"Omeprazole","s":"20 mg","f":"Capsule","m":"Square Pharmaceuticals"},
            {"i":5,"b":"Alatrol","g":"Cetirizine","s":"10 mg","f":"Tablet","m":"Square Pharmaceuticals"}
        ]
    """.trimIndent()

    @Test
    fun `queries shorter than the minimum return nothing`() {
        val results = runBlocking { repo(sample).search("n").getOrThrow() }
        assertTrue(results.isEmpty())
    }

    @Test
    fun `exact brand beats brand prefix beats substring`() {
        // Exact: "napa" is Napa first; Naproxen does not contain "napa" and
        // must not be suggested.
        val exact = runBlocking { repo(sample).search("napa").getOrThrow() }
        assertEquals(listOf("Napa", "Napa Extend"), exact.map { it.brandName })

        // Prefix: all three start with "nap", shortest brand first.
        val prefix = runBlocking { repo(sample).search("nap").getOrThrow() }
        assertEquals(listOf("Napa", "Naproxen", "Napa Extend"), prefix.map { it.brandName })

        // Substring: "apa" matches inside the brand only.
        val substring = runBlocking { repo(sample).search("apa").getOrThrow() }
        assertEquals(listOf("Napa", "Napa Extend"), substring.map { it.brandName })
    }

    @Test
    fun `generic name search finds the molecule`() {
        val results = runBlocking { repo(sample).search("omeprazole").getOrThrow() }
        assertEquals(listOf("Seclo"), results.map { it.brandName })
    }

    @Test
    fun `manufacturer search surfaces the company`() {
        val results = runBlocking { repo(sample).search("beximco").getOrThrow() }
        assertEquals(2, results.size)
        assertTrue(results.all { it.manufacturerName.contains("Beximco") })
    }

    @Test
    fun `missing data degrades to empty suggestions, never an error`() {
        val results = runBlocking { repo(null).search("napa").getOrThrow() }
        assertTrue(results.isEmpty())
    }

    @Test
    fun `bundled bangladesh catalogue answers household searches offline`() {
        val file = listOf(
            "src/main/assets/catalog/medicines.json",
            "app/src/main/assets/catalog/medicines.json",
        ).map(::File).firstOrNull { it.exists() }
            ?: error("bundled catalogue asset missing from the source tree")

        runBlocking {
            val catalog = CatalogRepository(json) { file.readText() }

            val napa = catalog.search("napa").getOrThrow()
            assertTrue(
                "Napa must be suggested for 'napa'",
                napa.any { it.brandName.equals("Napa", ignoreCase = true) },
            )

            val seclo = catalog.search("seclo").getOrThrow()
            assertTrue(seclo.any { it.brandName.equals("Seclo", ignoreCase = true) })

            val generic = catalog.search("paracetamol").getOrThrow()
            assertTrue("generic search must return real rows", generic.isNotEmpty())

            val broad = catalog.search("na").getOrThrow()
            assertTrue(
                "results stay scannable (<= ${CatalogRepository.MAX_RESULTS})",
                broad.size <= CatalogRepository.MAX_RESULTS,
            )
        }
    }
}
