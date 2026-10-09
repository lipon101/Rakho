package com.lipon.rakho.feature.settings

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Cloud
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.CloudOff
import androidx.compose.material.icons.filled.DarkMode
import androidx.compose.material.icons.filled.DeleteForever
import androidx.compose.material.icons.filled.Description
import androidx.compose.material.icons.filled.Language
import androidx.compose.material.icons.filled.LocalPharmacy
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material.icons.filled.PrivacyTip
import androidx.compose.material.icons.filled.Sync
import androidx.compose.material.icons.filled.VpnKey
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.lipon.rakho.BuildConfig
import com.lipon.rakho.R
import com.lipon.rakho.core.cloud.CloudServices
import com.lipon.rakho.core.time.DhakaTime
import com.lipon.rakho.di.RakhoViewModelFactory
import com.lipon.rakho.ui.components.GroupCard
import com.lipon.rakho.ui.components.GroupDivider
import com.lipon.rakho.ui.components.SectionLabel
import com.lipon.rakho.ui.components.SettingsRow
import com.lipon.rakho.ui.components.StatusPill
import com.lipon.rakho.ui.theme.Radii
import com.lipon.rakho.ui.theme.Sizes
import com.lipon.rakho.ui.theme.Spacing
import java.time.Instant
import java.time.format.DateTimeFormatter

