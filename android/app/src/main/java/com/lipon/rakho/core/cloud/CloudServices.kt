package com.lipon.rakho.core.cloud

import android.content.Context
import android.os.Bundle
import com.google.firebase.FirebaseApp
import com.google.firebase.analytics.FirebaseAnalytics
import com.google.firebase.crashlytics.FirebaseCrashlytics
import com.google.firebase.firestore.FirebaseFirestore
import com.google.firebase.firestore.FirebaseFirestoreSettings
import com.google.firebase.firestore.PersistentCacheSettings

/**
 * Cloud sign-in, crash reporting and usage analytics.
 *
 * Firebase supplies all three, but it only exists once the app is linked to a
 * Firebase project (app/google-services.json). Every entry point below is
 * feature-detected and failure-tolerant: on a checkout without that file the
 * app behaves exactly as it does today rather than crashing on a missing
 * default Firebase app. Dropping the file in turns everything on with no code
 * change — see the conditional plugins in app/build.gradle.kts.
 *
 * Nothing here ever blocks, prompts, or throws: monitoring must not be able to
 * take a shop offline.
 */
object CloudServices {

    enum class Status {
        /** No linked Firebase project — sign-in, crashes and analytics are off. */
        NOT_LINKED,

        /** Firebase is configured and reporting. */
        ACTIVE,
    }

    @Volatile
    private var resolved = false

    @Volatile
    private var appContext: Context? = null

    @Volatile
    var status: Status = Status.NOT_LINKED
        private set

    val isActive: Boolean get() = status == Status.ACTIVE

    /**
     * Detects Firebase once, at process start. Safe to call from any thread
     * and cheap when Firebase is absent.
     */
    @JvmStatic
    fun init(context: Context) {
        if (resolved) return
        synchronized(this) {
            if (resolved) return
            appContext = context.applicationContext
            // The google-services plugin generates the resources that let
            // FirebaseInitProvider create the default app. Without it this
            // throws IllegalStateException — which is simply "not linked".
            val linked = runCatching { FirebaseApp.getInstance() }.isSuccess
            status = if (linked) Status.ACTIVE else Status.NOT_LINKED
            resolved = true
            if (linked) {
                // No sign-in happens here: the app gates on a real Firebase
                // Auth account (AuthScreen). Monitoring only reports which
                // install an event came from via [identify] after sign-in.
                runCatching {
                    FirebaseCrashlytics.getInstance()
                        .setCrashlyticsCollectionEnabled(true)
                }
                // Disk persistence is what lets a counter sale be written with
                // no network: the batch queues locally and replays once. This
                // must happen before any Firestore read or write is issued.
                runCatching {
                    val db = FirebaseFirestore.getInstance()
                    if (!db.firestoreSettings.isPersistenceEnabled) {
                        db.firestoreSettings = FirebaseFirestoreSettings.Builder()
                            .setLocalCacheSettings(PersistentCacheSettings.newBuilder().build())
                            .build()
                    }
                }
            }
        }
    }

    /**
     * Binds crashes and analytics to this install and (once signed in) to the
     * pharmacy's Firebase account. [uid] is empty while signed out, in which
     * case the anonymous device id is used instead. Never a customer name.
     */
    @JvmStatic
    fun identify(deviceId: String, uid: String) {
        if (!isActive || deviceId.isBlank()) return
        val signedIn = uid.isNotBlank()
        runCatching {
            val crashlytics = FirebaseCrashlytics.getInstance()
            crashlytics.setUserId(if (signedIn) uid else deviceId)
            crashlytics.setCustomKey("signed_in", signedIn)
        }
        runCatching {
            val analytics = FirebaseAnalytics.getInstance(appContext ?: return)
            analytics.setUserProperty("signed_in", if (signedIn) "true" else "false")
        }
    }

    /**
     * Counts a product event. [event] must be [a-z0-9_] and start with a
     * letter — Firebase drops anything else rather than raising, so callers do
     * not need to guard.
     */
    @JvmStatic
    fun track(event: String, vararg params: Pair<String, String>) {
        if (!isActive) return
        val context = appContext ?: return
        runCatching {
            val bundle = Bundle()
            params.forEach { (key, value) -> bundle.putString(key, value) }
            FirebaseAnalytics.getInstance(context).logEvent(event, bundle)
        }
    }

    /** Files a non-fatal so it shows up in the Crashlytics console. */
    @JvmStatic
    fun report(throwable: Throwable, message: String = "") {
        if (!isActive) return
        runCatching {
            val crashlytics = FirebaseCrashlytics.getInstance()
            if (message.isNotBlank()) crashlytics.log(message)
            crashlytics.recordException(throwable)
        }
    }

    /** Attaches a breadcrumb to the next crash report. */
    @JvmStatic
    fun log(line: String) {
        if (!isActive) return
        runCatching { FirebaseCrashlytics.getInstance().log(line) }
    }
}
