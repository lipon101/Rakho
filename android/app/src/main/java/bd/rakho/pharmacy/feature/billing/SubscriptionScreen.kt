package bd.rakho.pharmacy.feature.billing

import android.app.Activity
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
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Star
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import bd.rakho.pharmacy.R
import bd.rakho.pharmacy.core.time.DhakaTime
import bd.rakho.pharmacy.di.RakhoViewModelFactory
import bd.rakho.pharmacy.ui.components.SectionHeader
import bd.rakho.pharmacy.ui.theme.Radii
import bd.rakho.pharmacy.ui.theme.Spacing

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SubscriptionScreen(
    onBack: () -> Unit,
    viewModel: SubscriptionViewModel = viewModel(factory = RakhoViewModelFactory),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val snackbar = remember { SnackbarHostState() }
    // Resolved here: stringResource is only callable from a composable scope.
    val features = featureStrings()

    val unavailable = stringResource(R.string.sub_unavailable)
    val verifying = stringResource(R.string.sub_verified_pending)
    val activated = stringResource(R.string.sub_thanks)
    val failed = stringResource(R.string.error_generic)

    LaunchedEffect(state.message) {
        when (state.message) {
            SubscriptionMessage.Unavailable -> snackbar.showSnackbar(unavailable)
            SubscriptionMessage.Verifying -> snackbar.showSnackbar(verifying)
            SubscriptionMessage.Activated -> snackbar.showSnackbar(activated)
            SubscriptionMessage.PurchaseFailed -> snackbar.showSnackbar(failed)
            SubscriptionMessage.NothingToRestore -> snackbar.showSnackbar(unavailable)
            null -> return@LaunchedEffect
        }
    }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            TopAppBar(
                title = { Text(stringResource(R.string.sub_title)) },
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
            item {
                Surface(
                    shape = RoundedCornerShape(Radii.card),
                    color = MaterialTheme.colorScheme.primaryContainer,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Column(modifier = Modifier.padding(Spacing.xl)) {
                        Icon(
                            imageVector = Icons.Filled.Star,
                            contentDescription = null,
                            tint = MaterialTheme.colorScheme.onPrimaryContainer,
                        )
                        Spacer(Modifier.height(Spacing.sm))
                        Text(
                            text = stringResource(R.string.sub_title),
                            style = MaterialTheme.typography.headlineSmall,
                            fontWeight = FontWeight.Bold,
                            color = MaterialTheme.colorScheme.onPrimaryContainer,
                        )
                        Spacer(Modifier.height(Spacing.xs))
                        Text(
                            text = stringResource(R.string.sub_subtitle),
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onPrimaryContainer.copy(alpha = 0.9f),
                        )
                    }
                }
            }

            item { SectionHeader(stringResource(R.string.sub_current_plan)) }
            item {
                Surface(
                    shape = RoundedCornerShape(Radii.card),
                    color = MaterialTheme.colorScheme.surface,
                    tonalElevation = 1.dp,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Column(modifier = Modifier.padding(Spacing.lg)) {
                        Text(
                            text = stringResource(
                                if (state.entitlement.isPro) R.string.sub_plan_pro else R.string.sub_plan_free,
                            ),
                            style = MaterialTheme.typography.titleMedium,
                            fontWeight = FontWeight.Bold,
                        )
                        state.entitlement.validUntil?.let { date ->
                            Text(
                                text = stringResource(R.string.sub_active_until, DhakaTime.format(date)),
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    }
                }
            }

            if (state.loading) {
                item {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.Center,
                    ) {
                        CircularProgressIndicator()
                    }
                }
            }

            state.offers.forEach { offer ->
                item(key = offer.productId) {
                    OfferCard(
                        offer = offer,
                        selected = state.selectedOffer?.productId == offer.productId,
                        onSelect = { viewModel.select(offer.productId) },
                    )
                }
            }

            item { SectionHeader(stringResource(R.string.sub_whats_included)) }
            for (feature in features) {
                item {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(
                            imageVector = Icons.Filled.Check,
                            contentDescription = null,
                            tint = MaterialTheme.colorScheme.primary,
                        )
                        Spacer(Modifier.height(Spacing.xs))
                        Text(
                            text = feature,
                            style = MaterialTheme.typography.bodyMedium,
                            modifier = Modifier.padding(start = Spacing.sm),
                        )
                    }
                }
            }

            item {
                Button(
                    onClick = { context.findActivity()?.let(viewModel::subscribe) },
                    enabled = !state.busy && state.offers.isNotEmpty() && !state.entitlement.isPro,
                    shape = RoundedCornerShape(Radii.button),
                    modifier = Modifier.fillMaxWidth().height(54.dp),
                ) {
                    Text(
                        text = stringResource(
                            if (state.entitlement.isPro) R.string.sub_manage else R.string.sub_subscribe,
                        ),
                        fontWeight = FontWeight.Bold,
                    )
                }
            }

            if (state.entitlement.isPro) {
                item {
                    OutlinedManageRow(
                        onManage = { openSubscriptionManagement(context) },
                    )
                }
            } else {
                item {
                    TextButton(
                        onClick = viewModel::restore,
                        enabled = !state.busy,
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text(stringResource(R.string.sub_restore))
                    }
                }
            }

            item {
                Text(
                    text = stringResource(R.string.sub_disclosure),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

@Composable
private fun OfferCard(offer: SubscriptionOffer, selected: Boolean, onSelect: () -> Unit) {
    Card(
        onClick = onSelect,
        shape = RoundedCornerShape(Radii.card),
        colors = CardDefaults.cardColors(
            containerColor = if (selected) {
                MaterialTheme.colorScheme.primaryContainer
            } else {
                MaterialTheme.colorScheme.surface
            },
        ),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(
            modifier = Modifier.padding(Spacing.lg),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = stringResource(
                        if (offer.isYearly) R.string.sub_yearly else R.string.sub_monthly,
                    ),
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.Bold,
                )
                if (offer.description.isNotBlank()) {
                    Text(
                        text = offer.description,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                Spacer(Modifier.height(Spacing.xs))
                Text(
                    text = stringResource(R.string.sub_start_trial),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Text(
                text = offer.formattedPrice,
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold,
            )
        }
    }
}

@Composable
private fun OutlinedManageRow(onManage: () -> Unit) {
    TextButton(onClick = onManage, modifier = Modifier.fillMaxWidth()) {
        Text(stringResource(R.string.sub_manage))
    }
}

@Composable
private fun featureStrings(): List<String> = listOf(
    stringResource(R.string.sub_feature_devices),
    stringResource(R.string.sub_feature_stock),
    stringResource(R.string.sub_feature_reports),
    stringResource(R.string.sub_feature_alerts),
    stringResource(R.string.sub_feature_support),
)

/**
 * Play's own subscription-management page — the only route a Play-distributed
 * app may offer for changing or cancelling a subscription.
 */
private fun android.content.Context.findActivity(): Activity? {
    var current = this
    while (current is android.content.ContextWrapper) {
        if (current is Activity) return current
        current = current.baseContext
    }
    return null
}

private fun openSubscriptionManagement(context: android.content.Context) {
    val url = "https://play.google.com/store/account/subscriptions" +
        "?package=${context.packageName}"
    runCatching {
        context.startActivity(
            Intent(Intent.ACTION_VIEW, Uri.parse(url)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
        )
    }
}
