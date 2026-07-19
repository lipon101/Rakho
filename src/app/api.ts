const BASE = "https://rakho-api.onrender.com/api/v1";

export type ApiStatus = "disconnected" | "syncing" | "connected" | "error";

type ListResponse<T> = { count: number; results: T[] };
type PurchaseResponse = { message: string; batches: ApiBatch[] };
type WastageResponse = { message: string; batch: ApiBatch };

function headers(key: string) {
  return { "Content-Type": "application/json", "X-Pharmacy-Key": key };
}

async function req<T>(method: string, path: string, key: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: headers(key),
    body: body != null ? JSON.stringify(body) : undefined,
    credentials: "omit",
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

function unwrapList<T>(payload: ListResponse<T> | T[]): T[] {
  return Array.isArray(payload) ? payload : payload.results;
}

// ---- Types ----------------------------------------------------------------

export interface ApiMedicine {
  id: string;
  brand_name: string;
  generic_name: string;
  strength: string;
  dosage_form: string;
  manufacturer_name: string;
  default_selling_price: string;
  low_stock_threshold: number;
  available_quantity: number;
  catalog_medicine: number | null;
  is_active: boolean;
}

export interface ApiBatch {
  id: string;
  medicine: string;
  medicine_name: string;
  medicine_strength: string;
  batch_number: string;
  expiry_date: string;
  unit_cost: string;
  selling_price: string;
  quantity_received: number;
  quantity_available: number;
}

export interface ApiSale {
  id: string;
  invoice_number: string;
  sold_at: string;
  total_amount: string;
  payment_method: string;
  lines: Array<{
    medicine: string;
    medicine_name: string;
    quantity: number;
    unit_price: string;
    line_total: string;
  }>;
}

export interface ApiDashboard {
  currency: string;
  stock_units: number;
  stock_value_bdt: number | string;
  sales_today_bdt: number | string;
  sales_count_today: number;
  expired_batches: number;
  expiring_soon_batches: number;
}

export interface ApiAlerts {
  expired: ApiBatch[];
  expiring: ApiBatch[];
  low_stock: ApiMedicine[];
}

export interface CatalogMedicine {
  id: number;
  brand_name: string;
  generic_name: string;
  strength: string;
  dosage_form: string;
  manufacturer_name: string;
}

interface LiveDashboard {
  pharmacy: { currency: string };
  inventory: { total_units: number; total_value_bdt: number | string };
  sales: { today_amount_bdt: number | string; today_count: number };
  alerts: { expired_batches: number; expiring_soon: number };
}

interface ApiAlertsResponse {
  expired: ApiBatch[];
  expiring?: ApiBatch[];
  expiring_soon?: ApiBatch[];
  low_stock: ApiMedicine[];
}

function normalizeDashboard(payload: ApiDashboard | LiveDashboard): ApiDashboard {
  if ("currency" in payload) return payload;
  return {
    currency: payload.pharmacy.currency,
    stock_units: payload.inventory.total_units,
    stock_value_bdt: payload.inventory.total_value_bdt,
    sales_today_bdt: payload.sales.today_amount_bdt,
    sales_count_today: payload.sales.today_count,
    expired_batches: payload.alerts.expired_batches,
    expiring_soon_batches: payload.alerts.expiring_soon,
  };
}

// ---- Endpoints ------------------------------------------------------------
// These match the independently deployed Rakho API at /api/v1/inventory/.

export const api = {
  health: () => fetch(`${BASE}/health/`, { credentials: "omit" }).then(async response => {
    if (!response.ok) throw new Error(`Health check failed: ${response.status}`);
    return response.json();
  }),

  medicines: {
    list: async (key: string) =>
      unwrapList(await req<ListResponse<ApiMedicine> | ApiMedicine[]>("GET", "/inventory/medicines/", key)),
    create: (key: string, body: {
      brand_name: string; generic_name: string; strength: string;
      dosage_form: string; default_selling_price: string;
      low_stock_threshold: number; catalog_medicine?: number | null;
    }) => req<ApiMedicine>("POST", "/inventory/medicines/", key, body),
  },

  batches: {
    list: async (key: string, activeOnly = true) =>
      unwrapList(await req<ListResponse<ApiBatch> | ApiBatch[]>("GET", `/inventory/batches/${activeOnly ? "?active=true" : ""}`, key)),
  },

  purchases: {
    receive: async (key: string, items: Array<{
      medicine: string; batch_number: string; expiry_date: string;
      quantity: number; unit_cost: string; selling_price: string;
      supplier_name?: string; notes?: string;
    }>) => {
      const payload = await req<PurchaseResponse | ApiBatch[]>("POST", "/inventory/purchases/", key, { items });
      return Array.isArray(payload) ? payload : payload.batches;
    },
  },

  sales: {
    list: async (key: string) =>
      unwrapList(await req<ListResponse<ApiSale> | ApiSale[]>("GET", "/inventory/sales/", key)),
    create: (key: string, body: {
      invoice_number: string; payment_method: string; note?: string;
      lines: Array<{ medicine: string; quantity: number; unit_price: string }>;
    }) => req<ApiSale>("POST", "/inventory/sales/", key, body),
  },

  wastage: {
    mark: async (key: string, batchId: string, note = "") => {
      const payload = await req<WastageResponse | ApiBatch>("POST", `/inventory/batches/${batchId}/write-off/`, key, { note });
      return "batch" in payload ? payload.batch : payload;
    },
  },

  alerts: async (key: string, days = 90) => {
    const payload = await req<ApiAlertsResponse>("GET", `/inventory/alerts/?days=${days}`, key);
    return { expired: payload.expired, expiring: payload.expiring ?? payload.expiring_soon ?? [], low_stock: payload.low_stock };
  },

  dashboard: async (key: string) => normalizeDashboard(
    await req<ApiDashboard | LiveDashboard>("GET", "/inventory/dashboard/", key),
  ),

  catalog: {
    search: async (q: string) => {
      const response = await fetch(`${BASE}/catalog/medicines/?q=${encodeURIComponent(q)}`, { credentials: "omit" });
      if (!response.ok) throw new Error(`Catalog search failed: ${response.status}`);
      return unwrapList(await response.json() as ListResponse<CatalogMedicine> | CatalogMedicine[]);
    },
  },
};
