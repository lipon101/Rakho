package com.lipon.rakho.feature.dues

import android.content.Context
import android.content.Intent
import android.net.Uri

/**
 * Sending a baki reminder over WhatsApp — no SMS cost, no server, and it is
 * already the channel Bangladeshi shops use to chase credit. The message is
 * built on device and handed to WhatsApp (or any text-capable app) through a
 * standard intent; nothing leaves the phone unless the shopkeeper taps send.
 */
object BakiShare {

    /**
     * Normalises a Bangladeshi number for wa.me (international, digits only):
     * 01XXXXXXXXX → 8801XXXXXXXXX, 1XXXXXXXXX → 8801XXXXXXXXX, and numbers
     * already in +880/880 form are kept. Anything too short to be a phone
     * returns empty, and the caller falls back to a plain text share.
     */
    fun whatsappNumber(raw: String): String {
        val digits = raw.filter { it.isDigit() }
        return when {
            digits.length == 11 && digits.startsWith("01") -> "88$digits"
            digits.length == 10 && digits.startsWith("1") -> "880$digits"
            digits.length == 13 && digits.startsWith("880") -> digits
            digits.length == 12 && digits.startsWith("880") -> digits
            digits.length in 10..12 && !digits.startsWith("0") -> "880$digits"
            else -> ""
        }
    }

    fun send(context: Context, phone: String, message: String, chooserTitle: String) {
        val number = whatsappNumber(phone)
        if (number.isNotEmpty()) {
            val wa = Intent(
                Intent.ACTION_VIEW,
                Uri.parse("https://wa.me/$number?text=${Uri.encode(message)}"),
            ).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            if (wa.resolveActivity(context.packageManager) != null) {
                runCatching { context.startActivity(wa) }
                return
            }
        }
        val send = Intent(Intent.ACTION_SEND)
            .setType("text/plain")
            .putExtra(Intent.EXTRA_TEXT, message)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        runCatching {
            context.startActivity(Intent.createChooser(send, chooserTitle).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        }
    }
}
