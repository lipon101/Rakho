package com.lipon.rakho.feature.pos

import com.lipon.rakho.core.money.Money
import com.lipon.rakho.core.model.Batch
import com.lipon.rakho.core.model.Medicine
import com.lipon.rakho.data.repo.InventoryRepository
import io.mockk.every
import io.mockk.mockk
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestCoroutineScheduler
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.time.LocalDate

/**
 * Cart editing at the counter.
 *
 * These cover the freedom the Sell tab was missing: a line can be corrected in
 * place (stepper, typed quantity, negotiated price) instead of only being
 * thrown away. The regression at the heart of the suite is that the old "−"
 * control called remove() and deleted the whole line on the first tap.
 *
 * The state is `stateIn(WhileSubscribed)`, so a collector must be held open
 * while edits are made and cancelled before the test returns — otherwise
 * runTest reports UncompletedCoroutinesError.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class PosCartEditTest {

    private val scheduler = TestCoroutineScheduler()

    @Before
    fun setUp() {
        Dispatchers.setMain(StandardTestDispatcher(scheduler))
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    private val medicine = Medicine(
        id = "m1",
        brandName = "Napa",
        genericName = "Paracetamol",
        strength = "500 mg",
        defaultSellingPrice = Money.parse("12.00"),
        lowStockThreshold = 5,
    )

    private val batch = Batch(
        id = "b1",
        medicineId = "m1",
        medicineName = "Napa",
        batchNumber = "B1",
        expiryDate = LocalDate.now().plusYears(1),
        unitCost = Money.parse("8.00"),
        sellingPrice = Money.parse("12.00"),
        quantityReceived = 10,
        quantityAvailable = 10,
    )

    private fun newViewModel(): PosViewModel {
        val inventory = mockk<InventoryRepository>()
        every { inventory.observeMedicines() } returns flowOf(listOf(medicine))
        every { inventory.observeBatches() } returns flowOf(listOf(batch))
        // Only checkout() touches these three, and none of these tests check out.
        // The catalogue is unused here (stock has a match), so a relaxed mock.
        return PosViewModel(
            inventory,
            mockk(relaxed = true),
            mockk(relaxed = true),
            mockk(relaxed = true),
            mockk(relaxed = true),
        )
    }

    /**
     * Subscribes to the view model for the duration of [body] so edits are
     * reflected in `state.value`, then tears the subscription down.
     */
    private suspend fun kotlinx.coroutines.test.TestScope.editingCart(
        body: suspend (vm: PosViewModel) -> Unit,
    ) {
        val vm = newViewModel()
        val collector = launch { vm.state.collect { } }
        advanceUntilIdle()
        try {
            body(vm)
        } finally {
            collector.cancel()
            advanceUntilIdle()
        }
    }

    @Test
    fun `stepping down removes one unit and keeps the line`() = runTest(scheduler) {
        editingCart { vm ->
            vm.add("m1")
            vm.add("m1")
            advanceUntilIdle()
            assertEquals(2, vm.state.value.cart.single().quantity)

            // The old control deleted the line here; it must only lose one unit.
            vm.decrement("m1")
            advanceUntilIdle()
            assertEquals(1, vm.state.value.cart.single().quantity)

            vm.decrement("m1")
            advanceUntilIdle()
            assertTrue("line should drop out at zero", vm.state.value.cart.isEmpty())
        }
    }

    @Test
    fun `typed quantity is applied directly`() = runTest(scheduler) {
        editingCart { vm ->
            vm.setQuantity("m1", 4)
            advanceUntilIdle()
            assertEquals(4, vm.state.value.cart.single().quantity)
            assertEquals(4, vm.state.value.itemCount)
        }
    }

    @Test
    fun `typed quantity can never exceed the shelf`() = runTest(scheduler) {
        editingCart { vm ->
            vm.setQuantity("m1", 99)
            advanceUntilIdle()
            assertEquals(10, vm.state.value.cart.single().quantity)
        }
    }

    @Test
    fun `a line can be deleted outright`() = runTest(scheduler) {
        editingCart { vm ->
            vm.add("m1")
            advanceUntilIdle()
            vm.remove("m1")
            advanceUntilIdle()

            assertTrue(vm.state.value.cart.isEmpty())
            assertTrue(vm.state.value.linePrices.isEmpty())
        }
    }

    @Test
    fun `negotiated unit price replaces the catalogue price in totals`() = runTest(scheduler) {
        editingCart { vm ->
            vm.setQuantity("m1", 3)
            vm.onLinePriceChange("m1", "9.50")
            advanceUntilIdle()

            val line = vm.state.value.cart.single()
            assertEquals(Money.parse("9.50"), line.unitPrice)
            assertEquals("9.50", vm.state.value.linePrices["m1"])
            // The receipt and the day's takings must both see the haggled price.
            assertEquals(Money.parse("28.50"), vm.state.value.totals.subtotal)
        }
    }

    @Test
    fun `clearing the price field falls back to the catalogue price`() = runTest(scheduler) {
        editingCart { vm ->
            vm.setQuantity("m1", 1)
            vm.onLinePriceChange("m1", "5.00")
            advanceUntilIdle()
            assertEquals(Money.parse("5.00"), vm.state.value.cart.single().unitPrice)

            vm.onLinePriceChange("m1", "")
            advanceUntilIdle()
            assertEquals(Money.parse("12.00"), vm.state.value.cart.single().unitPrice)
            assertTrue(vm.state.value.linePrices.isEmpty())
        }
    }

    @Test
    fun `price entry keeps only digits and one decimal point`() = runTest(scheduler) {
        editingCart { vm ->
            vm.setQuantity("m1", 1)
            vm.onLinePriceChange("m1", "12a.3b45")
            advanceUntilIdle()
            assertEquals("12.34", vm.state.value.linePrices["m1"])
        }
    }
}
