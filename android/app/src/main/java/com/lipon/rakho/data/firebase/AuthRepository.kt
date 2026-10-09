package com.lipon.rakho.data.firebase

import com.google.firebase.auth.FirebaseAuth
import com.google.firebase.auth.FirebaseAuthInvalidCredentialsException
import com.google.firebase.auth.FirebaseAuthUserCollisionException
import com.google.firebase.auth.FirebaseUser
import com.google.firebase.auth.PhoneAuthCredential
import com.google.firebase.auth.PhoneAuthOptions
import com.google.firebase.auth.PhoneAuthProvider
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.tasks.await
import java.util.concurrent.TimeUnit

/**
 * Authentication operations using Firebase Auth.
 *
 * Supports two sign-in methods:
 *  1. Email + password (quick registration for pharmacy owners)
 *  2. Phone OTP (Bangladesh mobile number — bKash/Nagad users already have one)
 *
 * On first sign-in, [FirestoreRepository.ensurePharmacyProfile] should be
 * called to create the pharmacy document if it does not yet exist.
 */
class AuthRepository {

    private val auth = FirebaseAuth.getInstance()

    /** The currently signed-in Firebase user, or null. */
    val currentUser: FirebaseUser? get() = auth.currentUser

    /** True when a user is signed in (email or phone). */
    val isLoggedIn: Boolean get() = auth.currentUser != null

    /** Emits whenever the auth state changes (sign-in, sign-out, token refresh). */
    fun observeAuthState(): Flow<FirebaseUser?> = callbackFlow {
        val listener = FirebaseAuth.AuthStateListener { firebaseAuth ->
            trySend(firebaseAuth.currentUser)
        }
        auth.addAuthStateListener(listener)
        awaitClose { auth.removeAuthStateListener(listener) }
    }

    // ─────────────────────────────────────────────────────────────────────
    // Email / Password
    // ─────────────────────────────────────────────────────────────────────

    /**
     * Creates a new account. Returns [AuthResult.Success] on success.
     */
    suspend fun createAccount(email: String, password: String): AuthResult {
        return try {
            auth.createUserWithEmailAndPassword(email.trim(), password).await()
            AuthResult.Success
        } catch (e: FirebaseAuthUserCollisionException) {
            AuthResult.EmailAlreadyInUse
        } catch (e: FirebaseAuthInvalidCredentialsException) {
            AuthResult.InvalidCredentials
        } catch (e: Exception) {
            AuthResult.Error(e.message ?: "Unknown error")
        }
    }

    /**
     * Signs in with email and password.
     */
    suspend fun signInWithEmail(email: String, password: String): AuthResult {
        return try {
            auth.signInWithEmailAndPassword(email.trim(), password).await()
            AuthResult.Success
        } catch (e: FirebaseAuthInvalidCredentialsException) {
            AuthResult.InvalidCredentials
        } catch (e: Exception) {
            AuthResult.Error(e.message ?: "Unknown error")
        }
    }

    /**
     * Sends a password reset email.
     */
    suspend fun sendPasswordReset(email: String): AuthResult {
        return try {
            auth.sendPasswordResetEmail(email.trim()).await()
            AuthResult.Success
        } catch (e: Exception) {
            AuthResult.Error(e.message ?: "Unknown error")
        }
    }

    // ─────────────────────────────────────────────────────────────────────
    // Phone / OTP
    // ─────────────────────────────────────────────────────────────────────

    /**
     * Signs in with a [PhoneAuthCredential] obtained from OTP verification.
     * Call this after the user enters the code sent to their phone.
     */
    suspend fun signInWithPhoneCredential(credential: PhoneAuthCredential): AuthResult {
        return try {
            auth.signInWithCredential(credential).await()
            AuthResult.Success
        } catch (e: FirebaseAuthInvalidCredentialsException) {
            AuthResult.InvalidCredentials
        } catch (e: Exception) {
            AuthResult.Error(e.message ?: "Unknown error")
        }
    }

    // ─────────────────────────────────────────────────────────────────────
    // Sign out
    // ─────────────────────────────────────────────────────────────────────

    fun signOut() {
        auth.signOut()
    }

    /**
     * Permanently deletes the signed-in account. Firestore data is wiped by
     * the caller before this runs; the auth record itself is what stops the
     * email from ever coming back with old data attached.
     */
    suspend fun deleteAccount(): AuthResult = try {
        val user = auth.currentUser ?: return AuthResult.Error("Not signed in")
        user.delete().await()
        AuthResult.Success
    } catch (e: Exception) {
        AuthResult.Error(e.message ?: "Could not delete account")
    }

    /** Updates the display name on the current user. */
    suspend fun updateDisplayName(name: String) {
        val user = auth.currentUser ?: return
        val profileUpdates = com.google.firebase.auth.UserProfileChangeRequest.Builder()
            .setDisplayName(name)
            .build()
        user.updateProfile(profileUpdates).await()
    }

    /** The display name from Firebase Auth (may differ from the Firestore pharmacy name). */
    val displayName: String get() = auth.currentUser?.displayName.orEmpty()
    val email: String get() = auth.currentUser?.email.orEmpty()
    val phoneNumber: String get() = auth.currentUser?.phoneNumber.orEmpty()
    val userId: String get() = auth.currentUser?.uid.orEmpty()
}

sealed interface AuthResult {
    data object Success : AuthResult
    data object EmailAlreadyInUse : AuthResult
    data object InvalidCredentials : AuthResult
    data class Error(val message: String) : AuthResult
}
