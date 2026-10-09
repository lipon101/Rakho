import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    // No kotlin-android plugin: AGP 9 compiles Kotlin itself.
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
}

/**
 * Firebase is optional at build time.
 *
 * The google-services plugin aborts the build when app/google-services.json
 * is missing, which would make a plain clone unbuildable. Both plugins are
 * therefore applied only when that config file is actually present: drop it
 * in and auth, Crashlytics and Analytics switch on without editing this file.
 * The SDK dependencies below are always compiled so the code stays warning-free
 * either way; without config they simply never initialise at runtime.
 */
val hasFirebaseConfig = file("google-services.json").exists()
if (hasFirebaseConfig) {
    apply(plugin = "com.google.gms.google-services")
    apply(plugin = "com.google.firebase.crashlytics")
}

/**
 * Release signing is read from environment variables so the keystore and its
 * passwords are never committed. Locally/CI without those vars the release
 * build stays unsigned but the debug build works fully.
 */
val keystorePath: String? = System.getenv("RAKHO_KEYSTORE_PATH")
val keystorePassword: String? = System.getenv("RAKHO_KEYSTORE_PASSWORD")
val keyAlias: String? = System.getenv("RAKHO_KEY_ALIAS")
val keyPassword: String? = System.getenv("RAKHO_KEY_PASSWORD")
val hasReleaseSigning = listOf(keystorePath, keystorePassword, keyAlias, keyPassword).all { !it.isNullOrBlank() }

android {
    namespace = "com.lipon.rakho"
    // compileSdk 37 is what the current AndroidX/Compose releases require.
    // targetSdk stays at 36, the API level Google Play requires new apps to
    // target, so runtime behaviour is the Android 16 behaviour we tested.
    compileSdk = 37

    defaultConfig {
        applicationId = "com.lipon.rakho"
        minSdk = 26
        targetSdk = 36
        versionCode = 1
        versionName = "1.0.0"

        vectorDrawables { useSupportLibrary = true }
    }

    androidResources {
        // Ship only the two languages the app actually supports.
        localeFilters += listOf("en", "bn")
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    signingConfigs {
        if (hasReleaseSigning) {
            create("release") {
                storeFile = file(keystorePath!!)
                storePassword = keystorePassword
                this.keyAlias = keyAlias
                keyPassword = keyPassword
            }
        }
    }

    buildTypes {
        debug {
            applicationIdSuffix = ".debug"
            versionNameSuffix = "-debug"
        }
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            if (hasReleaseSigning) {
                signingConfig = signingConfigs.getByName("release")
            }
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    packaging {
        resources {
            excludes += setOf(
                "/META-INF/{AL2.0,LGPL2.1}",
                "/META-INF/DEPENDENCIES",
                "/META-INF/INDEX.LIST",
            )
        }
    }

    testOptions {
        unitTests {
            isReturnDefaultValues = true
            isIncludeAndroidResources = true
        }
    }

    lint {
        abortOnError = true
        warningsAsErrors = false
        disable += setOf("GradleDependency", "OldTargetApi")
    }
}

kotlin {
    compilerOptions {
        jvmTarget.set(JvmTarget.JVM_17)
    }
}

dependencies {
    val bom = platform(libs.androidx.compose.bom)
    implementation(bom)
    androidTestImplementation(bom)

    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.core.splashscreen)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.navigation.compose)
    implementation(libs.androidx.fragment)
    implementation(libs.androidx.datastore.preferences)
    implementation(libs.androidx.work.runtime.ktx)

    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.graphics)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.androidx.compose.material3)
    implementation(libs.androidx.compose.material.icons.core)
    implementation(libs.androidx.compose.material.icons.extended)

    implementation(libs.kotlinx.serialization.json)
    implementation(libs.kotlinx.coroutines.android)

    // Cloud: auth, realtime database, crash reporting and usage analytics.
    // Everything the pharmacy keeps lives in Firestore; no other backend exists.
    implementation(platform(libs.firebase.bom))
    implementation(libs.firebase.auth)
    implementation(libs.firebase.crashlytics)
    implementation(libs.firebase.analytics)
    implementation(libs.firebase.firestore)

    // Camera + barcode scanning
    implementation(libs.camerax.core)
    implementation(libs.camerax.camera2)
    implementation(libs.camerax.lifecycle)
    implementation(libs.camerax.view)
    implementation(libs.mlkit.barcode)

    // Image loading
    implementation(libs.coil)

    debugImplementation(libs.androidx.compose.ui.tooling)
    debugImplementation(libs.androidx.compose.ui.test.manifest)

    testImplementation(libs.junit)
    testImplementation(libs.mockk)
    testImplementation(libs.turbine)
    testImplementation(libs.kotlinx.coroutines.test)

    androidTestImplementation(libs.androidx.test.junit)
    androidTestImplementation(libs.androidx.test.espresso)
    androidTestImplementation(libs.androidx.compose.ui.test.junit4)
}
