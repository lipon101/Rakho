package com.lipon.rakho

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.ui.Modifier
import androidx.core.splashscreen.SplashScreen.Companion.installSplashScreen
import com.lipon.rakho.ui.nav.RakhoRoot
import com.lipon.rakho.ui.theme.RakhoTheme

class MainActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        val splash = installSplashScreen()
        super.onCreate(savedInstanceState)

        // Keep the splash up until the persisted session has been loaded so the
        // first frame is never a half-configured screen.
        splash.setKeepOnScreenCondition { !containerReady() }

        enableEdgeToEdge()
        requestNotificationPermissionIfNeeded()
        setContent {
            RakhoTheme {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background,
                ) {
                    RakhoRoot()
                }
            }
        }
    }

    private fun containerReady(): Boolean =
        runCatching { com.lipon.rakho.di.ContainerHolder.get().ready.value }.getOrDefault(false)

    /**
     * Expiry reminders are the app's daily value, so the permission is asked
     * once at launch on Android 13+. Denying it only silences reminders —
     * every other feature keeps working.
     */
    private fun requestNotificationPermissionIfNeeded() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return
        val granted = ContextCompat.checkSelfPermission(
            this,
            Manifest.permission.POST_NOTIFICATIONS,
        ) == PackageManager.PERMISSION_GRANTED
        if (granted) return
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { }
            .launch(Manifest.permission.POST_NOTIFICATIONS)
    }
}
