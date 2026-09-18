package bd.rakho.pharmacy

import android.app.Application
import bd.rakho.pharmacy.di.AppContainer
import bd.rakho.pharmacy.di.ContainerHolder
import bd.rakho.pharmacy.work.ReminderNotifications
import bd.rakho.pharmacy.work.ReminderScheduler
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

class RakhoApp : Application() {

    private val appScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    override fun onCreate() {
        super.onCreate()

        val container = AppContainer(this)
        ContainerHolder.install(container)

        ReminderNotifications.ensureChannel(this)

        appScope.launch {
            container.initialize()
            // The daily reminder only makes sense once a pharmacy is connected.
            val session = container.sessionStore.current()
            if (session.isConnected && session.notificationsEnabled) {
                ReminderScheduler.schedule(this@RakhoApp)
            }
        }
    }
}
