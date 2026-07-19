import React, { useState, useEffect, useMemo, useCallback } from 'react';
import {
  AlertTriangle, AlertCircle, TrendingDown, ShoppingCart,
  Truck, Search, ClipboardList, Home, Package, Settings as SettingsIcon,
  ArrowLeft, Plus, X, Check, FileText, Download, RotateCcw, Building,
  ChevronRight, Clock, Activity, CheckCircle2, Wifi, WifiOff,
  RefreshCw, Key, Database
} from 'lucide-react';
import { format, addDays, isPast, differenceInDays, parseISO, getHours } from 'date-fns';
import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { api, ApiStatus, type ApiMedicine, type ApiBatch, type ApiDashboard, type ApiAlerts } from './api';

// --- LOCAL TYPES ---

interface LocalMedicine {
  id: string | number;
  name: string;
  generic: string;
  strength: string;
  form: string;
  price: number;
  minStock: number;
}

interface LocalBatch {
  id: string | number;
  medId: string | number;
  batchNo: string;
  expiry: string;
  remaining: number;
  price: number;
}

interface LocalSale {
  id: string | number;
  items: Array<{ medId: string | number; name: string; quantity: number; price: number }>;
  date: string;
  total: number;
}

// --- ADAPTER: API → Local store ---

function adaptMedicine(m: ApiMedicine): LocalMedicine {
  return {
    id: m.id,
    name: m.brand_name,
    generic: m.generic_name,
    strength: m.strength,
    form: m.dosage_form,
    price: parseFloat(m.default_selling_price) || 0,
    minStock: m.low_stock_threshold,
  };
}

function adaptBatch(b: ApiBatch): LocalBatch {
  return {
    id: b.id,
    medId: b.medicine,
    batchNo: b.batch_number,
    expiry: b.expiry_date,
    remaining: b.quantity_available,
    price: parseFloat(b.unit_cost) || 0,
  };
}

// --- INITIAL STATE ---

const initialState = {
  settings: {
    shopName: 'Halal Pharmacy',
    currency: '৳',
    language: 'English',
    pharmacyKey: '',
  },
  medicines: [
    { id: 1, name: 'Napa Extra', generic: 'Paracetamol', strength: '500mg', form: 'Tablet', price: 2.0, minStock: 50 },
    { id: 2, name: 'Fexo', generic: 'Fexofenadine', strength: '120mg', form: 'Tablet', price: 8.0, minStock: 20 },
    { id: 3, name: 'Seclo', generic: 'Omeprazole', strength: '20mg', form: 'Capsule', price: 5.0, minStock: 100 },
  ] as LocalMedicine[],
  batches: [
    { id: 1, medId: 1, batchNo: 'B-101', expiry: addDays(new Date(), 15).toISOString(), remaining: 20, price: 1.5 },
    { id: 2, medId: 1, batchNo: 'B-102', expiry: addDays(new Date(), 180).toISOString(), remaining: 500, price: 1.5 },
    { id: 3, medId: 2, batchNo: 'F-404', expiry: addDays(new Date(), -5).toISOString(), remaining: 10, price: 6.0 },
    { id: 4, medId: 3, batchNo: 'S-900', expiry: addDays(new Date(), 45).toISOString(), remaining: 40, price: 4.0 },
  ] as LocalBatch[],
  sales: [] as LocalSale[],
  purchases: [] as unknown[],
  apiStatus: 'disconnected' as ApiStatus,
  apiDashboard: null as ApiDashboard | null,
  apiAlerts: null as ApiAlerts | null,
};

const useStore = create(
  persist(
    (set, get: () => typeof initialState & Record<string, unknown>) => ({
      ...initialState,

      setApiStatus: (apiStatus: ApiStatus) => set({ apiStatus }),

      setApiData: (medicines: LocalMedicine[], batches: LocalBatch[], dashboard: ApiDashboard | null, alerts: ApiAlerts | null) =>
        set({ medicines, batches, apiDashboard: dashboard, apiAlerts: alerts }),

      updateSetting: (key: string, value: string) =>
        set((state: typeof initialState) => ({ settings: { ...state.settings, [key]: value } })),

      addMedicine: (med: LocalMedicine) =>
        set((state: typeof initialState) => ({ medicines: [...state.medicines, { ...med, id: Date.now() }] })),

      addPurchase: (items: Array<{ medId: string | number; batchNo: string; expiry: string; quantity: number; cost: number }>) =>
        set((state: typeof initialState) => {
          const newBatches = items.map(item => ({
            id: Math.random().toString(),
            medId: item.medId,
            batchNo: item.batchNo,
            expiry: item.expiry,
            remaining: item.quantity,
            price: item.cost,
          }));
          return { batches: [...state.batches, ...newBatches] };
        }),

      processSale: (cartItems: Array<{ id: string | number; medId: string | number; name: string; price: number; quantity: number; selectedBatchId: string | number }>) =>
        set((state: typeof initialState) => {
          let updatedBatches = [...state.batches];

          cartItems.forEach(cartItem => {
            let remainingToDeduct = cartItem.quantity;
            const batchIndex = updatedBatches.findIndex(b => b.id === cartItem.selectedBatchId);
            if (batchIndex > -1) {
              const batch = updatedBatches[batchIndex];
              if (batch.remaining >= remainingToDeduct) {
                updatedBatches[batchIndex] = { ...batch, remaining: batch.remaining - remainingToDeduct };
                remainingToDeduct = 0;
              } else {
                remainingToDeduct -= batch.remaining;
                updatedBatches[batchIndex] = { ...batch, remaining: 0 };
              }
            }
            if (remainingToDeduct > 0) {
              const otherBatches = updatedBatches
                .filter(b => b.medId === cartItem.medId && b.remaining > 0)
                .sort((a, b) => new Date(a.expiry).getTime() - new Date(b.expiry).getTime());
              for (const ob of otherBatches) {
                if (remainingToDeduct === 0) break;
                const idx = updatedBatches.findIndex(b => b.id === ob.id);
                if (ob.remaining >= remainingToDeduct) {
                  updatedBatches[idx] = { ...ob, remaining: ob.remaining - remainingToDeduct };
                  remainingToDeduct = 0;
                } else {
                  remainingToDeduct -= ob.remaining;
                  updatedBatches[idx] = { ...ob, remaining: 0 };
                }
              }
            }
          });

          return {
            batches: updatedBatches,
            sales: [...state.sales, {
              id: Date.now(),
              items: cartItems,
              date: new Date().toISOString(),
              total: cartItems.reduce((acc, item) => acc + item.price * item.quantity, 0),
            }],
          };
        }),

      markWastage: (batchId: string | number) =>
        set((state: typeof initialState) => ({
          batches: state.batches.map(b => b.id === batchId ? { ...b, remaining: 0 } : b),
        })),

      resetDatabase: () => set(initialState),
    }),
    { name: 'pharma-db-premium' }
  )
);

// --- API SYNC HOOK ---

function useApiSync() {
  const { settings, setApiStatus, setApiData } = useStore();
  const key = settings.pharmacyKey;

  const sync = useCallback(async () => {
    if (!key) return;
    setApiStatus('syncing');
    try {
      const [medicines, batches, dashboard, alerts] = await Promise.all([
        api.medicines.list(key),
        api.batches.list(key, true),
        api.dashboard(key),
        api.alerts(key, 90),
      ]);
      setApiData(medicines.map(adaptMedicine), batches.map(adaptBatch), dashboard, alerts);
      setApiStatus('connected');
    } catch {
      setApiStatus('error');
    }
  }, [key]);

  useEffect(() => {
    sync();
  }, [sync]);

  return { sync };
}

