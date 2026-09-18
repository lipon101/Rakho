package bd.rakho.pharmacy.work

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import bd.rakho.pharmacy.MainActivity
import bd.rakho.pharmacy.R
import bd.rakho.pharmacy.core.time.DhakaTime
import bd.rakho.pharmacy.di.ContainerHolder
import kotlinx.coroutines.flow.first
import java.time.Duration
import java.time.LocalDateTime
import java.time.LocalTime
import java.util.concurrent.TimeUnit

/**
 * Once a day, before the shop opens, tell the pharmacy what is about to expire
 * or run out. This is the notification that keeps the app installed: it is the
 * reason a pharmacist opens it every morning.
 */
class ExpiryReminderWorker(
    context: Context,
    params: WorkerParameters,
) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result {
        val container = runCatching { ContainerHolder.get() }.getOrNull() ?: return Result.success()
        if (!container.ready.value) return Result.retry()

        val session = container.sessionStore.current()
        if (!session.isConnected || !session.notificationsEnabled) return Result.success()

        val alerts = container.inventory.observeAlerts().first()
        val expiring = alerts.expiringSoon.size
        val expired = alerts.expired.size
        val lowStock = alerts.lowStock.size
        if (expiring == 0 && expired == 0 && lowStock == 0) return Result.success()

        ReminderNotifications.show(applicationContext, expiring, expired, lowStock)
        return Result.success()
    }
}

/** Channel + posting, kept in one place so the foreground app can reuse it. */
object ReminderNotifications {

    const val CHANNEL_EXPIRY = "expiry_reminders"

    fun ensureChannel(context: Context) {
        val manager = context.getSystemService(NotificationManager::class.java) ?: return
        if (manager.getNotificationChannel(CHANNEL_EXPIRY) != null) return
        manager.createNotificationChannel(
            NotificationChannel(
                CHANNEL_EXPIRY,
                context.getString(R.string.notif_channel_expiry),
                NotificationManager.IMPORTANCE_DEFAULT,
            ).apply {
                description = context.getString(R.string.settings_notifications_desc)
            },
        )
    }

    fun show(context: Context, expiring: Int, expired: Int, lowStock: Int) {
        ensureChannel(context)
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) !=
            PackageManager.PERMISSION_GRANTED
        ) {
            return
        }
        val intent = Intent(context, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
        val pendingIntent = PendingIntent.getActivity(
            context,
            0,
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )

        val body = context.getString(
            R.string.notif_expiry_body,
            maxOf(expiring, expired),
            lowStock,
        )
        val notification = NotificationCompat.Builder(context, CHANNEL_EXPIRY)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(context.getString(R.string.notif_expiry_title))
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setContentIntent(pendingIntent)
            .setAutoCancel(true)
            .setPriority(NotificationCompat.PRIORITY_DEFAULT)
            .build()

        runCatching {
            NotificationManagerCompat.from(context).notify(NOTIFICATION_ID, notification)
        }
    }

    private const val NOTIFICATION_ID = 1001
}

/** Schedules the daily reminder, aligned to a sensible morning hour in Dhaka. */
object ReminderScheduler {

    private const val WORK_NAME = "rakho_expiry_reminder"

    fun schedule(context: Context) {
        val request = PeriodicWorkRequestBuilder<ExpiryReminderWorker>(1, TimeUnit.DAYS)
            .setInitialDelay(initialDelayMinutes(), TimeUnit.MINUTES)
            .setConstraints(Constraints.NONE)
            .build()

        WorkManager.getInstance(context).enqueueUniquePeriodicWork(
            WORK_NAME,
            ExistingPeriodicWorkPolicy.UPDATE,
            request,
        )
    }

    fun cancel(context: Context) {
        WorkManager.getInstance(context).cancelUniqueWork(WORK_NAME)
    }

    /** Minutes until 09:00 Dhaka time, so the reminder lands before opening. */
    private fun initialDelayMinutes(): Long {
        val now = LocalDateTime.now(DhakaTime.ZONE)
        var target = now.toLocalDate().atTime(LocalTime.of(9, 0))
        if (!target.isAfter(now)) target = target.plusDays(1)
        return Duration.between(now, target).toMinutes().coerceAtLeast(1)
    }
}