/**
 * Settings, as grouped cards rather than a stack of loose tiles.
 *
 * The rule that shapes this screen: every row is one line. Titles and
 * subtitles ellipsize instead of wrapping, so the whole screen scans top to
 * bottom without the ragged two-line rows the previous version had.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(
    onBack: () -> Unit,
    onSignOut: () -> Unit = {},
    viewModel: SettingsViewModel = viewModel(factory = RakhoViewModelFactory),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val snackbar = remember { SnackbarHostState() }

    var shopName by remember(state.profile.name) { mutableStateOf(state.profile.name) }
    var phone by remember(state.profile.phone) { mutableStateOf(state.profile.phone) }
    var address by remember(state.profile.address) { mutableStateOf(state.profile.address) }
    var confirmDelete by remember { mutableStateOf(false) }
    var showLanguage by remember { mutableStateOf(false) }
    var showTheme by remember { mutableStateOf(false) }

    val savedText = stringResource(R.string.settings_saved)

    LaunchedEffect(state.saved) {
        if (state.saved) snackbar.showSnackbar(savedText)
    }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            TopAppBar(
                title = { Text(stringResource(R.string.settings_title)) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(
                            Icons.Filled.Close,
                            contentDescription = stringResource(R.string.action_back),
                        )
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
            verticalArrangement = Arrangement.spacedBy(Spacing.sm),
        ) {
            item { ProfileHero(state.profile.name, state.profile.phone, state.sync.pendingCount) }

            item { SectionLabel(stringResource(R.string.settings_profile)) }
            item {
                GroupCard {
                    Column(
                        modifier = Modifier.padding(Spacing.lg),
                        verticalArrangement = Arrangement.spacedBy(Spacing.md),
                    ) {
                        OutlinedTextField(
                            value = shopName,
                            onValueChange = { shopName = it },
                            label = { Text(stringResource(R.string.onboarding_shop_name)) },
                            singleLine = true,
                            modifier = Modifier.fillMaxWidth(),
                        )
                        OutlinedTextField(
                            value = phone,
                            onValueChange = { phone = it },
                            label = { Text(stringResource(R.string.settings_phone)) },
                            singleLine = true,
                            modifier = Modifier.fillMaxWidth(),
                        )
                        OutlinedTextField(
                            value = address,
                            onValueChange = { address = it },
                            label = { Text(stringResource(R.string.settings_address)) },
                            singleLine = true,
                            modifier = Modifier.fillMaxWidth(),
                        )
                        Button(
                            onClick = { viewModel.saveProfile(shopName, phone, address) },
                            enabled = !state.saving,
                            shape = RoundedCornerShape(Radii.button),
                            modifier = Modifier.fillMaxWidth().height(Sizes.primaryButtonHeight),
                        ) {
                            Text(
                                text = stringResource(R.string.action_save),
                                fontWeight = FontWeight.Bold,
                            )
                        }
                    }
                }
            }

            item { SectionLabel(stringResource(R.string.settings_preferences)) }
            item {
                GroupCard {
                    SettingsRow(
                        title = stringResource(R.string.settings_language),
                        subtitle = languageLabel(state.session.languageCode),
                        icon = Icons.Filled.Language,
                        onClick = { showLanguage = true },
                    )
                    GroupDivider()
                    SettingsRow(
                        title = stringResource(R.string.settings_appearance),
                        subtitle = themeLabel(state.session.themeMode),
                        icon = Icons.Filled.DarkMode,
                        onClick = { showTheme = true },
                    )
                    GroupDivider()
                    SettingsRow(
                        title = stringResource(R.string.settings_notifications),
                        icon = Icons.Filled.Notifications,
                        trailing = {
                            Switch(
                                checked = state.session.notificationsEnabled,
                                onCheckedChange = { viewModel.setNotifications(context, it) },
                            )
                        },
                    )
                }
            }

            // Sync is always on in the Firebase-only build: listeners are
            // live, writes self-replay, so this section reports state only.
            item { SectionLabel(stringResource(R.string.settings_sync)) }
            item {
                GroupCard {
                    SettingsRow(
                        title = stringResource(R.string.settings_sync),
                        subtitle = syncSummary(state.sync.lastSyncAtMillis),
                        icon = Icons.Filled.Sync,
                        trailing = {
                            TextButton(onClick = viewModel::syncNow) {
                                Text(stringResource(R.string.settings_sync_now))
                            }
                        },
                    )
                    if (state.sync.pendingCount > 0) {
                        GroupDivider()
                        SettingsRow(
                            title = stringResource(R.string.settings_pending_ops_title),
                            subtitle = stringResource(
                                R.string.settings_pending_ops,
                                state.sync.pendingCount,
                            ),
                            icon = Icons.Filled.CloudOff,
                        )
                    }
                }
            }

            item { SectionLabel(stringResource(R.string.settings_account)) }
            item {
                GroupCard {
                    SettingsRow(
                        title = stringResource(R.string.settings_signed_in_account),
                        subtitle = state.accountEmail.ifBlank { "—" },
                        icon = Icons.Filled.VpnKey,
                    )
                    GroupDivider()
                    SettingsRow(
                        title = stringResource(R.string.settings_sign_out),
                        subtitle = stringResource(R.string.settings_sign_out_sub),
                        icon = Icons.Filled.CloudOff,
                        onClick = { viewModel.signOut(onSignOut) },
                    )
                }
            }

            item { SectionLabel(stringResource(R.string.settings_support)) }
            item {
                GroupCard {
                    SettingsRow(
                        title = stringResource(R.string.settings_cloud_title),
                        subtitle = stringResource(
                            if (CloudServices.isActive) {
                                R.string.settings_cloud_active
                            } else {
                                R.string.settings_cloud_off
                            },
                        ),
                        icon = Icons.Filled.Cloud,
                    )
                    GroupDivider()
                    SettingsRow(
                        title = stringResource(R.string.settings_privacy),
                        icon = Icons.Filled.PrivacyTip,
                        onClick = { openUrl(context, PRIVACY_URL) },
                    )
                    GroupDivider()
                    SettingsRow(
                        title = stringResource(R.string.settings_terms),
                        icon = Icons.Filled.Description,
                        onClick = { openUrl(context, TERMS_URL) },
                    )
                }
            }

            item { SectionLabel(stringResource(R.string.settings_data_header)) }
            item {
                GroupCard {
                    SettingsRow(
                        title = stringResource(R.string.settings_delete_account),
                        subtitle = stringResource(R.string.settings_delete_brief),
                        icon = Icons.Filled.DeleteForever,
                        onClick = { confirmDelete = true },
                    )
                }
            }

            item {
                Text(
                    text = stringResource(R.string.settings_version, displayVersion),
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    textAlign = androidx.compose.ui.text.style.TextAlign.Center,
                    maxLines = 1,
                    modifier = Modifier.fillMaxWidth().padding(top = Spacing.md),
                )
            }
        }
    }

    if (showLanguage) {
        AlertDialog(
            onDismissRequest = { showLanguage = false },
            title = { Text(stringResource(R.string.settings_language)) },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(Spacing.xs)) {
                    LanguageOption(
                        label = stringResource(R.string.language_system),
                        selected = state.session.languageCode.isBlank(),
                    ) {
                        viewModel.setLanguage(context, "")
                        showLanguage = false
                    }
                    LanguageOption(label = "বাংলা", selected = state.session.languageCode == "bn") {
                        viewModel.setLanguage(context, "bn")
                        showLanguage = false
                    }
                    LanguageOption(label = "English", selected = state.session.languageCode == "en") {
                        viewModel.setLanguage(context, "en")
                        showLanguage = false
                    }
                }
            },
            confirmButton = {
                TextButton(onClick = { showLanguage = false }) {
                    Text(stringResource(R.string.action_ok))
                }
            },
        )
    }

    if (showTheme) {
        AlertDialog(
            onDismissRequest = { showTheme = false },
            title = { Text(stringResource(R.string.settings_appearance)) },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(Spacing.xs)) {
                    LanguageOption(
                        label = stringResource(R.string.theme_system),
                        selected = state.session.themeMode == "system",
                    ) {
                        viewModel.setThemeMode("system")
                        showTheme = false
                    }
                    LanguageOption(
                        label = stringResource(R.string.theme_light),
                        selected = state.session.themeMode == "light",
                    ) {
                        viewModel.setThemeMode("light")
                        showTheme = false
                    }
                    LanguageOption(
                        label = stringResource(R.string.theme_dark),
                        selected = state.session.themeMode == "dark",
                    ) {
                        viewModel.setThemeMode("dark")
                        showTheme = false
                    }
                }
            },
            confirmButton = {
                TextButton(onClick = { showTheme = false }) {
                    Text(stringResource(R.string.action_ok))
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
                        // Everything this pharmacy owns is deleted on the spot —
                        // no email round-trip, no waiting.
                        viewModel.deleteAccountAndData(onSignOut)
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

/** One language choice; the tick is the selection, never colour alone. */
@Composable
private fun LanguageOption(label: String, selected: Boolean, onClick: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(vertical = Spacing.sm),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.bodyLarge,
            fontWeight = if (selected) FontWeight.Bold else FontWeight.Normal,
            modifier = Modifier.weight(1f),
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        if (selected) {
            Icon(
                imageVector = Icons.Filled.Check,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.primary,
            )
        }
    }
}