// --- SHARED UI COMPONENTS ---

function StatusDot({ status }: { status: ApiStatus }) {
  if (status === 'disconnected') return null;
  const map = {
    syncing: 'bg-amber-400 animate-pulse',
    connected: 'bg-emerald-400',
    error: 'bg-rose-500',
  };
  return <span className={`inline-block w-2 h-2 rounded-full ${map[status]}`} />;
}

function AlertCard({ variant, title, subtitle, onClick }: { variant: string; title: string; subtitle?: string; onClick?: () => void }) {
  const styles: Record<string, string> = {
    danger: 'bg-gradient-to-r from-red-50 to-red-100 text-red-900 border-red-200 shadow-sm shadow-red-900/5',
    critical: 'bg-gradient-to-r from-rose-100 to-red-200 text-red-950 border-red-300 shadow-md shadow-red-900/10 font-bold',
    warning: 'bg-gradient-to-r from-amber-50 to-orange-100 text-amber-900 border-amber-200 shadow-sm shadow-amber-900/5',
  };
  const icons: Record<string, React.ReactNode> = {
    danger: <AlertCircle className="w-5 h-5 text-red-600" />,
    critical: <AlertTriangle className="w-6 h-6 text-red-700 drop-shadow-sm" />,
    warning: <TrendingDown className="w-5 h-5 text-amber-600" />,
  };

  return (
    <div onClick={onClick} className={`p-4 rounded-2xl border mb-3 flex items-start space-x-3 cursor-pointer active:scale-[0.98] transition-all duration-200 ${styles[variant]}`}>
      <div className="mt-0.5 bg-white/50 p-1.5 rounded-full shadow-sm">{icons[variant]}</div>
      <div className="flex-1">
        <h4 className="text-[15px] font-bold leading-tight">{title}</h4>
        {subtitle && <p className="text-xs opacity-80 mt-1 font-medium">{subtitle}</p>}
      </div>
      <div className="opacity-50 self-center"><ChevronRight className="w-5 h-5" /></div>
    </div>
  );
}

function TopBar({ title, onBack, right }: { title: string; onBack: () => void; right?: React.ReactNode }) {
  return (
    <div className="bg-white/80 backdrop-blur-xl px-4 py-3 shadow-[0_4px_20px_-10px_rgba(0,0,0,0.05)] z-20 flex items-center space-x-3 sticky top-0 border-b border-slate-100/50">
      <button onClick={onBack} className="p-2 -ml-2 rounded-full hover:bg-slate-100 active:bg-slate-200 transition-colors">
        <ArrowLeft className="w-6 h-6 text-slate-700" />
      </button>
      <h2 className="text-lg font-extrabold text-slate-900 tracking-tight flex-1">{title}</h2>
      {right}
    </div>
  );
}

function QuickActionButton({ icon, label, onClick, primary = false }: { icon: React.ReactNode; label: string; onClick: () => void; primary?: boolean }) {
  return (
    <div className="flex flex-col items-center space-y-2 cursor-pointer group" onClick={onClick}>
      <div className={`w-14 h-14 rounded-[1.25rem] flex items-center justify-center transition-all duration-300 active:scale-90 ${primary ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/30' : 'bg-white text-slate-600 border border-slate-200/60 shadow-sm hover:border-indigo-100 hover:text-indigo-600'}`}>
        {icon}
      </div>
      <span className="text-[11px] font-bold text-slate-500 tracking-tight">{label}</span>
    </div>
  );
}

function DashboardAlertRow({ icon, title, subtitle, variant, onClick }: { icon: React.ReactNode; title: string; subtitle: string; variant: string; onClick: () => void }) {
  const styles: Record<string, string> = {
    danger: 'bg-rose-50 text-rose-600',
    critical: 'bg-red-500 text-white shadow-md shadow-red-500/20',
    warning: 'bg-amber-50 text-amber-600',
  };
  return (
    <div onClick={onClick} className="flex items-center space-x-4 p-3 rounded-2xl hover:bg-slate-50 active:scale-[0.98] transition-all cursor-pointer">
      <div className={`w-12 h-12 rounded-xl flex items-center justify-center shrink-0 ${styles[variant]}`}>{icon}</div>
      <div className="flex-1 min-w-0">
        <h4 className="text-sm font-bold text-slate-900 truncate">{title}</h4>
        <p className="text-xs font-semibold text-slate-500 truncate mt-0.5">{subtitle}</p>
      </div>
      <div className="w-8 h-8 rounded-full bg-slate-50 flex items-center justify-center shrink-0">
        <ChevronRight className="w-4 h-4 text-slate-400" />
      </div>
    </div>
  );
}

// --- DASHBOARD SCREEN ---

