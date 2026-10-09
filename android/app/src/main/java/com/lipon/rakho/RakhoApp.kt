package com.lipon.rakho

import android.app.Application
import com.lipon.rakho.core.cloud.CloudServices
import com.lipon.rakho.di.AppContainer
import com.lipon.rakho.di.ContainerHolder
import com.lipon.rakho.work.ReminderNotifications
import com.lipon.rakho.work.ReminderScheduler
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

class RakhoApp : Application() {

    private val appScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    override fun onCreate() {
        super.onCreate()

        ReminderNotifications.ensureChannel(this)

        // Cloud monitoring comes up first — before any Firestore instance is
        // built — so disk persistence is configured while that is still legal,
        // and if anything below fails we still want the report.
        CloudServices.init(this)

        val container = AppContainer(this)
        ContainerHolder.install(container)

        appScope.launch {
            container.initialize()
            val session = container.sessionStore.current()
            // Ties crash reports and analytics to this install and account.
            CloudServices.identify(
                deviceId = container.sessionStore.ensureDeviceId(),
                uid = container.authRepo.userId,
            )
            // Schedule regardless of sign-in state — the worker checks auth
            // itself, so reminders start the day the shop first signs in.
            if (session.notificationsEnabled) {
                ReminderScheduler.schedule(this@RakhoApp)
            }
        }
    }
}
