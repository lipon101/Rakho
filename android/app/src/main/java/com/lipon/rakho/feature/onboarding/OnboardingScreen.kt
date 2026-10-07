package com.lipon.rakho.feature.onboarding

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CloudDone
import androidx.compose.material.icons.filled.HealthAndSafety
import androidx.compose.material.icons.filled.Inventory2
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.lipon.rakho.R
import com.lipon.rakho.di.RakhoViewModelFactory
import com.lipon.rakho.ui.theme.Radii
import com.lipon.rakho.ui.theme.Spacing

/**
 * First run: name your pharmacy and start using Rakho immediately — no
 * account, no key, no friction. Connecting a Rakho server key is optional and
 * offered as the natural next step once the shop is running.
 */
@Composable
fun OnboardingScreen(
    onConnected: () -> Unit,
    viewModel: OnboardingViewModel = viewModel(factory = RakhoViewModelFactory),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()

    if (state.finished) {
        onConnected()
    }

    Scaffold { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(Spacing.xl)
                .verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.Center,
        ) {
            Surface(
                shape = RoundedCornerShape(28.dp),
                color = MaterialTheme.colorScheme.primaryContainer,
            ) {
                Icon(
                    imageVector = Icons.Filled.HealthAndSafety,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.onPrimaryContainer,
                    modifier = Modifier.padding(Spacing.lg).size(28.dp),
                )
            }
            Spacer(Modifier.height(Spacing.lg))
            Text(
                text = stringResource(R.string.onboarding_title),
                style = MaterialTheme.typography.headlineMedium,
                fontWeight = FontWeight.Bold,
            )
            Spacer(Modifier.height(Spacing.sm))
            Text(
                text = stringResource(R.string.onboarding_subtitle),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(Spacing.xl))

            OutlinedTextField(
                value = state.shopName,
                onValueChange = viewModel::onShopNameChange,
                label = { Text(stringResource(R.string.onboarding_shop_name)) },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
            )

            if (state.keyMode) {
                Spacer(Modifier.height(Spacing.md))
                OutlinedTextField(
                    value = state.apiKey,
                    onValueChange = viewModel::onApiKeyChange,
                    label = { Text(stringResource(R.string.onboarding_api_key)) },
                    placeholder = { Text(stringResource(R.string.onboarding_api_key_hint)) },
                    singleLine = true,
                    visualTransformation = PasswordVisualTransformation(),
                    modifier = Modifier.fillMaxWidth(),
                    keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
                )
                Spacer(Modifier.height(Spacing.sm))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(
                        imageVector = Icons.Filled.CloudDone,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.size(16.dp),
                    )
                    Spacer(Modifier.width(Spacing.sm))
                    Text(
                        text = stringResource(R.string.onboarding_key_help),
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            } else {
                Spacer(Modifier.height(Spacing.lg))
                BenefitRow(
                    icon = Icons.Filled.Inventory2,
                    text = stringResource(R.string.onboarding_benefit_offline),
                )
                BenefitRow(
                    icon = Icons.Filled.HealthAndSafety,
                    text = stringResource(R.string.onboarding_benefit_expiry),
                )
                BenefitRow(
                    icon = Icons.Filled.CloudDone,
                    text = stringResource(R.string.onboarding_benefit_sync),
                )
            }

            state.error?.let { error ->
                Spacer(Modifier.height(Spacing.md))
                val message = when (error) {
                    OnboardingError.INVALID_KEY -> stringResource(R.string.onboarding_error_key)
                    OnboardingError.NETWORK -> stringResource(R.string.onboarding_error_network)
                    OnboardingError.EMPTY_FIELDS -> stringResource(R.string.error_generic)
                }
                Text(
                    text = message,
                    color = MaterialTheme.colorScheme.error,
                    style = MaterialTheme.typography.bodyMedium,
                )
            }

            Spacer(Modifier.height(Spacing.xl))

            if (state.keyMode) {
                Button(
                    onClick = viewModel::connect,
                    enabled = !state.busy,
                    modifier = Modifier.fillMaxWidth().height(52.dp),
                    shape = RoundedCornerShape(Radii.button),
                ) {
                    if (state.busy) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(20.dp),
                            strokeWidth = 2.dp,
                            color = MaterialTheme.colorScheme.onPrimary,
                        )
                        Spacer(Modifier.width(Spacing.sm))
                        Text(stringResource(R.string.onboarding_working))
                    } else {
                        Text(
                            text = stringResource(R.string.onboarding_connect),
                            fontWeight = FontWeight.Bold,
                        )
                    }
                }
                if (state.error == OnboardingError.NETWORK) {
                    TextButton(onClick = viewModel::startFree) {
                        Text(stringResource(R.string.onboarding_continue_offline))
                    }
                }
                TextButton(onClick = viewModel::closeKeyMode, modifier = Modifier.fillMaxWidth()) {
                    Text(stringResource(R.string.onboarding_back_to_free))
                }
            } else {
                Button(
                    onClick = viewModel::startFree,
                    modifier = Modifier.fillMaxWidth().height(52.dp),
                    shape = RoundedCornerShape(Radii.button),
                    colors = ButtonDefaults.buttonColors(
                        containerColor = MaterialTheme.colorScheme.primary,
                    ),
                ) {
                    Text(
                        text = stringResource(R.string.onboarding_start_free),
                        fontWeight = FontWeight.Bold,
                    )
                }
                Spacer(Modifier.height(Spacing.sm))
                OutlinedButton(
                    onClick = viewModel::openKeyMode,
                    modifier = Modifier.fillMaxWidth().height(52.dp),
                    shape = RoundedCornerShape(Radii.button),
                ) {
                    Text(stringResource(R.string.onboarding_have_key))
                }
                Spacer(Modifier.height(Spacing.md))
                Text(
                    text = stringResource(R.string.onboarding_free_note),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

@Composable
private fun BenefitRow(icon: ImageVector, text: String) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier.padding(vertical = Spacing.xs),
    ) {
        Icon(
            imageVector = icon,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.primary,
            modifier = Modifier.size(18.dp),
        )
        Spacer(Modifier.width(Spacing.md))
        Text(
            text = text,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurface,
        )
    }
}