@Composable
private fun languageLabel(code: String): String = when (code) {
    "bn" -> "বাংলা"
    "en" -> "English"
    else -> stringResource(R.string.language_system)
}

@Composable
private fun themeLabel(mode: String): String = when (mode) {
    "light" -> stringResource(R.string.theme_light)
    "dark" -> stringResource(R.string.theme_dark)
    else -> stringResource(R.string.theme_system)
}

/** Identity card: who this device belongs to and whether writes are landing. */
@Composable
private fun ProfileHero(name: String, phone: String, pendingWrites: Int) {
    Surface(
        shape = RoundedCornerShape(Radii.card),
        color = MaterialTheme.colorScheme.primaryContainer,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(
            modifier = Modifier.padding(Spacing.lg),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(
                modifier = Modifier
                    .size(48.dp)
                    .clip(RoundedCornerShape(Radii.badge))
                    .background(MaterialTheme.colorScheme.primary),
                contentAlignment = Alignment.Center,
            ) {
                // The pharmacy mark rather than the shop's first letter —
                // consistent for every shop name and it reads instantly.
                Icon(
                    imageVector = Icons.Filled.LocalPharmacy,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.onPrimary,
                    modifier = Modifier.size(26.dp),
                )
            }
            Spacer(Modifier.width(Spacing.md))
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = name.ifBlank { stringResource(R.string.auto_shop_name) },
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold,
                    color = MaterialTheme.colorScheme.onPrimaryContainer,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                if (phone.isNotBlank()) {
                    Text(
                        text = phone,
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onPrimaryContainer,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }
            StatusPill(
                text = stringResource(
                    if (pendingWrites == 0) R.string.settings_synced else R.string.settings_pending_ops_title,
                ),
                containerColor = MaterialTheme.colorScheme.surface,
                contentColor = MaterialTheme.colorScheme.primary,
            )
        }
    }
}

@Composable
private fun syncSummary(lastSyncAtMillis: Long): String {
    if (lastSyncAtMillis == 0L) return stringResource(R.string.dashboard_never_synced)
    val stamp = Instant.ofEpochMilli(lastSyncAtMillis)
        .atZone(DhakaTime.ZONE)
        .format(DateTimeFormatter.ofPattern("dd MMM, HH:mm"))
    return stringResource(R.string.settings_last_sync, stamp)
}

/**
 * Version without the build-type marker. `1.0.0-debug` is developer noise on
 * a screen the shopkeeper reads, and says nothing they act on.
 */
private val displayVersion: String
    get() = BuildConfig.VERSION_NAME.substringBefore("-")

private fun openUrl(context: android.content.Context, url: String) {
    runCatching {
        context.startActivity(
            Intent(Intent.ACTION_VIEW, Uri.parse(url)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
        )
    }
}

private const val PRIVACY_URL = "https://rakho-api.onrender.com/privacy/"
private const val TERMS_URL = "https://rakho-api.onrender.com/terms/"
