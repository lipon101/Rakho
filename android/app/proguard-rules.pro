# Rakho release rules.
#
# kotlinx.serialization keeps generated serializers reachable reflectively.
-keepattributes *Annotation*, InnerClasses
-dontnote kotlinx.serialization.**

-keepclassmembers class kotlinx.serialization.json.** { *; }
-keepclasseswithmembers class com.lipon.rakho.data.remote.dto.** {
    kotlinx.serialization.KSerializer serializer(...);
}
-keep,includedescriptorclasses class com.lipon.rakho.data.remote.**$$serializer { *; }
-keepclassmembers class com.lipon.rakho.** {
    *** Companion;
}
# Serializer lookup happens by class name at runtime.
-keep class com.lipon.rakho.data.remote.dto.** { *; }
-keepnames class kotlinx.serialization.internal.** { *; }
-dontwarn kotlinx.serialization.**

# Retrofit / OkHttp
-dontwarn okhttp3.**
-dontwarn okio.**
-dontwarn retrofit2.**
-keep,allowobfuscation,allowshrinking interface retrofit2.Call
-keep,allowobfuscation,allowshrinking class kotlin.coroutines.Continuation
-keep,allowobfuscation,allowshrinking class retrofit2.Response

# Google Play Billing
-keep class com.android.vending.billing.** { *; }
