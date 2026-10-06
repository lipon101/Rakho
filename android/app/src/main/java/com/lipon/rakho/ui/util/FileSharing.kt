package com.lipon.rakho.ui.util

import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.core.content.FileProvider
import java.io.File

/**
 * Writes generated text (CSV reports, JSON backups) to the private exports
 * folder and offers it to other apps. The file never leaves the app sandbox
 * unless the pharmacy explicitly shares it.
 */
object FileSharing {

    private const val AUTHORITY_SUFFIX = ".fileprovider"

    fun shareText(
        context: Context,
        fileName: String,
        content: String,
        mimeType: String = "text/csv",
        chooserTitle: String,
    ): Result<Unit> = runCatching {
        val dir = File(context.cacheDir, "exports").apply { mkdirs() }
        // Keep only the most recent exports so the cache cannot grow unbounded.
        dir.listFiles()
            ?.sortedByDescending { it.lastModified() }
            ?.drop(4)
            ?.forEach { it.delete() }

        val file = File(dir, fileName)
        file.writeText(content)

        val uri: Uri = FileProvider.getUriForFile(
            context,
            context.packageName + AUTHORITY_SUFFIX,
            file,
        )
        val intent = Intent(Intent.ACTION_SEND).apply {
            type = mimeType
            putExtra(Intent.EXTRA_STREAM, uri)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        context.startActivity(
            Intent.createChooser(intent, chooserTitle).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
        )
    }
}
