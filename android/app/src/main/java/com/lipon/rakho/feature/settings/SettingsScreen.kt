package com.lipon.rakho.feature.settings

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.lipon.rakho.BuildConfig
import com.lipon.rakho.R
import com.lipon.rakho.core.time.DhakaTime
import com.lipon.rakho.di.RakhoViewModelFactory
import com.lipon.rakho.ui.components.SectionHeader
import com.lipon.rakho.ui.theme.Radii
import com.lipon.rakho.ui.theme.Spacing
import java.time.Instant
import java.time.format.DateTimeFormatter

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(
    onBack: () -> Unit,
    onOpenSubscription: () -> Unit,
    viewModel: SettingsViewModel = viewModel(factory = RakhoViewModelFactory),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val snackbar = remember { SnackbarHostState() }

    var shopName by remember(state.profile.name) { mutableStateOf(state.profile.name) }
    var phone by remember(state.profile.phone) { mutableStateOf(state.profile.phone) }
    var address by remember(state.profile.address) { mutableStateOf(state.profile.address) }
    var serverUrl by remember(state.session.serverBaseUrl) { mutableStateOf(state.session.serverBaseUrl) }
    var apiKeyInput by remember { mutableStateOf("") }
    var confirmDisconnect by remember { mutableStateOf(false) }
    var confirmDelete by remember { mutableStateOf(false) }

    val savedText = stringResource(R.string.settings_saved)

    LaunchedEffect(state.saved) {
        if (state.saved) snackbar.showSnackbar(savedText)
    }

    // After a successful connect the input clears and the screen settles;
    // the pharmacy is now syncing, so the key entry disappears on its own.
    LaunchedEffect(state.connected) {
        if (state.connected) {
            apiKeyInput = ""
            viewModel.consumeConnectResult()
        }
    }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text(stringResource(R.string.settings_title))
                        if (!state.session.isConnected) {
                            Text(
                                text = stringResource(R.string.local_badge),
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.tertiary,
                            )
                        }
                    }
                },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.Filled.Close, contentDescription = stringResource(R.string.action_back))
                    }
                },
            )
        },
    ) { padding ->
        LazyColumn(
            modifier = Modifier.fillMaxSize().padding(padding),
            contentPadding = PaddingValues(
                start = Spacing.lg,
                end = Spacing.lg,
                top = Spacing.sm,
                bottom = Spacing.xxl,
            ),
            verticalArrangement = Arrangement.spacedBy(Spacing.md),
        ) {
            item { SectionHeader(stringResource(R.string.settings_profile)) }

            item {
                OutlinedTextField(
                    value = shopName,
                    onValueChange = { shopName = it },
                    label = { Text(stringResource(R.string.onboarding_shop_name)) },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
            }
            item {
                OutlinedTextField(
                    value = phone,
                    onValueChange = { phone = it },
                    label = { Text(stringResource(R.string.settings_phone)) },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
            }
            item {
                OutlinedTextField(
                    value = address,
                    onValueChange = { address = it },
                    label = { Text(stringResource(R.string.settings_address)) },
                    minLines = 2,
                    modifier = Modifier.fillMaxWidth(),
                )
            }
            item {
                Button(
                    onClick = { viewModel.saveProfile(shopName, phone, address) },
                    enabled = !state.saving,
                    shape = RoundedCornerShape(Radii.button),
                    modifier = Modifier.fillMaxWidth().height(50.dp),
                ) {
                    Text(
                        text = stringResource(R.string.action_save),
                        fontWeight = FontWeight.Bold,
                    )
                }
            }

            item { SectionHeader(stringResource(R.string.settings_language)) }
            item {
                Row(horizontalArrangement = Arrangement.spacedBy(Spacing.sm)) {
                    listOf("" to "System", "bn" to "বাংলা", "en" to "English").forEach { (code, label) ->
                        FilterChip(
                            selected = state.session.languageCode == code,
                            onClick = { viewModel.setLanguage(context, code) },
                            label = { Text(label) },
                        )
                    }
                }
            }

            item { SectionHeader(stringResource(R.string.settings_sync)) }
            item {
                Surface(
                    shape = RoundedCornerShape(Radii.card),
                    color = MaterialTheme.colorScheme.surface,
                    tonalElevation = 1.dp,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Column(modifier = Modifier.padding(Spacing.lg)) {
                        Text(
                            text = syncSummary(state.sync.lastSyncAtMillis),
                            style = MaterialTheme.typography.bodyMedium,
                        )
                        if (state.sync.pendingCount > 0) {
                            Spacer(Modifier.height(Spacing.xs))
                            Text(
                                text = stringResource(
                                    R.string.settings_pending_ops,
                                    state.sync.pendingCount,
                                ),
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                        Spacer(Modifier.height(Spacing.md))
                        OutlinedButton(
                            onClick = viewModel::syncNow,
                            shape = RoundedCornerShape(Radii.button),
                            modifier = Modifier.fillMaxWidth(),
                        ) {
                            Text(stringResource(R.string.settings_sync_now))
                        }
                    }
                }
            }

            item {
                ToggleRow(
                    title = stringResource(R.string.settings_notifications),
                    subtitle = stringResource(R.string.settings_notifications_desc),
                    checked = state.session.notificationsEnabled,
                    onCheckedChange = { viewModel.setNotifications(context, it) },
                )
            }

            if (!state.session.isConnected) {
                item { SectionHeader(stringResource(R.string.connect_title)) }
                item {
                    Surface(
                        shape = RoundedCornerShape(Radii.card),
                        color = MaterialTheme.colorScheme.primaryContainer,
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Column(modifier = Modifier.padding(Spacing.lg)) {
                            Text(
                                text = stringResource(R.string.settings_connect),
                                style = MaterialTheme.typography.titleSmall,
                                fontWeight = FontWeight.Bold,
                                color = MaterialTheme.colorScheme.onPrimaryContainer,
                            )
                            Spacer(Modifier.height(Spacing.xs))
                            Text(
                                text = stringResource(R.string.settings_connect_desc),
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onPrimaryContainer.copy(alpha = 0.9f),
                            )
                            Spacer(Modifier.height(Spacing.md))
                            OutlinedTextField(
                                value = apiKeyInput,
                                onValueChange = { apiKeyInput = it },
                                label = { Text(stringResource(R.string.onboarding_api_key)) },
                                placeholder = { Text(stringResource(R.string.onboarding_api_key_hint)) },
                                singleLine = true,
                                visualTransformation = androidx.compose.ui.text.input.PasswordVisualTransformation(),
                                modifier = Modifier.fillMaxWidth(),
                            )
                            state.connectError?.let { error ->
                                Spacer(Modifier.height(Spacing.xs))
                                Text(
                                    text = when (error) {
                                        ConnectError.REJECTED -> stringResource(R.string.onboarding_error_key)
                                        ConnectError.NETWORK -> stringResource(R.string.onboarding_error_network)
                                        ConnectError.EMPTY_KEY -> stringResource(R.string.error_generic)
                                    },
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.error,
                                )
                            }
                            Spacer(Modifier.height(Spacing.md))
                            Button(
                                onClick = { viewModel.connect(apiKeyInput) },
                                enabled = !state.connecting && apiKeyInput.isNotBlank(),
                                shape = RoundedCornerShape(Radii.button),
                                modifier = Modifier.fillMaxWidth(),
                            ) {
                                Text(
                                    text = stringResource(R.string.onboarding_connect),
                                    fontWeight = FontWeight.Bold,
                                )
                            }
                            Spacer(Modifier.height(Spacing.sm))
                            Text(
                                text = stringResource(R.string.connect_saved_locally),
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onPrimaryContainer.copy(alpha = 0.85f),
                            )
                        }
                    }
                }
                item {
                    Text(
                        text = stringResource(R.string.settings_local_note),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            } else {
                item { SectionHeader(stringResource(R.string.settings_api_key)) }
            item {
                Surface(
                    shape = RoundedCornerShape(Radii.card),
                    color = MaterialTheme.colorScheme.surfaceVariant,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Row(
                        modifier = Modifier.padding(Spacing.lg),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(
                            text = if (state.showApiKey) {
                                state.session.apiKey
                            } else {
                                maskKey(state.session.apiKey)
                            },
                            style = MaterialTheme.typography.bodySmall,
                            modifier = Modifier.weight(1f),
                        )
                        TextButton(onClick = viewModel::toggleApiKeyVisibility) {
                            Text(
                                stringResource(
                                    if (state.showApiKey) R.string.settings_hide else R.string.settings_show,
                                ),
                            )
                        }
                    }
                }
            }

            item { SectionHeader(stringResource(R.string.settings_backup)) }
            item {
                OutlinedTextField(
                    value = serverUrl,
                    onValueChange = { serverUrl = it },
                    label = { Text(stringResource(R.string.settings_server_url)) },
                    supportingText = { Text(stringResource(R.string.settings_server_url_help)) },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
            }
            item {
                OutlinedButton(
                    onClick = { viewModel.setServerUrl(serverUrl) },
                    shape = RoundedCornerShape(Radii.button),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text(stringResource(R.string.settings_server_apply))
                }
            }

            item { SectionHeader(stringResource(R.string.sub_title)) }
            item {
                Surface(
                    shape = RoundedCornerShape(Radii.card),
                    color = MaterialTheme.colorScheme.primaryContainer,
                    onClick = onOpenSubscription,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Column(modifier = Modifier.padding(Spacing.lg)) {
                        Text(
                            text = stringResource(
                                if (state.subscription.isPro) R.string.sub_plan_pro else R.string.sub_plan_free,
                            ),
                            style = MaterialTheme.typography.titleSmall,
                            fontWeight = FontWeight.Bold,
                            color = MaterialTheme.colorScheme.onPrimaryContainer,
                        )
                        state.subscription.validUntil?.let { date ->
                            Text(
                                text = stringResource(R.string.sub_active_until, DhakaTime.format(date)),
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onPrimaryContainer,
                            )
                        }
                        Spacer(Modifier.height(Spacing.sm))
                        Text(
                            text = stringResource(R.string.dashboard_pro_cta),
                            style = MaterialTheme.typography.labelLarge,
                            color = MaterialTheme.colorScheme.onPrimaryContainer,
                        )
                    }
                }
            }
            }

            item { SectionHeader(stringResource(R.string.settings_privacy)) }
            item {
                LinkRow(stringResource(R.string.settings_privacy)) {
                    openUrl(context, PRIVACY_URL)
                }
            }
            item {
                LinkRow(stringResource(R.string.settings_terms)) {
                    openUrl(context, TERMS_URL)
                }
            }

            item { SectionHeader(stringResource(R.string.settings_disconnect)) }
            item {
                OutlinedButton(
                    onClick = { confirmDisconnect = true },
                    shape = RoundedCornerShape(Radii.button),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text(stringResource(R.string.settings_disconnect))
                }
            }
            item {
                TextButton(
                    onClick = { confirmDelete = true },
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text(
                        text = stringResource(R.string.settings_delete_account),
                        color = MaterialTheme.colorScheme.error,
                    )
                }
            }

            item {
                Text(
                    text = stringResource(R.string.settings_version, BuildConfig.VERSION_NAME),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.fillMaxWidth(),
                )
            }
        }
    }

    if (confirmDisconnect) {
        AlertDialog(
            onDismissRequest = { confirmDisconnect = false },
            title = { Text(stringResource(R.string.settings_disconnect)) },
            text = { Text(stringResource(R.string.settings_disconnect_confirm)) },
            confirmButton = {
                TextButton(
                    onClick = {
                        viewModel.disconnect()
                        confirmDisconnect = false
                        onBack()
                    },
                ) {
                    Text(stringResource(R.string.action_confirm))
                }
            },
            dismissButton = {
                TextButton(onClick = { confirmDisconnect = false }) {
                    Text(stringResource(R.string.action_cancel))
                }
            },
        )
    }

    if (confirmDelete) {
        AlertDialog(
            onDismissRequest = { confirmDelete = false },
            title = { Text(stringResource(R.string.settings_delete_account)) },
            text = { Text(stringResource(R.string.settings_delete_confirm)) },
            confirmButton = {
                TextButton(
                    onClick = {
                        confirmDelete = false
                        openUrl(context, deletionRequestUrl(state.profile.name))
                    },
                ) {
                    Text(stringResource(R.string.action_confirm))
                }
            },
            dismissButton = {
                TextButton(onClick = { confirmDelete = false }) {
                    Text(stringResource(R.string.action_cancel))
                }
            },
        )
    }
}

@Composable
private fun ToggleRow(
    title: String,
    subtitle: String,
    checked: Boolean,
    onCheckedChange: (Boolean) -> Unit,
) {
    Surface(
        shape = RoundedCornerShape(Radii.card),
        color = MaterialTheme.colorScheme.surface,
        tonalElevation = 1.dp,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(
            modifier = Modifier.padding(Spacing.lg),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(text = title, style = MaterialTheme.typography.bodyLarge)
                Text(
                    text = subtitle,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Switch(checked = checked, onCheckedChange = onCheckedChange)
        }
    }
}

@Composable
private fun LinkRow(label: String, onClick: () -> Unit) {
    Surface(
        shape = RoundedCornerShape(Radii.card),
        color = MaterialTheme.colorScheme.surface,
        tonalElevation = 1.dp,
        onClick = onClick,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(
            modifier = Modifier.padding(Spacing.lg),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(text = label, style = MaterialTheme.typography.bodyLarge)
        }
    }
}

@Composable
private fun syncSummary(lastSyncAtMillis: Long): String {
    if (lastSyncAtMillis == 0L) return stringResource(R.string.dashboard_never_synced)
    val stamp = Instant.ofEpochMilli(lastSyncAtMillis)
        .atZone(DhakaTime.ZONE)
        .format(DateTimeFormatter.ofPattern("dd MMM yyyy, HH:mm"))
    return stringResource(R.string.settings_last_sync, stamp)
}

private fun maskKey(key: String): String {
    if (key.length <= 8) return "••••••••"
    return key.take(4) + "••••••••••••" + key.takeLast(4)
}

private fun openUrl(context: android.content.Context, url: String) {
    runCatching {
        context.startActivity(
            Intent(Intent.ACTION_VIEW, Uri.parse(url)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
        )
    }
}

private fun deletionRequestUrl(pharmacy: String): String {
    val subject = Uri.encode("Rakho account deletion request — $pharmacy")
    val body = Uri.encode(
        "Please delete my Rakho account and all associated pharmacy data.\n\nPharmacy: $pharmacy",
    )
    return "mailto:$SUPPORT_EMAIL?subject=$subject&body=$body"
}

private const val SUPPORT_EMAIL = "support@rakho.app"
private const val PRIVACY_URL = "https://rakho-api.onrender.com/privacy/"
private const val TERMS_URL = "https://rakho-api.onrender.com/terms/"
