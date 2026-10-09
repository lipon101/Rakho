package com.lipon.rakho.core.domain

import com.lipon.rakho.core.model.Medicine

/**
 * Ranked, instant search over the pharmacy's OWN medicines — the single
 * matcher behind New Sale, Stock and Receive stock, so all three behave
 * identically and every keystroke filters the full live list in memory.
 *
 * Matches brand, generic, strength, dosage form, manufacturer and barcode
 * (case-insensitive). Ranking mirrors the bundled catalogue search a
 * shopkeeper already knows: exact brand, brand prefix (shortest first),
 * brand substring, generic, then manufacturer — so "napa" offers Napa before
 * Napa Extend before Naproxen, and an exact barcode scan jumps straight to
 * its medicine.
 *
 * No result cap: the medicine list is small enough to rank fully, and the UI
 * virtualizes, so hiding real stock behind `.take(N)` was a data bug, not a
 * performance choice. An empty query returns everything (caller order kept).
 */
object MedicineSearch {

    /** Projection of one medicine's searchable text, lowercased once. */
    private data class Indexed(
        val medicine: Medicine,
        val brand: String,
        val generic: String,
        val strength: String,
        val form: String,
        val barcode: String,
    )

    fun rank(medicines: List<Medicine>, query: String): List<Medicine> {
        val needle = query.trim().lowercase()
        if (needle.isEmpty()) return medicines
        val scored = ArrayList<Triple<Int, Int, Medicine>>(32)
        for (medicine in medicines) {
            val entry = Indexed(
                medicine = medicine,
                brand = medicine.brandName.lowercase(),
                generic = medicine.genericName.lowercase(),
                strength = medicine.strength.lowercase(),
                form = medicine.dosageForm.lowercase(),
                barcode = medicine.barcode.trim().lowercase(),
            )
            val tier = when {
                entry.barcode.isNotEmpty() && entry.barcode == needle -> 0
                entry.brand == needle -> 1
                entry.brand.startsWith(needle) -> 2
                entry.brand.contains(needle) -> 3
                entry.generic.startsWith(needle) -> 4
                entry.generic.contains(needle) -> 5
                entry.strength.contains(needle) -> 6
                entry.form.contains(needle) -> 7
                entry.barcode.isNotEmpty() && entry.barcode.contains(needle) -> 8
                else -> continue
            }
            scored.add(Triple(tier, medicine.brandName.length, medicine))
        }
        if (scored.isEmpty()) return emptyList()
        scored.sortWith(compareBy({ it.first }, { it.second }, { it.third.brandName }))
        return scored.map { it.third }
    }

    /**
     * Active-only variant for the counter: inactive medicines are never
     * sellable, so New Sale searches them out of existence.
     */
    fun rankActive(medicines: List<Medicine>, query: String): List<Medicine> =
        rank(medicines.filter { it.isActive }, query)
}