function Dashboard({ navigate }: { navigate: (s: string) => void }) {
  const { batches, medicines, sales, settings, apiStatus, apiDashboard, apiAlerts } = useStore();
  const today = new Date();
  const currentHour = getHours(today);
  let greeting = 'Good evening';
  if (currentHour < 12) greeting = 'Good morning';
  else if (currentHour < 17) greeting = 'Good afternoon';

  // Use API data if connected, else compute locally
  const usingApi = apiStatus === 'connected' && !!apiDashboard;

  const todaysRevenue = usingApi
    ? parseFloat(String(apiDashboard!.sales_today_bdt)) || 0
    : sales.filter(s => differenceInDays(today, parseISO(s.date)) === 0).reduce((sum, s) => sum + s.total, 0);

  const todaysSalesCount = usingApi
    ? apiDashboard!.sales_count_today
    : sales.filter(s => differenceInDays(today, parseISO(s.date)) === 0).length;

  const activeBatches = batches.filter(b => b.remaining > 0);

  const expiredCount = usingApi
    ? apiDashboard!.expired_batches
    : activeBatches.filter(b => isPast(parseISO(b.expiry))).length;

  const expiredLoss = activeBatches.filter(b => isPast(parseISO(b.expiry))).reduce((sum, b) => sum + b.remaining * b.price, 0);

  const expiringCount = usingApi
    ? apiDashboard!.expiring_soon_batches
    : activeBatches.filter(b => { const d = differenceInDays(parseISO(b.expiry), today); return d >= 0 && d <= 30; }).length;

  const expiringBatches = activeBatches.filter(b => { const d = differenceInDays(parseISO(b.expiry), today); return d >= 0 && d <= 30; });
  const expiringLoss = expiringBatches.reduce((sum, b) => sum + b.remaining * b.price, 0);

  const lowStockMeds = usingApi && apiAlerts
    ? apiAlerts.low_stock
    : medicines.filter(m => {
        const total = activeBatches.filter(b => b.medId === m.id).reduce((sum, b) => sum + b.remaining, 0);
        return total < m.minStock;
      });

  const hasAlerts = expiredCount > 0 || expiringCount > 0 || lowStockMeds.length > 0;

  return (
    <div className="pb-32 h-full overflow-y-auto scrollbar-hidden bg-[#F4F6F8] scroll-smooth animate-in fade-in duration-500">
      <div className="px-6 pt-8 pb-2 flex justify-between items-center">
        <div>
          <p className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-1">{greeting}</p>
          <h1 className="text-2xl font-black text-slate-900 tracking-tight">{settings.shopName}</h1>
        </div>
        <div className="flex flex-col items-center space-y-1">
          <div className="w-12 h-12 rounded-[1.2rem] bg-white border border-slate-200/60 shadow-sm flex items-center justify-center shrink-0">
            <Building className="w-6 h-6 text-indigo-600" />
          </div>
          {apiStatus !== 'disconnected' && (
            <div className="flex items-center space-x-1">
              <StatusDot status={apiStatus} />
              <span className="text-[9px] font-bold text-slate-400 uppercase">
                {apiStatus === 'connected' ? 'Live' : apiStatus === 'syncing' ? 'Sync' : 'Err'}
              </span>
            </div>
          )}
        </div>
      </div>

      <div className="px-6 mt-4">
        <div className="relative bg-slate-900 rounded-[2rem] p-7 shadow-2xl shadow-slate-900/20 overflow-hidden isolate">
          <div className="absolute -top-12 -right-12 w-48 h-48 bg-indigo-500 rounded-full mix-blend-screen filter blur-[3rem] opacity-40 z-0"></div>
          <div className="absolute -bottom-12 -left-12 w-40 h-40 bg-blue-500 rounded-full mix-blend-screen filter blur-[3rem] opacity-30 z-0"></div>
          <div className="relative z-10 flex justify-between items-start mb-6">
            <div>
              <h3 className="text-slate-400 text-xs font-bold uppercase tracking-wider mb-1">Today's Revenue</h3>
              <div className="flex items-baseline space-x-1">
                <span className="text-slate-300 font-bold text-2xl mb-1">{settings.currency}</span>
                <span className="text-white text-5xl font-black tracking-tighter leading-none">{todaysRevenue.toFixed(2)}</span>
              </div>
            </div>
            <div className="bg-white/10 backdrop-blur-md p-2 rounded-xl">
              <Activity className="w-5 h-5 text-indigo-300" />
            </div>
          </div>
          <div className="relative z-10 flex space-x-3">
            <div className="bg-white/10 backdrop-blur-md px-3.5 py-2 rounded-xl flex items-center space-x-2 border border-white/5">
              <CheckCircle2 className="w-4 h-4 text-emerald-400" />
              <span className="text-xs font-bold text-white tracking-wide">{todaysSalesCount} Sales</span>
            </div>
            <div className="bg-white/10 backdrop-blur-md px-3.5 py-2 rounded-xl flex items-center space-x-2 border border-white/5">
              <Clock className="w-4 h-4 text-amber-400" />
              <span className="text-xs font-bold text-white tracking-wide">{format(today, 'MMM dd')}</span>
            </div>
            {usingApi && (
              <div className="bg-white/10 backdrop-blur-md px-3.5 py-2 rounded-xl flex items-center space-x-2 border border-white/5">
                <Wifi className="w-4 h-4 text-emerald-400" />
                <span className="text-xs font-bold text-white tracking-wide">Live</span>
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="px-7 mt-8 flex justify-between items-start">
        <QuickActionButton primary icon={<ShoppingCart className="w-6 h-6" />} label="Sell" onClick={() => navigate('pos')} />
        <QuickActionButton icon={<Truck className="w-6 h-6" />} label="Receive" onClick={() => navigate('purchase')} />
        <QuickActionButton icon={<Plus className="w-6 h-6" />} label="Add Med" onClick={() => navigate('add_medicine')} />
        <QuickActionButton icon={<ClipboardList className="w-6 h-6" />} label="Reports" onClick={() => navigate('reports')} />
      </div>

      <div className="px-6 mt-8">
        <div className="bg-white rounded-[2rem] p-5 shadow-[0_8px_30px_-15px_rgba(0,0,0,0.04)] border border-slate-200/50">
          <div className="flex justify-between items-end px-2 mb-4">
            <h3 className="text-base font-black text-slate-900 tracking-tight">Needs Attention</h3>
            {hasAlerts && <span className="text-[10px] font-bold text-rose-500 bg-rose-50 px-2 py-1 rounded-md uppercase tracking-wider">Action Req</span>}
          </div>
          <div className="space-y-1">
            {!hasAlerts ? (
              <div className="py-6 flex flex-col items-center justify-center text-slate-400">
                <CheckCircle2 className="w-10 h-10 text-emerald-400 mb-2 opacity-50" />
                <p className="text-sm font-bold">You're all caught up!</p>
                <p className="text-xs font-medium mt-1 text-slate-400">Inventory is looking good.</p>
              </div>
            ) : (
              <>
                {expiredCount > 0 && (
                  <DashboardAlertRow variant="critical" icon={<AlertTriangle className="w-6 h-6" />}
                    title={`${expiredCount} Expired Items`}
                    subtitle={`${settings.currency}${expiredLoss.toFixed(2)} total loss value`}
                    onClick={() => navigate('expiry')} />
                )}
                {expiringCount > 0 && (
                  <DashboardAlertRow variant="danger" icon={<Clock className="w-6 h-6" />}
                    title={`${expiringCount} Expiring Soon`}
                    subtitle={`Review before ${format(addDays(today, 30), 'MMM dd')}`}
                    onClick={() => navigate('expiry')} />
                )}
                {lowStockMeds.length > 0 && (
                  <DashboardAlertRow variant="warning" icon={<TrendingDown className="w-6 h-6" />}
                    title={`${lowStockMeds.length} Low Stock`}
                    subtitle="Below minimum threshold"
                    onClick={() => navigate('low_stock')} />
                )}
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// --- SETTINGS SCREEN ---

function SettingsScreen({ navigate }: { navigate: (s: string) => void }) {
  const { settings, updateSetting, resetDatabase, apiStatus } = useStore();
  const { sync } = useApiSync();
  const [localShopName, setLocalShopName] = useState(settings.shopName);
  const [localKey, setLocalKey] = useState(settings.pharmacyKey);
  const [keyVisible, setKeyVisible] = useState(false);

  const handleSave = () => {
    updateSetting('shopName', localShopName);
    alert('Settings saved!');
  };

  const handleSaveKey = () => {
    updateSetting('pharmacyKey', localKey.trim());
    setTimeout(() => sync(), 100);
  };

  const handleExport = () => {
    const dataStr = 'data:text/json;charset=utf-8,' + encodeURIComponent(JSON.stringify(useStore.getState()));
    const a = document.createElement('a');
    a.setAttribute('href', dataStr);
    a.setAttribute('download', `pharma_backup_${format(new Date(), 'yyyy-MM-dd')}.json`);
    document.body.appendChild(a);
    a.click();
    a.remove();
  };

  const handleReset = () => {
    if (window.confirm('CRITICAL: Delete ALL medicines, batches, sales and settings?')) {
      if (window.confirm('Final confirmation — click OK to reset.')) {
        resetDatabase();
        navigate('dashboard');
      }
    }
  };

  const statusLabel: Record<ApiStatus, string> = {
    disconnected: 'Not connected',
    syncing: 'Syncing…',
    connected: 'Connected',
    error: 'Connection error',
  };
  const statusColor: Record<ApiStatus, string> = {
    disconnected: 'text-slate-400',
    syncing: 'text-amber-500',
    connected: 'text-emerald-600',
    error: 'text-rose-500',
  };

  return (
    <div className="flex flex-col h-full bg-slate-50 animate-in slide-in-from-right-8 duration-300">
      <TopBar title="Settings" onBack={() => navigate('dashboard')} />
      <div className="flex-1 p-5 overflow-auto scrollbar-hidden space-y-6">

        <section>
          <h3 className="text-[13px] font-bold text-slate-400 uppercase tracking-wider mb-3 px-1">Pharmacy Profile</h3>
          <div className="bg-white p-5 rounded-3xl shadow-sm border border-slate-100/50">
            <div className="flex items-center space-x-4 mb-4">
              <div className="w-12 h-12 bg-indigo-50 rounded-2xl flex items-center justify-center text-indigo-600">
                <Building className="w-6 h-6" />
              </div>
              <div className="flex-1">
                <label className="text-xs font-bold text-slate-500 mb-1 block">Shop Name</label>
                <input type="text" value={localShopName} onChange={e => setLocalShopName(e.target.value)}
                  className="w-full text-base font-bold text-slate-900 border-b-2 border-slate-100 focus:border-indigo-500 pb-1 outline-none bg-transparent transition-colors" />
              </div>
            </div>
            <button onClick={handleSave} className="w-full bg-slate-900 hover:bg-slate-800 text-white font-bold py-3.5 rounded-xl shadow-md transition-colors text-sm">
              Save Profile
            </button>
          </div>
        </section>

        <section>
          <h3 className="text-[13px] font-bold text-slate-400 uppercase tracking-wider mb-3 px-1">Backend API</h3>
          <div className="bg-white p-5 rounded-3xl shadow-sm border border-slate-100/50 space-y-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center space-x-2">
                {apiStatus === 'connected' ? <Wifi className="w-4 h-4 text-emerald-500" /> : apiStatus === 'error' ? <WifiOff className="w-4 h-4 text-rose-500" /> : <Database className="w-4 h-4 text-slate-400" />}
                <span className={`text-sm font-bold ${statusColor[apiStatus]}`}>{statusLabel[apiStatus]}</span>
              </div>
              {settings.pharmacyKey && (
                <button onClick={sync} className="flex items-center space-x-1 text-indigo-600 text-xs font-bold bg-indigo-50 px-3 py-1.5 rounded-xl active:scale-95 transition-all">
                  <RefreshCw className="w-3.5 h-3.5" />
                  <span>Sync</span>
                </button>
              )}
            </div>

            <div>
              <label className="text-xs font-bold text-slate-500 mb-2 block flex items-center space-x-1">
                <Key className="w-3.5 h-3.5" /><span>Pharmacy API Key</span>
              </label>
              <div className="relative">
                <input
                  type={keyVisible ? 'text' : 'password'}
                  value={localKey}
                  onChange={e => setLocalKey(e.target.value)}
                  placeholder="phm_..."
                  className="w-full p-3 pr-12 border-2 border-slate-100 rounded-xl bg-slate-50 text-sm font-mono text-slate-800 outline-none focus:border-indigo-500 transition-colors"
                />
                <button onClick={() => setKeyVisible(v => !v)} className="absolute right-3 top-3 text-slate-400 hover:text-slate-600">
                  <span className="text-xs font-bold">{keyVisible ? 'Hide' : 'Show'}</span>
                </button>
              </div>
              <p className="text-[10px] text-slate-400 mt-1.5 px-1">Generated by <code className="font-mono">python manage.py create_pharmacy</code> on Render.</p>
            </div>

            <button onClick={handleSaveKey} disabled={!localKey.trim()}
              className="w-full bg-indigo-600 disabled:bg-slate-200 disabled:text-slate-400 text-white font-bold py-3.5 rounded-xl shadow-md transition-colors text-sm active:scale-[0.98]">
              Connect &amp; Sync
            </button>

            {settings.pharmacyKey && (
              <button onClick={() => { updateSetting('pharmacyKey', ''); setLocalKey(''); }}
                className="w-full border-2 border-slate-100 text-slate-500 font-bold py-3 rounded-xl text-sm active:scale-[0.98] transition-all">
                Disconnect API
              </button>
            )}
          </div>
        </section>

        <section>
          <h3 className="text-[13px] font-bold text-slate-400 uppercase tracking-wider mb-3 px-1">Data Management</h3>
          <div className="bg-white rounded-3xl shadow-sm border border-slate-100/50 overflow-hidden">
            <button onClick={handleExport} className="w-full p-5 flex items-center space-x-4 border-b border-slate-50 active:bg-slate-50 transition-colors">
              <div className="w-10 h-10 bg-blue-50 rounded-xl flex items-center justify-center text-blue-600"><Download className="w-5 h-5" /></div>
              <div className="flex-1 text-left">
                <h4 className="font-bold text-slate-900 text-[15px]">Export Database Backup</h4>
                <p className="text-xs font-medium text-slate-500 mt-0.5">Save a copy of your records to JSON</p>
              </div>
              <ChevronRight className="w-5 h-5 text-slate-300" />
            </button>
            <button onClick={handleReset} className="w-full p-5 flex items-center space-x-4 active:bg-rose-50 transition-colors group">
              <div className="w-10 h-10 bg-rose-50 rounded-xl flex items-center justify-center text-rose-600 group-active:bg-rose-100"><RotateCcw className="w-5 h-5" /></div>
              <div className="flex-1 text-left">
                <h4 className="font-bold text-rose-600 text-[15px]">Factory Reset</h4>
                <p className="text-xs font-medium text-rose-400/80 mt-0.5">Permanently delete all app data</p>
              </div>
            </button>
          </div>
        </section>

        <p className="text-center text-xs font-bold text-slate-400 mt-8">Version 1.0.0 · rakho-api.onrender.com</p>
      </div>
    </div>
  );
}

// --- POS SCREEN ---

function POS({ navigate }: { navigate: (s: string) => void }) {
  const { medicines, batches, processSale, settings } = useStore();
  const [search, setSearch] = useState('');
  const [cart, setCart] = useState<Array<{
    id: number; medId: string | number; name: string; price: number; quantity: number;
    selectedBatchId: string | number; availableBatches: LocalBatch[];
  }>>([]);
  const [loading, setLoading] = useState(false);

  const activeBatches = useMemo(() => batches.filter(b => b.remaining > 0), [batches]);

  const addToCart = (med: LocalMedicine) => {
    const medBatches = activeBatches
      .filter(b => b.medId === med.id)
      .sort((a, b) => new Date(a.expiry).getTime() - new Date(b.expiry).getTime());
    if (medBatches.length === 0) { alert('Out of stock!'); return; }
    const fefoBatch = medBatches[0];
    if (isPast(parseISO(fefoBatch.expiry))) {
      if (!window.confirm('WARNING: The selected batch is expired. Add anyway?')) return;
    }
    setCart([...cart, { id: Date.now(), medId: med.id, name: med.name, price: med.price, quantity: 1, selectedBatchId: fefoBatch.id, availableBatches: medBatches }]);
    setSearch('');
  };

  const updateQuantity = (cartItemId: number, newQty: number) => {
    setCart(cart.map(item => {
      if (item.id === cartItemId) {
        const batch = item.availableBatches.find(b => b.id === item.selectedBatchId);
        return { ...item, quantity: Math.min(Math.max(1, newQty), batch ? batch.remaining : 0) };
      }
      return item;
    }));
  };

  const handleCheckout = async () => {
    if (cart.length === 0) return;
    setLoading(true);
    const key = settings.pharmacyKey;

    if (key) {
      try {
        const invoiceNumber = `INV-${Date.now()}`;
        await api.sales.create(key, {
          invoice_number: invoiceNumber,
          payment_method: 'cash',
          lines: cart.map(item => ({
            medicine: String(item.medId),
            quantity: item.quantity,
            unit_price: String(item.price.toFixed(2)),
          })),
        });
      } catch (err) {
        const proceed = window.confirm(`API sync failed (${(err as Error).message}). Save locally only?`);
        if (!proceed) { setLoading(false); return; }
      }
    }

    processSale(cart);
    setCart([]);
    setLoading(false);
    navigate('dashboard');
  };

  const total = cart.reduce((sum, item) => sum + item.price * item.quantity, 0);

  return (
    <div className="flex flex-col h-full bg-slate-50 animate-in slide-in-from-right-8 duration-300">
      <div className="bg-white/90 backdrop-blur-md p-4 shadow-sm z-20 flex items-center space-x-3 sticky top-0">
        <button onClick={() => navigate('dashboard')} className="p-2 -ml-2 rounded-full hover:bg-slate-100 transition-colors">
          <ArrowLeft className="w-6 h-6 text-slate-700" />
        </button>
        <div className="flex-1 relative">
          <Search className="w-5 h-5 text-slate-400 absolute left-3.5 top-3" />
          <input autoFocus type="text" placeholder="Search medicine…"
            className="w-full pl-11 pr-4 py-2.5 bg-slate-100 focus:bg-white focus:ring-2 focus:ring-indigo-500/30 border border-transparent focus:border-indigo-500 rounded-2xl outline-none text-[15px] font-bold text-slate-900 transition-all shadow-inner shadow-slate-200/50"
            value={search} onChange={e => setSearch(e.target.value)} />
        </div>
      </div>

      <div className="flex-1 p-4 overflow-auto scrollbar-hidden scroll-smooth">
        {search !== '' ? (
          <div className="space-y-3">
            {medicines.filter(m => m.name.toLowerCase().includes(search.toLowerCase())).map(med => {
              const medStock = activeBatches.filter(b => b.medId === med.id).reduce((sum, b) => sum + b.remaining, 0);
              return (
                <div key={String(med.id)} onClick={() => addToCart(med)}
                  className="bg-white p-4 rounded-3xl border border-slate-100 shadow-[0_2px_10px_-4px_rgba(0,0,0,0.05)] flex justify-between items-center cursor-pointer active:scale-95 transition-all">
                  <div>
                    <h4 className="font-bold text-slate-900 text-lg">{med.name} <span className="font-semibold text-slate-400 text-sm ml-1">{med.strength}</span></h4>
                    <p className="text-xs font-semibold text-slate-400 mt-0.5">{med.generic}</p>
                  </div>
                  <div className="text-right">
                    <p className="font-black text-indigo-600 text-lg">{settings.currency}{med.price.toFixed(2)}</p>
                    <p className={`text-xs font-bold mt-1 px-2 py-0.5 rounded-md inline-block ${medStock > 0 ? 'bg-emerald-50 text-emerald-600' : 'bg-rose-50 text-rose-600'}`}>
                      {medStock > 0 ? `${medStock} in stock` : 'Out of stock'}
                    </p>
                  </div>
                </div>
              );
            })}
          </div>
        ) : cart.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-slate-400">
            <div className="bg-slate-100 p-6 rounded-full mb-4 shadow-inner">
              <ShoppingCart className="w-10 h-10 text-slate-300" />
            </div>
            <p className="font-bold text-slate-500">Scan or search items</p>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="bg-indigo-50 text-indigo-800 text-[11px] uppercase tracking-wider px-4 py-2.5 rounded-2xl font-black flex items-center shadow-sm border border-indigo-100/50">
              <Check className="w-4 h-4 mr-2 text-indigo-600" />
              FEFO Sorting Active (Soonest Expiry First)
            </div>
            {cart.map(item => (
              <div key={item.id} className="bg-white p-4 rounded-3xl shadow-[0_4px_15px_-5px_rgba(0,0,0,0.05)] border border-slate-100">
                <div className="flex justify-between items-start mb-3">
                  <span className="font-black text-slate-900 text-[17px]">{item.name}</span>
                  <button onClick={() => setCart(cart.filter(c => c.id !== item.id))} className="text-slate-300 hover:text-rose-500 transition-colors p-1 bg-slate-50 rounded-full">
                    <X className="w-5 h-5" />
                  </button>
                </div>
                <div className="flex overflow-x-auto scrollbar-hidden space-x-2 mb-4 pb-1">
                  {item.availableBatches.map(b => (
                    <div key={String(b.id)} onClick={() => setCart(cart.map(c => c.id === item.id ? { ...c, selectedBatchId: b.id } : c))}
                      className={`text-xs px-3 py-1.5 rounded-xl whitespace-nowrap cursor-pointer border-2 transition-all font-bold ${item.selectedBatchId === b.id ? 'bg-indigo-50 border-indigo-500 text-indigo-700 shadow-sm shadow-indigo-500/20' : 'bg-white border-slate-100 text-slate-500 hover:border-slate-200'}`}>
                      {item.selectedBatchId === b.id && '✓ '}Batch {b.batchNo} ({b.remaining})
                    </div>
                  ))}
                </div>
                <div className="flex justify-between items-center bg-slate-50 p-2 rounded-2xl">
                  <div className="flex items-center space-x-1 bg-white rounded-xl p-1 shadow-sm border border-slate-100">
                    <button onClick={() => updateQuantity(item.id, item.quantity - 1)} className="w-10 h-10 flex items-center justify-center bg-slate-50 active:bg-slate-200 rounded-lg text-slate-700 font-bold transition-colors">-</button>
                    <span className="w-10 text-center font-black text-[15px]">{item.quantity}</span>
                    <button onClick={() => updateQuantity(item.id, item.quantity + 1)} className="w-10 h-10 flex items-center justify-center bg-slate-50 active:bg-slate-200 rounded-lg text-slate-700 font-bold transition-colors">+</button>
                  </div>
                  <span className="font-black text-slate-900 text-xl pr-2">{settings.currency}{(item.price * item.quantity).toFixed(2)}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="bg-white border-t border-slate-100 p-5 rounded-t-[2.5rem] shadow-[0_-10px_40px_-15px_rgba(0,0,0,0.05)] relative z-20">
        <div className="flex justify-between items-center mb-5 px-2">
          <span className="text-slate-500 font-bold uppercase tracking-wider text-xs">Total ({cart.length} items)</span>
          <span className="text-3xl font-black text-slate-900">{settings.currency}{total.toFixed(2)}</span>
        </div>
        <button disabled={cart.length === 0 || loading} onClick={handleCheckout}
          className="w-full bg-gradient-to-r from-indigo-600 to-blue-700 disabled:from-slate-200 disabled:to-slate-300 disabled:text-slate-400 text-white font-black py-4 rounded-2xl shadow-xl shadow-indigo-600/30 active:scale-[0.98] transition-all text-lg tracking-tight">
          {loading ? 'Processing…' : 'COMPLETE SALE'}
        </button>
      </div>
    </div>
  );
}

// --- EXPIRY MANAGEMENT ---

function ExpiryManagement({ navigate }: { navigate: (s: string) => void }) {
  const { batches, medicines, markWastage, settings } = useStore();
  const [loading, setLoading] = useState<string | number | null>(null);
  const today = new Date();

  const activeBatches = batches.filter(b => b.remaining > 0).map(b => {
    const med = medicines.find(m => m.id === b.medId);
    return { ...b, medName: med ? med.name : 'Unknown' };
  }).sort((a, b) => new Date(a.expiry).getTime() - new Date(b.expiry).getTime());

  const getExpiryStyle = (expiryIso: string) => {
    const exp = parseISO(expiryIso);
    if (isPast(exp)) return 'bg-rose-100 text-rose-800 border-rose-200';
    if (differenceInDays(exp, today) <= 30) return 'bg-amber-100 text-amber-800 border-amber-200';
    return 'bg-emerald-100 text-emerald-800 border-emerald-200';
  };

  const handleWastage = async (batchId: string | number) => {
    if (!window.confirm('Mark this batch as wastage? Stock will be reduced to 0.')) return;
    setLoading(batchId);
    const key = settings.pharmacyKey;
    if (key) {
      try {
        await api.wastage.mark(key, String(batchId), 'Marked as wastage from app');
      } catch {
        if (!window.confirm('API sync failed. Mark locally only?')) { setLoading(null); return; }
      }
    }
    markWastage(batchId);
    setLoading(null);
  };

  return (
    <div className="flex flex-col h-full bg-slate-50 animate-in slide-in-from-right-8 duration-300">
      <TopBar title="Expiry Management" onBack={() => navigate('dashboard')} />
      <div className="flex-1 p-4 overflow-auto scrollbar-hidden space-y-4">
        {activeBatches.map(batch => {
          const daysLeft = differenceInDays(parseISO(batch.expiry), today);
          const isExp = daysLeft < 0;
          return (
            <div key={String(batch.id)} className="bg-white p-5 rounded-3xl border border-slate-100 shadow-[0_4px_20px_-10px_rgba(0,0,0,0.05)] flex flex-col">
              <div className="flex justify-between items-start mb-4">
                <div>
                  <h4 className="font-black text-slate-900 text-lg tracking-tight">{batch.medName}</h4>
                  <p className="text-sm font-semibold text-slate-400 mt-0.5">Batch: {batch.batchNo} · {batch.remaining} units</p>
                </div>
                <div className={`px-3 py-1.5 rounded-xl border text-[11px] uppercase tracking-wider font-black ${getExpiryStyle(batch.expiry)}`}>
                  {isExp ? `Expired ${Math.abs(daysLeft)}d ago` : `${daysLeft} days left`}
                </div>
              </div>
              <div className="flex justify-between items-center mt-2 pt-4 border-t border-slate-50">
                <span className="font-bold text-slate-600 text-sm">Value: <span className="text-slate-900 font-black">{settings.currency}{(batch.remaining * batch.price).toFixed(2)}</span></span>
                <button disabled={loading === batch.id} onClick={() => handleWastage(batch.id)}
                  className="bg-rose-50 hover:bg-rose-100 disabled:opacity-50 text-rose-600 px-4 py-2 rounded-xl text-sm font-bold transition-colors active:scale-95">
                  {loading === batch.id ? '…' : 'Mark Wastage'}
                </button>
              </div>
            </div>
          );
        })}
        {activeBatches.length === 0 && (
          <div className="flex flex-col items-center justify-center mt-20 text-slate-400">
            <div className="w-16 h-16 bg-slate-100 rounded-full flex items-center justify-center mb-4">
              <Check className="w-8 h-8 text-emerald-500" />
            </div>
            <p className="font-bold">Inventory is healthy</p>
            <p className="text-sm mt-1">No active stock alerts.</p>
          </div>
        )}
      </div>
    </div>
  );
}

// --- PURCHASE / RECEIVE STOCK ---

function PurchaseStock({ navigate }: { navigate: (s: string) => void }) {
  const { medicines, addPurchase, settings } = useStore();
  const [items, setItems] = useState<Array<{ id: number; medId: string | number; name: string; batchNo: string; expiry: string; quantity: number; cost: number }>>([]);
  const [selectedMed, setSelectedMed] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSave = async () => {
    if (items.length === 0) return;
    setLoading(true);
    const key = settings.pharmacyKey;
    if (key) {
      try {
        await api.purchases.receive(key, items.map(item => ({
          medicine: String(item.medId),
          batch_number: item.batchNo,
          expiry_date: item.expiry,
          quantity: item.quantity,
          unit_cost: item.cost.toFixed(2),
          selling_price: item.cost.toFixed(2),
        })));
      } catch (err) {
        const proceed = window.confirm(`API sync failed (${(err as Error).message}). Save locally only?`);
        if (!proceed) { setLoading(false); return; }
      }
    }
    addPurchase(items);
    setLoading(false);
    navigate('dashboard');
  };

  return (
    <div className="flex flex-col h-full bg-slate-50 animate-in slide-in-from-right-8 duration-300">
      <TopBar title="Receive Stock" onBack={() => navigate('dashboard')} />
      <div className="flex-1 overflow-auto scrollbar-hidden p-4 space-y-4">
        <div className="bg-white p-5 rounded-3xl shadow-sm border border-slate-100">
          <label className="text-[11px] uppercase tracking-wider font-black text-slate-400 mb-2 block ml-1">Select Medicine</label>
          <div className="relative">
            <select className="w-full p-4 border-2 border-slate-100 rounded-2xl bg-slate-50 mb-1 font-bold text-slate-700 outline-none focus:border-indigo-500 transition-colors appearance-none"
              value={selectedMed}
              onChange={e => {
                if (e.target.value) {
                  const med = medicines.find(m => String(m.id) === e.target.value);
                  if (med) {
                    setItems([...items, { id: Date.now(), medId: med.id, name: med.name, batchNo: '', expiry: format(addDays(new Date(), 365), 'yyyy-MM-dd'), quantity: 10, cost: med.price }]);
                    setSelectedMed('');
                  }
                }
              }}>
              <option value="">-- Select medicine --</option>
              {medicines.map(m => <option key={String(m.id)} value={String(m.id)}>{m.name} ({m.strength})</option>)}
            </select>
            <ChevronRight className="absolute right-4 top-4 w-5 h-5 text-slate-400 pointer-events-none rotate-90" />
          </div>
        </div>

        {items.map((item, idx) => (
          <div key={item.id} className="bg-white p-5 rounded-3xl border border-slate-100 shadow-[0_4px_20px_-10px_rgba(0,0,0,0.05)] relative overflow-hidden">
            <div className="absolute top-0 right-0 w-full h-1 bg-indigo-500"></div>
            <button onClick={() => setItems(items.filter(i => i.id !== item.id))} className="absolute top-4 right-4 text-slate-300 hover:text-rose-400 p-1 bg-slate-50 rounded-full transition-colors">
              <X className="w-5 h-5" />
            </button>
            <h4 className="font-black text-slate-900 text-lg mb-5">{item.name}</h4>
            <div className="grid grid-cols-2 gap-4 mb-4">
              <div>
                <label className="text-[10px] uppercase tracking-wider font-black text-slate-400 block mb-1">Batch Number *</label>
                <input type="text" placeholder="e.g. B-123"
                  className="w-full p-3 border-2 border-slate-100 rounded-xl bg-slate-50 text-sm font-bold text-slate-800 outline-none focus:border-indigo-500 transition-colors"
                  value={item.batchNo} onChange={e => { const n = [...items]; n[idx].batchNo = e.target.value; setItems(n); }} />
              </div>
              <div>
                <label className="text-[10px] uppercase tracking-wider font-black text-slate-400 block mb-1">Expiry Date *</label>
                <input type="date"
                  className="w-full p-3 border-2 border-slate-100 rounded-xl bg-slate-50 text-sm font-bold text-slate-800 outline-none focus:border-indigo-500 transition-colors"
                  value={item.expiry} onChange={e => { const n = [...items]; n[idx].expiry = e.target.value; setItems(n); }} />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-[10px] uppercase tracking-wider font-black text-slate-400 block mb-1">Qty Received *</label>
                <input type="number"
                  className="w-full p-3 border-2 border-slate-100 rounded-xl bg-slate-50 text-base font-black text-slate-800 outline-none focus:border-indigo-500 transition-colors"
                  value={item.quantity} onChange={e => { const n = [...items]; n[idx].quantity = Number(e.target.value); setItems(n); }} />
              </div>
              <div>
                <label className="text-[10px] uppercase tracking-wider font-black text-slate-400 block mb-1">Unit Cost ({settings.currency})</label>
                <input type="number"
                  className="w-full p-3 border-2 border-slate-100 rounded-xl bg-slate-50 text-base font-black text-indigo-600 outline-none focus:border-indigo-500 transition-colors"
                  value={item.cost} onChange={e => { const n = [...items]; n[idx].cost = Number(e.target.value); setItems(n); }} />
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="bg-white border-t border-slate-100 p-5 rounded-t-[2.5rem] shadow-[0_-10px_40px_-15px_rgba(0,0,0,0.05)] relative z-20">
        <button
          disabled={items.length === 0 || items.some(i => !i.batchNo || !i.expiry || i.quantity <= 0) || loading}
          onClick={handleSave}
          className="w-full bg-gradient-to-r from-emerald-500 to-emerald-600 disabled:from-slate-200 disabled:to-slate-300 disabled:text-slate-400 text-white font-black py-4 rounded-2xl shadow-xl shadow-emerald-500/30 active:scale-[0.98] transition-all text-lg tracking-tight">
          {loading ? 'Saving…' : 'SAVE PURCHASE'}
        </button>
      </div>
    </div>
  );
}

// --- ADD MEDICINE SCREEN (BD Catalog + Manual) ---

function AddMedicineScreen({ navigate }: { navigate: (s: string) => void }) {
  const { addMedicine, settings } = useStore();
  const [query, setQuery] = useState('');
  const [catalogResults, setCatalogResults] = useState<import('./api').CatalogMedicine[]>([]);
  const [searching, setSearching] = useState(false);
  const [selected, setSelected] = useState<import('./api').CatalogMedicine | null>(null);
  const [price, setPrice] = useState('');
  const [minStock, setMinStock] = useState('10');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (query.length < 2) { setCatalogResults([]); return; }
    const t = setTimeout(async () => {
      setSearching(true);
      try {
        const results = await api.catalog.search(query);
        setCatalogResults(Array.isArray(results) ? results.slice(0, 15) : []);
      } catch { setCatalogResults([]); }
      setSearching(false);
    }, 400);
    return () => clearTimeout(t);
  }, [query]);

  const handleAdd = async () => {
    if (!selected || !price) return;
    setSaving(true);
    const key = settings.pharmacyKey;
    if (key) {
      try {
        await api.medicines.create(key, {
          brand_name: selected.brand_name,
          generic_name: selected.generic_name,
          strength: selected.strength,
          dosage_form: selected.dosage_form,
          default_selling_price: parseFloat(price).toFixed(2),
          low_stock_threshold: parseInt(minStock) || 10,
          catalog_medicine: selected.id,
        });
      } catch (err) {
        const proceed = window.confirm(`API failed (${(err as Error).message}). Add locally only?`);
        if (!proceed) { setSaving(false); return; }
      }
    }
    addMedicine({
      id: Date.now(),
      name: selected.brand_name,
      generic: selected.generic_name,
      strength: selected.strength,
      form: selected.dosage_form,
      price: parseFloat(price) || 0,
      minStock: parseInt(minStock) || 10,
    });
    setSaving(false);
    navigate('dashboard');
  };

  return (
    <div className="flex flex-col h-full bg-slate-50 animate-in slide-in-from-right-8 duration-300">
      <TopBar title="Add Medicine" onBack={() => navigate('dashboard')} />
      <div className="flex-1 overflow-auto scrollbar-hidden p-4 space-y-4">

        {!selected ? (
          <>
            <div className="bg-white p-5 rounded-3xl shadow-sm border border-slate-100">
              <label className="text-[11px] uppercase tracking-wider font-black text-slate-400 mb-2 block">Search Bangladesh Catalog</label>
              <div className="relative">
                <Search className="w-5 h-5 text-slate-400 absolute left-3.5 top-3" />
                <input autoFocus type="text" placeholder="e.g. Napa, Seclo, Fexo…"
                  className="w-full pl-11 pr-4 py-2.5 bg-slate-50 border-2 border-slate-100 focus:border-indigo-500 rounded-2xl outline-none text-[15px] font-bold text-slate-900 transition-all"
                  value={query} onChange={e => setQuery(e.target.value)} />
              </div>
              {searching && <p className="text-xs text-slate-400 font-bold mt-2 px-1 animate-pulse">Searching catalog…</p>}
            </div>

            {catalogResults.length > 0 && (
              <div className="space-y-2">
                {catalogResults.map(med => (
                  <div key={med.id} onClick={() => { setSelected(med); setQuery(''); }}
                    className="bg-white p-4 rounded-2xl border border-slate-100 shadow-sm flex justify-between items-center cursor-pointer active:scale-95 transition-all">
                    <div>
                      <h4 className="font-bold text-slate-900">{med.brand_name} <span className="text-slate-400 font-semibold text-sm">{med.strength}</span></h4>
                      <p className="text-xs text-slate-400 font-semibold mt-0.5">{med.generic_name} · {med.dosage_form}</p>
                      <p className="text-[10px] text-slate-300 font-bold mt-0.5 uppercase tracking-wider">{med.manufacturer_name}</p>
                    </div>
                    <ChevronRight className="w-5 h-5 text-slate-300 shrink-0" />
                  </div>
                ))}
              </div>
            )}

            {query.length >= 2 && !searching && catalogResults.length === 0 && (
              <div className="bg-white p-5 rounded-2xl border border-slate-100 text-center">
                <p className="text-sm font-bold text-slate-500">No catalog matches for "{query}"</p>
                <p className="text-xs text-slate-400 mt-1">Try a different name or spelling.</p>
              </div>
            )}
          </>
        ) : (
          <>
            <div className="bg-indigo-50 border border-indigo-100 p-4 rounded-2xl flex items-start space-x-3">
              <div className="w-10 h-10 bg-indigo-100 rounded-xl flex items-center justify-center shrink-0">
                <Package className="w-5 h-5 text-indigo-600" />
              </div>
              <div className="flex-1">
                <h4 className="font-black text-indigo-900">{selected.brand_name} {selected.strength}</h4>
                <p className="text-xs text-indigo-600 font-semibold mt-0.5">{selected.generic_name} · {selected.dosage_form}</p>
                <p className="text-[10px] text-indigo-400 font-bold mt-0.5 uppercase tracking-wider">{selected.manufacturer_name}</p>
              </div>
              <button onClick={() => setSelected(null)} className="text-indigo-300 hover:text-indigo-500">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="bg-white p-5 rounded-3xl shadow-sm border border-slate-100 space-y-4">
              <div>
                <label className="text-[11px] uppercase tracking-wider font-black text-slate-400 block mb-2">Selling Price ({settings.currency}) *</label>
                <input type="number" placeholder="0.00" step="0.01"
                  className="w-full p-4 border-2 border-slate-100 rounded-2xl bg-slate-50 text-lg font-black text-indigo-600 outline-none focus:border-indigo-500 transition-colors"
                  value={price} onChange={e => setPrice(e.target.value)} />
              </div>
              <div>
                <label className="text-[11px] uppercase tracking-wider font-black text-slate-400 block mb-2">Low Stock Alert Threshold</label>
                <input type="number" placeholder="10"
                  className="w-full p-4 border-2 border-slate-100 rounded-2xl bg-slate-50 text-base font-bold text-slate-800 outline-none focus:border-indigo-500 transition-colors"
                  value={minStock} onChange={e => setMinStock(e.target.value)} />
              </div>
            </div>
          </>
        )}
      </div>

      {selected && (
        <div className="bg-white border-t border-slate-100 p-5 rounded-t-[2.5rem] shadow-[0_-10px_40px_-15px_rgba(0,0,0,0.05)] relative z-20">
          <button disabled={!price || saving} onClick={handleAdd}
            className="w-full bg-gradient-to-r from-indigo-600 to-blue-700 disabled:from-slate-200 disabled:to-slate-300 disabled:text-slate-400 text-white font-black py-4 rounded-2xl shadow-xl shadow-indigo-600/30 active:scale-[0.98] transition-all text-lg tracking-tight">
            {saving ? 'Adding…' : 'ADD TO PHARMACY'}
          </button>
        </div>
      )}
    </div>
  );
}

// --- MAIN APP ---

export default function App() {
  const [currentScreen, setCurrentScreen] = useState('dashboard');
  const { settings, updateSetting } = useStore();
  useApiSync();

  // Preserve existing installations while replacing the previous demo pharmacy name.
  useEffect(() => {
    if (settings.shopName === 'Bhai Bhai Pharmacy') {
      updateSetting('shopName', 'Halal Pharmacy');
    }
  }, [settings.shopName, updateSetting]);

  return (
    <div className="min-h-screen bg-slate-200 flex items-center justify-center p-4 sm:p-8 font-sans selection:bg-indigo-100 selection:text-indigo-900">
      <div className="w-full max-w-[420px] h-[860px] max-h-[95vh] bg-slate-900 rounded-[3.5rem] p-3.5 shadow-2xl relative ring-1 ring-white/10 shadow-slate-900/50">
        <div className="w-full h-full bg-slate-50 rounded-[2.8rem] overflow-hidden flex flex-col relative ring-1 ring-black/5">

          {/* Status Bar */}
          <div className="h-10 bg-transparent w-full flex justify-between items-center px-7 text-[12px] font-bold text-slate-900 absolute top-0 z-50 pointer-events-none">
            <span className="mt-1">{format(new Date(), 'HH:mm')}</span>
            <div className="absolute top-2 left-1/2 -translate-x-1/2 w-32 h-7 bg-black rounded-full pointer-events-auto"></div>
            <div className="flex space-x-1.5 items-center mt-1">
              <span>LTE</span>
              <div className="w-5 h-3 bg-slate-900 rounded-sm relative opacity-90"><div className="absolute right-[-3px] top-1 w-1 h-1 bg-slate-900 rounded-r-sm"></div></div>
            </div>
          </div>

          <div className="h-10 shrink-0 bg-transparent pointer-events-none z-40"></div>

          <div className="flex-1 overflow-hidden relative isolate">
            {currentScreen === 'dashboard' && <Dashboard navigate={setCurrentScreen} />}
            {currentScreen === 'pos' && <POS navigate={setCurrentScreen} />}
            {currentScreen === 'expiry' && <ExpiryManagement navigate={setCurrentScreen} />}
            {currentScreen === 'purchase' && <PurchaseStock navigate={setCurrentScreen} />}
            {currentScreen === 'settings' && <SettingsScreen navigate={setCurrentScreen} />}
            {currentScreen === 'add_medicine' && <AddMedicineScreen navigate={setCurrentScreen} />}

            {['low_stock', 'stock_take', 'reports'].includes(currentScreen) && (
              <div className="flex flex-col h-full bg-slate-50 animate-in slide-in-from-right-8 duration-300">
                <TopBar title="Coming Soon" onBack={() => setCurrentScreen('dashboard')} />
                <div className="flex-1 flex flex-col items-center justify-center text-slate-400 p-8 text-center">
                  <div className="bg-slate-100 p-6 rounded-full mb-5 shadow-inner">
                    <FileText className="w-12 h-12 text-slate-300" />
                  </div>
                  <h3 className="font-black text-slate-800 text-xl tracking-tight mb-2">Under Construction</h3>
                  <p className="font-semibold text-slate-500 text-sm">The '{currentScreen}' feature is coming in the next release.</p>
                </div>
              </div>
            )}
          </div>

          {['dashboard', 'expiry', 'settings'].includes(currentScreen) && (
            <div className="absolute bottom-6 left-6 right-6 bg-white/95 backdrop-blur-xl border border-slate-200/60 rounded-3xl flex justify-around py-3 px-2 shadow-[0_8px_30px_-10px_rgba(0,0,0,0.1)] z-50">
              <button onClick={() => setCurrentScreen('dashboard')} className={`flex flex-col items-center w-16 transition-colors ${currentScreen === 'dashboard' ? 'text-indigo-600' : 'text-slate-400 hover:text-slate-600'}`}>
                <div className={`p-1.5 rounded-xl mb-1 transition-all ${currentScreen === 'dashboard' ? 'bg-indigo-50' : 'bg-transparent'}`}>
                  <Home className="w-6 h-6" strokeWidth={currentScreen === 'dashboard' ? 2.5 : 2} />
                </div>
                <span className="text-[10px] font-bold tracking-tight">Home</span>
              </button>
              <button onClick={() => setCurrentScreen('expiry')} className={`flex flex-col items-center w-16 transition-colors ${currentScreen === 'expiry' ? 'text-indigo-600' : 'text-slate-400 hover:text-slate-600'}`}>
                <div className={`p-1.5 rounded-xl mb-1 transition-all ${currentScreen === 'expiry' ? 'bg-indigo-50' : 'bg-transparent'}`}>
                  <Package className="w-6 h-6" strokeWidth={currentScreen === 'expiry' ? 2.5 : 2} />
                </div>
                <span className="text-[10px] font-bold tracking-tight">Inventory</span>
              </button>
              <button onClick={() => setCurrentScreen('settings')} className={`flex flex-col items-center w-16 transition-colors ${currentScreen === 'settings' ? 'text-indigo-600' : 'text-slate-400 hover:text-slate-600'}`}>
                <div className={`p-1.5 rounded-xl mb-1 transition-all ${currentScreen === 'settings' ? 'bg-indigo-50' : 'bg-transparent'}`}>
                  <SettingsIcon className="w-6 h-6" strokeWidth={currentScreen === 'settings' ? 2.5 : 2} />
                </div>
                <span className="text-[10px] font-bold tracking-tight">Settings</span>
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
