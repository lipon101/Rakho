// AGP 9 compiles Kotlin itself (built-in Kotlin), so the kotlin-android plugin
// must not be applied anywhere. AGP pins KGP 2.2.10 by default; the Kotlin
// compiler plugins below (compose, serialization) are declared at 2.4.20, so the
// matching KGP is put on the buildscript classpath before those plugins load.
buildscript {
    dependencies {
        classpath("org.jetbrains.kotlin:kotlin-gradle-plugin:${libs.versions.kotlin.get()}")
    }
}

plugins {
    alias(libs.plugins.android.application) apply false
    alias(libs.plugins.kotlin.compose) apply false
    alias(libs.plugins.kotlin.serialization) apply false
}
