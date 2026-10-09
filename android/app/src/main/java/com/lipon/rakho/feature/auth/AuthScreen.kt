package com.lipon.rakho.feature.auth

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Email
import androidx.compose.material.icons.filled.LocalPharmacy
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.Store
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.lipon.rakho.R
import com.lipon.rakho.ui.theme.Radii
import com.lipon.rakho.ui.theme.Sizes
import com.lipon.rakho.ui.theme.Spacing

/**
 * Authentication screen: sign-in and sign-up in one surface, fully localised
 * (every string goes through resources, so Bangla shops read Bangla here).
 *
 * The flat brand fill replaces the old gradient, matching the design system:
 * white on it is 5.2:1 in light and the scheme swaps to the dark brand teal
 * with its own onPrimary ink automatically.
 */
@Composable
fun AuthScreen(
    viewModel: AuthViewModel,
    onAuthenticated: () -> Unit,
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val snackbar = remember { SnackbarHostState() }
    var showPassword by remember { mutableStateOf(false) }
    var showConfirmPassword by remember { mutableStateOf(false) }

    val resetSentText = stringResource(R.string.auth_reset_sent)

    LaunchedEffect(state.success) {
        if (state.success) onAuthenticated()
    }

    val errorText = state.error?.let { stringResource(it) }
    LaunchedEffect(errorText) {
        if (errorText != null) snackbar.showSnackbar(errorText)
    }

    LaunchedEffect(state.resetEmailSent) {
        if (state.resetEmailSent) {
            snackbar.showSnackbar(resetSentText)
        }
    }

    Scaffold(snackbarHost = { SnackbarHost(snackbar) }) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .systemBarsPadding()
                .imePadding()
                .verticalScroll(rememberScrollState()),
        ) {
            // Hero band: flat brand fill, no gradient (design system rule).
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .background(MaterialTheme.colorScheme.primary),
            ) {
                Column(
                    modifier = Modifier.padding(top = 48.dp, bottom = 56.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    Box(
                        modifier = Modifier
                            .size(80.dp)
                            .clip(CircleShape)
                            .background(MaterialTheme.colorScheme.onPrimary.copy(alpha = 0.15f)),
                        contentAlignment = Alignment.Center,
                    ) {
                        Icon(
                            imageVector = Icons.Filled.LocalPharmacy,
                            contentDescription = null,
                            tint = MaterialTheme.colorScheme.onPrimary,
                            modifier = Modifier.size(44.dp),
                        )
                    }
                    Spacer(Modifier.height(Spacing.lg))
                    Text(
                        text = stringResource(R.string.app_name),
                        style = MaterialTheme.typography.headlineLarge,
                        fontWeight = FontWeight.Bold,
                        color = MaterialTheme.colorScheme.onPrimary,
                    )
                    Text(
                        text = stringResource(R.string.auth_tagline),
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onPrimary.copy(alpha = 0.85f),
                    )
                }
            }

            // Card form
            Surface(
                shape = RoundedCornerShape(topStart = 28.dp, topEnd = 28.dp),
                color = MaterialTheme.colorScheme.background,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Column(
                    modifier = Modifier.padding(horizontal = Spacing.xl, vertical = Spacing.xl),
                    verticalArrangement = Arrangement.spacedBy(Spacing.md),
                ) {
                    // Mode toggle tabs
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clip(RoundedCornerShape(Radii.chip))
                            .background(MaterialTheme.colorScheme.surfaceVariant),
                    ) {
                        ModeTab(
                            text = stringResource(R.string.auth_sign_in),
                            selected = state.isLogin,
                            onClick = { if (!state.isLogin) viewModel.toggleMode() },
                            modifier = Modifier.weight(1f),
                        )
                        ModeTab(
                            text = stringResource(R.string.auth_sign_up),
                            selected = !state.isLogin,
                            onClick = { if (state.isLogin) viewModel.toggleMode() },
                            modifier = Modifier.weight(1f),
                        )
                    }

                    Spacer(Modifier.height(Spacing.sm))

                    // Shop name (signup only)
                    AnimatedVisibility(
                        visible = !state.isLogin,
                        enter = fadeIn() + slideInVertically(),
                        exit = fadeOut(),
                    ) {
                        OutlinedTextField(
                            value = state.shopName,
                            onValueChange = viewModel::onShopNameChange,
                            label = { Text(stringResource(R.string.auth_shop_name)) },
                            leadingIcon = {
                                Icon(Icons.Filled.Store, contentDescription = null)
                            },
                            singleLine = true,
                            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Next),
                            modifier = Modifier.fillMaxWidth(),
                        )
                    }

                    // Email
                    OutlinedTextField(
                        value = state.email,
                        onValueChange = viewModel::onEmailChange,
                        label = { Text(stringResource(R.string.auth_email)) },
                        leadingIcon = { Icon(Icons.Filled.Email, contentDescription = null) },
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(
                            keyboardType = KeyboardType.Email,
                            imeAction = ImeAction.Next,
                        ),
                        modifier = Modifier.fillMaxWidth(),
                    )

                    // Password
                    OutlinedTextField(
                        value = state.password,
                        onValueChange = viewModel::onPasswordChange,
                        label = { Text(stringResource(R.string.auth_password)) },
                        leadingIcon = { Icon(Icons.Filled.Lock, contentDescription = null) },
                        trailingIcon = {
                            IconButton(onClick = { showPassword = !showPassword }) {
                                Icon(
                                    imageVector = if (showPassword) Icons.Filled.VisibilityOff else Icons.Filled.Visibility,
                                    contentDescription = null,
                                )
                            }
                        },
                        visualTransformation = if (showPassword) VisualTransformation.None else PasswordVisualTransformation(),
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(
                            keyboardType = KeyboardType.Password,
                            imeAction = if (state.isLogin) ImeAction.Done else ImeAction.Next,
                        ),
                        modifier = Modifier.fillMaxWidth(),
                    )

                    // Confirm password (signup only)
                    AnimatedVisibility(
                        visible = !state.isLogin,
                        enter = fadeIn() + slideInVertically(),
                        exit = fadeOut(),
                    ) {
                        OutlinedTextField(
                            value = state.confirmPassword,
                            onValueChange = viewModel::onConfirmPasswordChange,
                            label = { Text(stringResource(R.string.auth_confirm_password)) },
                            leadingIcon = { Icon(Icons.Filled.Lock, contentDescription = null) },
                            trailingIcon = {
                                IconButton(onClick = { showConfirmPassword = !showConfirmPassword }) {
                                    Icon(
                                        imageVector = if (showConfirmPassword) Icons.Filled.VisibilityOff else Icons.Filled.Visibility,
                                        contentDescription = null,
                                    )
                                }
                            },
                            visualTransformation = if (showConfirmPassword) VisualTransformation.None else PasswordVisualTransformation(),
                            singleLine = true,
                            keyboardOptions = KeyboardOptions(
                                keyboardType = KeyboardType.Password,
                                imeAction = ImeAction.Done,
                            ),
                            modifier = Modifier.fillMaxWidth(),
                        )
                    }

                    // Forgot password (login only)
                    AnimatedVisibility(visible = state.isLogin) {
                        Box(modifier = Modifier.fillMaxWidth(), contentAlignment = Alignment.CenterEnd) {
                            TextButton(onClick = viewModel::showForgotPassword) {
                                Text(
                                    text = stringResource(R.string.auth_forgot),
                                    style = MaterialTheme.typography.labelMedium,
                                    color = MaterialTheme.colorScheme.primary,
                                )
                            }
                        }
                    }

                    Spacer(Modifier.height(Spacing.sm))

                    // Submit button
                    Button(
                        onClick = viewModel::submit,
                        enabled = !state.loading,
                        shape = RoundedCornerShape(Radii.button),
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(Sizes.primaryButtonHeight),
                    ) {
                        if (state.loading) {
                            CircularProgressIndicator(
                                modifier = Modifier.size(20.dp),
                                strokeWidth = 2.dp,
                                color = MaterialTheme.colorScheme.onPrimary,
                            )
                            Spacer(Modifier.width(Spacing.sm))
                        }
                        Text(
                            text = if (state.isLogin) {
                                stringResource(R.string.auth_sign_in)
                            } else {
                                stringResource(R.string.auth_create_account)
                            },
                            fontWeight = FontWeight.Bold,
                        )
                    }

                    // Divider
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier.padding(vertical = Spacing.sm),
                    ) {
                        HorizontalDivider(modifier = Modifier.weight(1f))
                        Text(
                            text = "  ${stringResource(R.string.auth_or)}  ",
                            style = MaterialTheme.typography.labelMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        HorizontalDivider(modifier = Modifier.weight(1f))
                    }

                    // Toggle link
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.Center,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(
                            text = if (state.isLogin) {
                                stringResource(R.string.auth_no_account)
                            } else {
                                stringResource(R.string.auth_have_account)
                            },
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        TextButton(onClick = viewModel::toggleMode) {
                            Text(
                                text = if (state.isLogin) {
                                    stringResource(R.string.auth_sign_up)
                                } else {
                                    stringResource(R.string.auth_sign_in)
                                },
                                fontWeight = FontWeight.Bold,
                                color = MaterialTheme.colorScheme.primary,
                            )
                        }
                    }

                    // Terms note
                    Text(
                        text = stringResource(R.string.auth_terms_note),
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        textAlign = TextAlign.Center,
                        modifier = Modifier.fillMaxWidth().padding(top = Spacing.sm),
                    )
                }
            }
        }
    }

    // Forgot password dialog
    if (state.showForgotPassword) {
        AlertDialog(
            onDismissRequest = viewModel::dismissForgotPassword,
            title = { Text(stringResource(R.string.auth_reset_title)) },
            text = {
                Column {
                    Text(stringResource(R.string.auth_reset_body))
                    Spacer(Modifier.height(Spacing.md))
                    OutlinedTextField(
                        value = state.email,
                        onValueChange = viewModel::onEmailChange,
                        label = { Text(stringResource(R.string.auth_email)) },
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email),
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
            },
            confirmButton = {
                Button(onClick = viewModel::sendPasswordReset, enabled = !state.loading) {
                    Text(stringResource(R.string.auth_send_reset))
                }
            },
            dismissButton = {
                TextButton(onClick = viewModel::dismissForgotPassword) {
                    Text(stringResource(R.string.action_cancel))
                }
            },
        )
    }
}

@Composable
private fun ModeTab(
    text: String,
    selected: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Surface(
        onClick = onClick,
        shape = RoundedCornerShape(Radii.chip),
        color = if (selected) MaterialTheme.colorScheme.primary else androidx.compose.ui.graphics.Color.Transparent,
        modifier = modifier,
    ) {
        Text(
            text = text,
            style = MaterialTheme.typography.labelLarge,
            fontWeight = if (selected) FontWeight.Bold else FontWeight.Normal,
            color = if (selected) {
                MaterialTheme.colorScheme.onPrimary
            } else {
                MaterialTheme.colorScheme.onSurfaceVariant
            },
            modifier = Modifier.padding(vertical = 12.dp),
            textAlign = TextAlign.Center,
            maxLines = 1,
        )
    }
}
