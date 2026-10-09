package com.lipon.rakho.core.domain

import com.lipon.rakho.core.model.Medicine
import com.lipon.rakho.core.money.Money
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The counter's search must surface the right medicine on every keystroke:
 * exact matches first, then prefixes, then substrings — across brand,
 * generic, strength, form, manufacturer and barcode — with no hidden caps.
 */
class MedicineSearchTest {

    private fun medicine(
        id: String,
        brand: String,
        generic: String = "",
        strength: String = "",
        form: String = "",
        barcode: String = "",
        active: Boolean = true,
    ) = Medicine(
        id = id,
        brandName = brand,
        genericName = generic,
        strength = strength,
        dosageForm = form,
        barcode = barcode,
        defaultSellingPrice = Money(100_00),
        isActive = active,
    )

    private val stock = listOf(
        medicine("1", "Napa", "Paracetamol", "500 mg", "Tablet", "8941111"),
        medicine("2", "Napa Extend", "Paracetamol", "665 mg", "Tablet"),
        medicine("3", "Naproxen", "Naproxen", "250 mg", "Tablet"),
        medicine("4", "Seclo", "Omeprazole", "20 mg", "Capsule"),
        medicine("5", "OldInactive", "Paracetamol", "500 mg", "Tablet", active = false),
    )

    @Test
    fun `empty query returns the full live list`() {
        assertEquals(stock, MedicineSearch.rank(stock, ""))
        assertEquals(stock, MedicineSearch.rank(stock, "   "))
    }

    @Test
    fun `exact brand beats prefix beats substring`() {
        val exact = MedicineSearch.rank(stock, "napa")
        assertEquals(listOf("Napa", "Napa Extend"), exact.map { it.brandName })

        val prefix = MedicineSearch.rank(stock, "nap")
        assertEquals(listOf("Napa", "Naproxen", "Napa Extend"), prefix.map { it.brandName })

        val substring = MedicineSearch.rank(stock, "apa")
        assertEquals(listOf("Napa", "Napa Extend"), substring.map { it.brandName })
    }

    @Test
    fun `generic strength form and maker all match`() {
        assertEquals(listOf("Seclo"), MedicineSearch.rank(stock, "omeprazole").map { it.brandName })
        assertEquals(listOf("Seclo"), MedicineSearch.rank(stock, "20 mg").map { it.brandName })
        assertEquals(listOf("Seclo"), MedicineSearch.rank(stock, "capsule").map { it.brandName })
    }

    @Test
    fun `exact barcode jumps straight to its medicine`() {
        val results = MedicineSearch.rank(stock, "8941111")
        assertEquals(listOf("Napa"), results.map { it.brandName })
    }

    @Test
    fun `search is case-insensitive and trims`() {
        val results = MedicineSearch.rank(stock, "  NAPA  ")
        assertEquals(listOf("Napa", "Napa Extend"), results.map { it.brandName })
    }

    @Test
    fun `no match returns empty, never a fallback`() {
        assertTrue(MedicineSearch.rank(stock, "zzz-no-such-medicine").isEmpty())
    }

    @Test
    fun `active-only search hides inactive medicines`() {
        val results = MedicineSearch.rankActive(stock, "paracetamol")
        assertTrue(results.none { it.brandName == "OldInactive" })
        assertEquals(listOf("Napa", "Napa Extend"), results.map { it.brandName })
    }

    @Test
    fun `no result cap hides real stock`() {
        val many = (1..300).map { i -> medicine("m$i", "MedBrand$i", "Generic$i") }
        val results = MedicineSearch.rank(many, "medbrand")
        assertEquals(300, results.size)
    }
}
