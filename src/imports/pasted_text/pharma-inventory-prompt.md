# Pharma Inventory & Expiry Manager — Full Build Prompt

## Context (Read First)

You are building an offline-first Android mobile app for small pharmacy owners in Bangladesh. There are ~150,000 pharmacies in Bangladesh. Every one of them deals with expired stock daily — expired medicine is 100% loss. Current tools like Telekhata only track item-level quantities (no batch-level tracking, no expiry alerting, no FEFO picking). This app fills that gap completely offline, with zero third-party API dependencies.

**Business model:** The app saves a pharmacy ৳3,000+/month in prevented expiry loss at ৳300-500/month subscription. No payment processing needed in v1 — collect manually.

## Technical Stack (MANDATORY)

- **Framework:** React Native with Expo (~52.x or latest stable)
- **Routing:** Expo Router (file-based routing)
- **Database:** expo-sqlite (local SQLite, no cloud)
- **State management:** Zustand
- **Date picker:** @react-native-community/datetimepicker
- **Barcode scanning:** expo-camera + expo-barcode-scanner (phone camera, no external API)
- **PDF export:** expo-print + react-native-html-to-pdf + expo-sharing
- **File system:** expo-file-system
- **No external APIs, no cloud sync, no authentication, no backend.** Everything runs on-device.
- Target Android (API 24+, 2GB RAM minimum — Bangladesh's mid-range phone). iOS is secondary.

## Directory Structure (Exact)

```
app/
├── _layout.tsx                  # Root layout — providers only
├── index.tsx                    # Dashboard
├── medicines/
│   ├── _layout.tsx
│   ├── add.tsx                  # Add new medicine (master data)
│   └── [id].tsx                 # View/edit single medicine
├── purchases/
│   ├── _layout.tsx
│   ├── new.tsx                  # Purchase stock (batch receiving)
│   └── history.tsx              # Past purchase receipts
├── sales/
│   ├── _layout.tsx
│   ├── new.tsx                  # POS billing screen
│   └── history.tsx              # Past sales
├── expiry/
│   └── index.tsx                # Expiry management
├── stock/
│   ├── low.tsx                  # Low stock overview + reorder list generator
│   └── take/
│       ├── index.tsx            # Start stock take
│       └── count.tsx            # Active counting screen
├── reports/
│   └── index.tsx                # Reports (Daily Sales, Expiry Loss, Stock Value)
└── settings.tsx                 # App settings, data export

components/
├── ui/
│   ├── Button.tsx               # Variants: primary, outline, danger, link, small
│   ├── TextInput.tsx            # Label + input + error state
│   ├── NumericInput.tsx         # Number-only input (large variant for stock take)
│   ├── CurrencyInput.tsx        # ৳-prefixed numeric input
│   ├── DateInput.tsx            # Date picker with formatted display
│   ├── Picker.tsx               # Modal-based dropdown selector
│   ├── AutoCompleteInput.tsx    # Text input with local DB suggestion dropdown
│   ├── SearchBar.tsx            # Search input with clear button, autoFocus support
│   ├── IconButton.tsx           # Icon-only touchable
│   ├── Badge.tsx                # Colored label (expired, low stock, etc)
│   └── ProgressBar.tsx          # Progress bar (stock take)
├── layout/
│   ├── FloatingBottomBar.tsx    # Fixed bottom action bar for forms
│   ├── SectionHeader.tsx        # Section divider with title
│   ├── RowField.tsx             # 2-3 column horizontal form layout
│   ├── SummaryCard.tsx          # Today's summary widget (dashboard)
│   └── AlertCard.tsx            # Alert card — variant prop: danger/critical/warning
├── pharmacy/
│   ├── BatchSelector.tsx        # FEFO batch picker for POS screen
│   ├── ExpiryCountdown.tsx      # Colored days-left badge (green/amber/red/darkred)
│   ├── StockBar.tsx             # Visual stock-level bar
│   └── ActionTile.tsx           # Dashboard quick-action tile (icon + label)
└── providers/
    ├── DatabaseProvider.tsx     # expo-sqlite context + initialization
    └── ThemeProvider.tsx        # Theme colors, spacing, typography

services/
├── database/
│   ├── schema.ts                # CREATE TABLE statements (all 9 tables)
│   ├── migrations.ts            # Versioned schema migrations with version tracking
│   ├── medicines.ts             # CRUD for medicines table
│   ├── batches.ts               # CRUD + FEFO queries for batches
│   ├── sales.ts                 # Transactional INSERT sale + sale_items + batch deduction
│   ├── purchases.ts             # Transactional INSERT purchase + purchase_items + create batches
│   ├── stockTake.ts             # Stock take CRUD + discrepancy computation
│   └── reports.ts               # Aggregation queries
├── fefo.ts                      # FEFO algorithm: SELECT batches sorted by expiry ASC, non-empty first
├── expiry.ts                    # Helpers to filter batches by expiry window
└── export.ts                    # PDF report generation using react-native-html-to-pdf
```

## Database Schema (9 Tables, SQLite)

### 1. `medicines` — Master product catalog

```sql
id              INTEGER PRIMARY KEY AUTOINCREMENT
name            TEXT NOT NULL              -- e.g. "Napa Extra"
generic_name    TEXT                       -- e.g. "Paracetamol"
manufacturer    TEXT                       -- Brand/manufacturer name
strength        TEXT                       -- e.g. "500mg"
form            TEXT NOT NULL DEFAULT 'Tablet' -- Tablet/Capsule/Syrup/Injection/Cream/Drops/Inhaler/Other
pack_size       INTEGER NOT NULL           -- e.g. 10 (tablets per strip)
unit_of_sale    TEXT NOT NULL DEFAULT 'Strip' -- Strip/Bottle/Piece/Packet/Box/Vial
purchase_price  REAL                       -- Per unit (may differ by batch)
selling_price   REAL NOT NULL              -- Per unit
min_stock_level INTEGER NOT NULL DEFAULT 10
supplier        TEXT                       -- Default supplier name
barcode         TEXT UNIQUE                -- Optional, for scanner
created_at      TEXT NOT NULL              -- ISO 8601
updated_at      TEXT NOT NULL
is_active       INTEGER NOT NULL DEFAULT 1 -- Soft delete
```

### 2. `batches` — Each receipt/shipment = one batch row

```sql
id              INTEGER PRIMARY KEY AUTOINCREMENT
medicine_id     INTEGER NOT NULL REFERENCES medicines(id)
batch_no        TEXT NOT NULL              -- Printed on box
expiry_date     TEXT NOT NULL              -- YYYY-MM-DD
quantity        INTEGER NOT NULL           -- Total units received
remaining       INTEGER NOT NULL           -- Starts = quantity, decremented per sale
purchase_price  REAL NOT NULL              -- Price paid for THIS batch (may differ from master)
received_date   TEXT NOT NULL              -- Default today
supplier_invoice TEXT                      -- Optional reference
created_at      TEXT NOT NULL
```

### 3. `sales` — Each sale transaction

```sql
id              INTEGER PRIMARY KEY AUTOINCREMENT
customer_name   TEXT                       -- Optional — for credit tracking
total_amount    REAL NOT NULL
total_items     INTEGER NOT NULL           -- Count of distinct line items
sale_date       TEXT NOT NULL              -- Default current timestamp
created_at      TEXT NOT NULL
```

### 4. `sale_items` — Lines within a sale

```sql
id              INTEGER PRIMARY KEY AUTOINCREMENT
sale_id         INTEGER NOT NULL REFERENCES sales(id)
medicine_id     INTEGER NOT NULL REFERENCES medicines(id)
batch_id        INTEGER NOT NULL REFERENCES batches(id)  -- Which batch was picked (FEFO)
quantity        INTEGER NOT NULL
unit_price      REAL NOT NULL               -- Price at time of sale (historical record)
line_total      REAL NOT NULL               -- quantity * unit_price
```

### 5. `purchases` — Purchase receipt header

```sql
id              INTEGER PRIMARY KEY AUTOINCREMENT
supplier_name   TEXT
invoice_no      TEXT
total_amount    REAL NOT NULL
purchase_date   TEXT NOT NULL
created_at      TEXT NOT NULL
```

### 6. `purchase_items` — Lines within a purchase

```sql
id              INTEGER PRIMARY KEY AUTOINCREMENT
purchase_id     INTEGER NOT NULL REFERENCES purchases(id)
medicine_id     INTEGER NOT NULL REFERENCES medicines(id)
batch_no        TEXT NOT NULL
expiry_date     TEXT NOT NULL
quantity        INTEGER NOT NULL
unit_cost       REAL NOT NULL
```

**Note:** Creating a purchase also creates a batch record (the `batches` table). The purchase entry flow auto-creates both in one transaction.

### 7. `stock_takes` — Cycle count sessions

```sql
id              INTEGER PRIMARY KEY AUTOINCREMENT
taken_date      TEXT NOT NULL
status          TEXT NOT NULL DEFAULT 'in_progress'  -- in_progress / completed / cancelled
notes           TEXT
created_at      TEXT NOT NULL
```

### 8. `stock_take_items` — Individual counts

```sql
id              INTEGER PRIMARY KEY AUTOINCREMENT
stock_take_id   INTEGER NOT NULL REFERENCES stock_takes(id)
medicine_id     INTEGER NOT NULL REFERENCES medicines(id)
system_qty      INTEGER NOT NULL           -- What the app thinks
physical_qty    INTEGER NOT NULL           -- What was actually counted
discrepancy     INTEGER NOT NULL           -- physical_qty - system_qty
reason          TEXT                       -- Damage/Theft/Miscount/Expired/Other
```

### 9. Optional: `settings` — App-level settings

```sql
id              INTEGER PRIMARY KEY AUTOINCREMENT
key             TEXT NOT NULL UNIQUE
value           TEXT
```

## Screen Specifications

### Screen 1: Dashboard (index.tsx)

**Purpose:** Daily landing page. Pharmacy owner sees alerts and acts immediately.

**Elements (top to bottom):**
1. Header: Shop name (from settings) + today's date in Bangla format
2. **AlertCard** (variant="danger") — "X medicines expiring this month — ৳Y at risk". Tappable → navigates to /expiry
3. **AlertCard** (variant="critical") — "X expired (৳Y loss). Mark as wastage?" Tappable → /expiry
4. **AlertCard** (variant="warning") — "X items below minimum stock". Tappable → /stock/low
5. **SummaryCard** — "Today: X items sold, ৳Y revenue, Z purchases received"
6. **QuickActions grid** — 4 ActionTile components in a 2×2 grid:
   - "New Sale" (cart icon) → /sales/new
   - "Add Stock" (truck icon) → /purchases/new
   - "Search" (magnify icon) → /sales/new (focuses search bar)
   - "Stock Take" (clipboard icon) → /stock/take

**Data:** Run 4 queries on mount:
(a) COUNT batches WHERE expiry_date BETWEEN today AND today+30 days AND remaining > 0
(b) SUM remaining * purchase_price for those batches
(c) COUNT batches WHERE expiry_date < today AND remaining > 0
(d) COUNT medicines WHERE total stock < min_stock_level

Cache results for 30 seconds.

### Screen 2: Add Medicine (medicines/add.tsx)

**Purpose:** Create a new master medicine record. Used once per product, then reused for stock-in.

**Form fields:**
- Medicine Name * — AutoCompleteInput that searches existing names in the DB (suggest as user types)
- Generic Name — free text, e.g. "Paracetamol"
- Manufacturer — Picker with saved manufacturers + "Add New" option
- Strength — free text, e.g. "500mg"
- Form * — Picker: Tablet/Capsule/Syrup/Injection/Cream/Drops/Inhaler/Other
- Pack Size * — NumericInput, e.g. 10
- Unit of Sale — Picker: Strip/Bottle/Piece/Packet/Box/Vial (default Strip)
- Purchase Price (৳) — CurrencyInput
- Sell Price (৳) * — CurrencyInput
- Min Stock Level * — NumericInput, default 10
- Default Supplier — optional free text
- Barcode — optional TextInput + barcode scan button

**Validation:** Name is required. Sell Price is required. If barcode is entered, check uniqueness and show error if duplicate.

**On save:** INSERT into `medicines`. Navigate to dashboard (or optionally to purchase/new with this medicine pre-selected).

### Screen 3: Purchase Stock (purchases/new.tsx)

**Purpose:** Record incoming stock from distributor — this is where batch/expiry is captured.

**Sections:**
1. **Supplier Info:** Supplier AutoCompleteInput (from saved suppliers list), Invoice # (optional), Date (default today)
2. **Items Received:** Dynamic list of PurchaseLineItem components:
   - Medicine selector (AutoCompleteInput searching medicines table)
   - Batch/Lot Number * (TextInput)
   - Expiry Date * (DateInput — BIG clear display. If < 6 months away, show inline warning: "Expires in X months — confirm?")
   - Quantity Received * (NumericInput)
   - Unit Cost (CurrencyInput, pre-filled from master purchase_price but editable)
   - Remove button (IconButton close)
   - "+ Add Another Item" link
3. **Summary:** Items count, Total Cost
4. **Bottom bar:** Cancel (outline) | Save Purchase (primary, disabled until valid)

**On save (transactional):**
1. INSERT into `purchases`
2. For each item: INSERT into `purchase_items`, INSERT into `batches` (remaining = quantity)
3. Show success toast, navigate to purchase history or dashboard

### Screen 4: POS / Sell Stock (sales/new.tsx)

**Purpose:** Fast checkout — used dozens of times daily. Must be SPEEDY.

**Layout:**
1. **Fixed top:** SearchBar (autoFocus when navigated to). Search by name, generic name, OR barcode in real-time from local DB.
2. **Search results:** FlatList below search bar (only visible when query.length > 0). Each row shows: Name + generic + strength, Sell Price, Available stock (sum of all batches' remaining).
   - Tapping a result adds it to the cart with FEFO batch pre-selected
3. **Cart:** Scrollable section below. Each CartRow shows:
   - Medicine name + strength
   - **BatchSelector** — horizontal chips showing available batches for this medicine, sorted FEFO (nearest expiry first). Pre-selected batch highlighted green. Chip shows "Batch {no} — Exp {date} ({remaining} left)".
   - Quantity NumericInput (default 1)
   - Line total (qty * unit_price)
   - Remove button
   - FEFO indicator banner: "Items sorted: soonest-expiry batches first"
4. **Fixed bottom:**
   - Customer name field (optional — for credit sales)
   - Total display (living, updates as cart changes)
   - **SELL button** (primary, disabled when cart empty)

**FEFO BatchSelector sub-component:**
- Receives `medicineId`, returns `{ batchId, quantity }` per cart item
- Sorts available batches (remaining > 0) by expiry_date ASC
- Auto-selects the first (soonest-expiry) batch
- Each chip shows: expiry date + remaining quantity
- Color coding: red if expired, amber if < 90 days, green otherwise
- Allow manual override by tapping a different chip

**On save (transactional):**
1. INSERT into `sales`
2. For each cart item: INSERT into `sale_items`, UPDATE `batches` SET remaining = remaining - quantity
3. If a batch's remaining hits 0, it's automatically depleted (no separate delete needed)
4. If post-sale remaining < min_stock_level, the dashboard will pick it up on next render
5. Clear cart, show success toast, stay on screen for next sale

**Edge cases:**
- If remaining stock < requested quantity, show alert and clamp qty to remaining
- If batch just ran out mid-cart (from a concurrent sale — not applicable offline, but guard anyway), show "Batch depleted" and suggest next FEFO batch
- Allow 0 qty items to exist in cart? No — remove them automatically
- If ALL stock is expired batches and user tries to sell, warn: "All batches of [medicine] are expired. Sell anyway?"

### Screen 5: Expiry Management (expiry/index.tsx)

**Purpose:** Dedicated screen for managing expiry risk. The "save money" screen.

**Top (sticky):** 3 stat cards in a row:
- "Expiring This Month" — count, red background
- "Expired" — count, dark red background
- "At Risk (৳)" — total purchase value of expiring stock, orange background

**Filter tabs** (horizontal scrollable pills): This Month | Next 3 Months | Already Expired | All

**List:** Each row shows:
- Medicine name + strength (bold)
- Batch number + quantity remaining (muted)
- ExpiryCountdown badge (green/amber/red/darkred with "X days left" or "Expired Xd ago")
- Purchase value (remaining × purchase_price)
- Two action buttons: "Wastage" (danger, small) | "Bulk Sale" (info, small)

**Wastage action:** Sets batch.remaining = 0 and logs a stock_take_items entry with reason='expired'. Removes the batch from active inventory. Updates dashboard.

**Bulk Sale action:** Marks the batch as sold-at-discount (alternative flow) — reduce remaining to 0, record it differently in the sales log.

### Screen 6: Low Stock (stock/low.tsx)

**Purpose:** Know what to reorder.

**Header banner:** "X items need reordering" + "Generate Reorder List" button

**List:** Each row shows:
- Medicine name + strength + form
- **StockBar component** — horizontal bar showing current stock vs minimum. Red if below min, amber if < 2× min, green otherwise. Percentage bar width.
- Numeric label: "{stock} / min {minLevel}"
- "Order: {shortfall} more" (shortfall = minLevel - stock, only if stock < minLevel)

**Generate Reorder List:** Button press creates a text list and a PDF:
```
Reorder List — [Shop Name]
[Date]

• Napa Extra 500mg — order 15 strips
• Fexo 120mg — order 10 strips
• ...
```
Opens a modal with the preview. User can share via WhatsApp (Share.share with message text) or save PDF (printPdf + expo-sharing).

### Screen 7: Stock Take (stock/take/index.tsx → count.tsx)

**Purpose:** Monthly/quarterly cycle count. Catch theft, counting errors, wastage.

**Start screen:**
- "Start New Count" button
- "Previous counts" list (date + status + discrepancy count)

**Count screen (count.tsx):**
- Progress header: "12 / 48 items counted" + ProgressBar
- CountCard shows one medicine at a time:
  - Medicine name + strength (large, bold)
  - "Current system stock: X"
  - NumericInput for physical count (large font, autoFocus)
  - If physical count ≠ system stock, show discrepancy banner with reason Picker (Damage/Theft/Miscount/Expired/Other) + TextInput for details
- Bottom bar: "Skip" (outline) | "Confirm & Next" (primary)
- After last item, show completion screen with summary (total discrepancies, total value difference)

**Auto-adjust logic:** On stock take completion, for each item with a discrepancy, UPDATE `batches` adjusting remaining (proportional across batches by current remaining ratio) to match the physical count. Log reason.

### Screen 8: Reports (reports/index.tsx)

**Purpose:** Business intelligence without the internet.

**Three tabs (bottom tabs or segmented control):**
1. **Daily Sales:** Date range selector (default today). Shows total revenue, items sold, margin (total sales - total cost of goods sold calculated from batch purchase prices at time of sale). Optional small bar chart.
2. **Expiry Report:** "You lost ৳X to expiry this [month/quarter]". Export button.
3. **Stock Value:** Total purchase value of current stock (SUM of batches.remaining * batches.purchase_price). Trend indicator (up/down from last calculation).

All reports have an "Export PDF" button.

## FEFO Algorithm (Critical — Implement Exactly)

**Purpose:** Every time a sale is made, the app MUST default to picking the batch that expires soonest. This is the core value proposition — without it, the app is just a list.

```sql
SELECT b.* FROM batches b
WHERE b.medicine_id = ?
  AND b.remaining > 0
  AND b.expiry_date >= date('now')
ORDER BY b.expiry_date ASC, b.received_date ASC
```

**In the BatchSelector component:**
- Sort batches by expiry_date ASC (soonest first)
- Pre-select the first batch in the sorted list (highlight it green)
- Show a small "FEFO" label on the pre-selected batch so the pharmacist knows the system chose it
- Allow manual override by tapping a different batch

**On the Sell screen, in the cart row:**
- Show which batch is selected for each line item
- If user tries to select a batch that's expired (expiry_date < today), show "This batch is expired — are you sure?" confirmation

## UI/UX Requirements

1. **Bangladesh-specific design:**
   - Support for Bangla language in UI (use i18n with bangla.json locale file from day one — even if v1 ships in English, the architecture must support switching)
   - Large text (16px minimum — small screens, aging pharmacy owners)
   - Large touch targets (minimum 48×48dp, prefer 56×56dp)
   - High contrast (avoid light grey on white — use real contrast)
   - BDT currency format everywhere (৳1,234.50 or just ৳1,235)

2. **Offline-first:**
   - Zero features require internet
   - All queries hit SQLite directly
   - No loading spinners for data — sync queries are instant on SQLite
   - The app must work on a phone that has never seen the internet (after Play Store install)

3. **Performance:**
   - Target 60fps on 2GB RAM Android devices
   - All DB queries run synchronously or with minimal async overhead
   - Search should return results within 200ms for a 1,000-medicine database
   - Use SQLite FTS5 (Full Text Search) for medicine search if performance degrades
   - Optimize for slow eMMC storage (common at this price point) — avoid frequent large writes

4. **No login, no auth:**
   - App opens to dashboard directly
   - If multi-user needed later, add a 4-digit PIN lock — not in v1

## Error Handling & Edge Cases

1. **Zero stock:** Dashboard should still work. Show "No medicines yet — add your first medicine" CTA.
2. **Empty cart:** SELL button disabled. Show "Search and tap items to add to cart" placeholder.
3. **Expired batch selected:** Warn user before allowing sale of expired stock.
4. **Batch runs out mid-flow:** Deduct, check remaining, show toast "Batch X now empty."
5. **Duplicate barcode:** Show error on save, do not allow.
6. **Negative quantities:** Clamp NumericInput to min 0. Reject 0 on save.
7. **Large datasets:** Test with 5,000 medicines and 15,000 batches. Search must remain under 500ms.
8. **Backup:** Settings screen includes "Export Database" that copies the SQLite file to shared storage/Documents, and "Import Database" from file picker. Use expo-file-system + expo-sharing.
9. **App update:** migrations.ts handles schema changes incrementally (version number in settings table, run migrations sequentially).

## Build Order (Do NOT Skip)

Build in this exact order — each step produces a testable, working app:

**Week 1:**
- Day 1-2: Project init, Expo Router structure, SQLite schema creation + migrations, DatabaseProvider context, Zustand store setup
- Day 3-4: Shared UI components (Button, TextInput, NumericInput, CurrencyInput, DateInput, Picker, AutoCompleteInput, SearchBar, Badge, Modal, AlertCard, SectionHeader, FloatingBottomBar, RowField)
- Day 5-7: Medicines CRUD (schema + services + Add Medicine screen) + Dashboard (with real aggregate queries)

**Week 2:**
- Day 8-10: Purchases CRUD (purchase + batch creation in one transaction, Purchase screen, batch display in dashboard)
- Day 11-14: Sales/POS (cart, FEFO BatchSelector, sale + sale_items + batch deduction transaction, Sell screen)

**Week 3:**
- Day 15-16: Expiry Management screen (filtering, wastage/bulk-sale actions, ExpiryCountdown component)
- Day 17-18: Low Stock screen + StockBar + Reorder List generation (text + PDF)
- Day 19-20: Stock Take workflow
- Day 21: Reports screen (3 tabs, PDF export)

**Week 4:**
- Day 22-23: Settings (shop name, data export/import, language toggle if applicable)
- Day 24-25: Barcode scanning integration
- Day 26-27: Polish — loading states, empty states, error states, edge cases
- Day 28: Performance testing at 5,000+ medicines, 15,000+ batches. FTS5 search if needed.

## What to Skip in v1

- Cloud sync / backup
- User authentication / multi-device
- GST/VAT tax calculation
- Supplier management (free-text supplier name is enough)
- Customer management beyond optional name field
- Payment integration (bKash, cards)
- Analytics graphs/charts beyond bar chart on daily sales
- Push notifications
- Bangla language localization (architect for it, don't build it — unless you ship both from day one)
- Dark mode
- Animations beyond standard React Native transitions
- Automated tests beyond manual QA — ship fast, fix post-launch

## Quality Bar

- Every screen must render without crashing on first load
- All CRUD operations must succeed and persist after app close/reopen
- All transactional writes (sale, purchase) must be atomic — partial writes are NOT acceptable
- Search must feel instant (< 200ms for 1,000 items)
- Zero console.log statements in production code
- Expo build (APK) must pass `eas build --platform android` without warnings
- App must handle the back button correctly (Expo Router handles this, but test it)

## Final Instruction

Build each week's scope before showing anything to me. Do NOT stop mid-week to ask questions — the spec above answers every likely question. If something genuinely ambiguous, make the most pragmatic decision for an offline-first Bangladesh pharmacy app and note it in a comment.
