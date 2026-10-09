package com.lipon.rakho.feature.dues

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * The phone normaliser behind every WhatsApp baki reminder: shopkeepers type
 * numbers however they remember them, and wa.me only accepts the international
 * form. A wrong mapping messages a stranger with someone's dues, so each
 * shape the counter actually uses is pinned here.
 */
class BakiShareTest {

    @Test
    fun `local BD mobile gets the 88 country prefix`() {
        assertEquals("8801712345678", BakiShare.whatsappNumber("01712345678"))
    }

    @Test
    fun `spaces and dashes are ignored`() {
        assertEquals("8801712345678", BakiShare.whatsappNumber("01712-345 678"))
    }

    @Test
    fun `plus international form is kept`() {
        assertEquals("8801712345678", BakiShare.whatsappNumber("+8801712345678"))
    }

    @Test
    fun `ten digit without leading zero is completed`() {
        assertEquals("8801712345678", BakiShare.whatsappNumber("1712345678"))
    }

    @Test
    fun `already international ten-digit form is completed`() {
        assertEquals("8801912345678", BakiShare.whatsappNumber("1912345678"))
    }

    @Test
    fun `junk and too-short numbers are refused`() {
        assertEquals("", BakiShare.whatsappNumber(""))
        assertEquals("", BakiShare.whatsappNumber("abc"))
        assertEquals("", BakiShare.whatsappNumber("0153"))
    }
}
