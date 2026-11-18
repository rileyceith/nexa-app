import React, { useEffect, useRef, useState } from "react";
import { ADMIN_URL, API, selectWorkspace, selectedWorkspace, TOKEN_KEY, WORKSPACE_KEY } from "./api/client.js";
import { AuthSheet, RecordSheet } from "./components/index.jsx";
import { shrinkImage } from "./features/inventory/images.js";
import AccountSettings from "./features/settings/AccountSettings.jsx";
import TeamSettings from "./features/settings/TeamSettings.jsx";
import { currentUser, logout, resetPassword, verifyMagicLink } from "./features/auth/api.js";
import { listProducts } from "./features/catalog/api.js";
import { createExpense, createSale, listExpenses, listSales } from "./features/sales/api.js";
import { createPurchase, listBatches, listPurchases, receivePurchase, receiveStock } from "./features/inventory/api.js";
import { analyze, chat } from "./features/insights/api.js";
import { getDashboard, getReports } from "./features/reports/api.js";
import {
  getGoalSeries, getSettings, updateSettings, verifySettingsEmail, requestAccountConfirmation,
  exportAccountData, deleteAccount, acceptTeamInvitation, previewTeamInvitation,
} from "./features/settings/api.js";

function smoothPath(p) {
  let d = `M${p[0][0]},${p[0][1]}`;
  for (let i = 0; i < p.length - 1; i++) {
    const a = p[i - 1] || p[i], b = p[i], c = p[i + 1], e = p[i + 2] || c;
    d += ` C${b[0] + (c[0] - a[0]) / 6},${b[1] + (c[1] - a[1]) / 6} ${c[0] - (e[0] - b[0]) / 6},${c[1] - (e[1] - b[1]) / 6} ${c[0]},${c[1]}`;
  }
  return d;
}
let activeCurrency = 'USD';
let activeTimeZone = 'Africa/Harare';
const money = (n) => `${activeCurrency} ${Math.round(n).toLocaleString('en-US')}`;
const preciseMoney = (n) => `${activeCurrency} ${Number(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const wholeOrCents = (n) => (Number.isInteger(n) ? money(n) : preciseMoney(n));
const monthParts = () => Object.fromEntries(new Intl.DateTimeFormat('en-US', {
  timeZone: activeTimeZone, year: 'numeric', month: '2-digit',
}).formatToParts(new Date()).filter((part) => part.type === 'year' || part.type === 'month').map((part) => [part.type, Number(part.value)]));
const currentMonthKey = () => {
  const { year, month } = monthParts();
  return `${year}-${String(month).padStart(2, '0')}`;
};
const monthName = (offset = 0) => {
  const { year, month } = monthParts();
  return new Date(Date.UTC(year, month - 1 + offset, 1)).toLocaleString('en-US', { month: 'short', timeZone: 'UTC' });
};
const toNum = (v) => Number(v) || 0;
const monthLabel = (key) => new Date(key + '-01T00:00:00').toLocaleDateString('en-US', { month: 'short', year: 'numeric' });
// The series comes from settings/series/. A yearly goal is charted as monthly bars against a twelfth of the goal.
const goalChart = (series) => {
  const dateOf = (iso) => new Date(iso + 'T00:00:00');
  const monthShort = (iso) => dateOf(iso).toLocaleDateString('en-US', { month: 'short' });
  const monthYear = (iso) => dateOf(iso).toLocaleDateString('en-US', { month: 'short', year: 'numeric' });
  const target = toNum(series.target);
  const bars = (name, label) => series.buckets.map((b, i) => ({ name: name(b.start, i), label: label(b.start, i), value: toNum(b.amount) }));
  const charts = {
    day: { buckets: bars(shortDate, (iso, i) => (i === 0 || (i + 1) % 5 === 0 ? String(i + 1) : '')), heading: `Daily sales, ${monthName()}`, actual: 'Daily sales', targetText: `Daily target ${wholeOrCents(target)}` },
    week: { buckets: bars((iso) => `Week of ${shortDate(iso)}`, shortDate), heading: 'Weekly sales, last 8 weeks', actual: 'Weekly sales', targetText: `Weekly target ${wholeOrCents(target)}` },
    month: { buckets: bars(monthYear, monthShort), heading: 'Monthly sales, last 6 months', actual: 'Monthly sales', targetText: `Monthly target ${wholeOrCents(target)}` },
    year: { buckets: bars(monthYear, monthShort), heading: `Monthly sales, ${dateOf(series.buckets[0].start).getFullYear()}`, actual: 'Monthly sales', targetText: `Monthly target ${wholeOrCents(target)}` },
  };
  return { ...charts[series.period], current: series.current, target };
};
const SC = { Conservative: 0.97, Expected: 1.08, Optimistic: 1.2 };
const RECS = [];
const GOAL_PERIODS = [['day', 'Day'], ['week', 'Week'], ['month', 'Month'], ['year', 'Year']];
const GOAL_WORDS = { day: 'today', week: 'this week', month: 'this month', year: 'this year' };
const DEFAULT_PREFERENCES = {
  theme: 'light', currency: 'USD', time_zone: 'Africa/Harare',
  business_name: '', business_logo_url: '', business_email: '', business_phone: '',
  business_logo_zoom: 100, business_logo_x: 0, business_logo_y: 0,
  low_stock_threshold: '0.350', slow_stock_days: 45, reorder_lead_days: 14,
  safety_stock_days: 7, reorder_target_days: 30,
  email_verified: false, email_delivery_configured: false,
  notify_low_stock: false, notify_slow_stock: false, notify_goal_reached: false,
};
const CURRENCIES = ['USD', 'ZWL', 'ZAR', 'EUR', 'GBP'];
const TIME_ZONES = [
  'Africa/Harare', 'Africa/Johannesburg', 'Africa/Nairobi', 'Africa/Lagos',
  'UTC', 'Europe/London', 'Europe/Paris', 'America/New_York', 'America/Los_Angeles',
  'Asia/Dubai', 'Asia/Kolkata', 'Asia/Singapore', 'Australia/Sydney',
];
const shortDate = (iso) => new Date(iso + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' });

const IC = {
  rev: 'M12 3v18M16 7h-5.5a2.5 2.5 0 000 5h3a2.5 2.5 0 010 5H8',
  gross: 'M5 20V11M12 20V4M19 20v-6',
  exp: 'M3 7h16a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2zM3 7l12-3v3M17 14h2',
  net: 'M3 17l6-6 4 4 8-8M15 7h6v6',
  star: 'M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z',
  bulb: 'M9 18h6M10 21h4M12 3a6 6 0 00-3.5 10.9c.6.5 1 1.2 1 2.1h5c0-.9.4-1.6 1-2.1A6 6 0 0012 3z',
  settings: 'M12 8a4 4 0 100 8 4 4 0 000-8zM19.4 15a1.7 1.7 0 00.3 1.9l.1.1-1.7 2.9-.2-.1a1.7 1.7 0 00-1.9.3l-.1.1h-3.4l-.1-.2a1.7 1.7 0 00-1.7-1l-.2.1-2.9-1.7.1-.2a1.7 1.7 0 00-.3-1.9l-.1-.1v-3.4l.2-.1a1.7 1.7 0 001-1.7l-.1-.2 1.7-2.9.2.1a1.7 1.7 0 001.9-.3l.1-.1h3.4l.1.2a1.7 1.7 0 001.7 1l.2-.1 2.9 1.7-.1.2a1.7 1.7 0 00.3 1.9l.1.1v3.4z',
  box: 'M3 7l9-4 9 4-9 4zM3 7v10l9 4 9-4V7M12 11v10',
  receipt: 'M6 3h12v18l-3-2-3 2-3-2-3 2zM9 8h6M9 12h6',
  upload: 'M12 16V4M7 9l5-5 5 5M4 16v3a2 2 0 002 2h12a2 2 0 002-2v-3',
};
function Ico({ d, s = 22 }) {
  return (
    <svg width={s} height={s} viewBox='0 0 24 24' fill='none' stroke='currentColor' strokeWidth='1.8' strokeLinecap='round' strokeLinejoin='round' aria-hidden='true'><path d={d} /></svg>
  );
}
function Title({ ic, children, right }) {
  return (
    <div className='ct'>
      <span className='nin sm'><Ico d={ic} s={18} /></span>
      <span className='dlab'>{children}</span>
      {right}
    </div>
  );
}
function Ring({ pct, icon }) {
  const C = 2 * Math.PI * 34, p = Math.max(0, Math.min(100, pct));
  return (
    <div className='nring'>
      <svg viewBox='0 0 88 88' aria-hidden='true'>
        <circle cx='44' cy='44' r='34' className='rt' />
        <circle cx='44' cy='44' r='34' className='rf' strokeDasharray={C} strokeDashoffset={C * (1 - p / 100)} transform='rotate(-90 44 44)' />
      </svg>
      <span className='nin'><Ico d={icon} s={22} /></span>
    </div>
  );
}
function Trend({ series, next }) {
  const vals = [...series, next], max = Math.max(...vals, 1) * 1.08;
  const labels = ['Wk 1', 'Wk 2', 'Wk 3', 'Wk 4', 'Next'];
  return (
    <div className='nbars' role='img' aria-label={`Weekly sales ${series.map(money).join(', ')} with a forecast of ${money(next)} for next week`}>
      {vals.map((v, i) => (
        <div className='ncol' key={i}>
          <b>{v >= 1000 ? `${activeCurrency} ${(v / 1000).toFixed(1)}k` : money(v)}</b>
          <div className='ntrack'>
            <i className={i === 4 ? 'fc' : ''} style={{ height: (v / max) * 100 + '%' }} />
          </div>
          <span>{labels[i]}</span>
        </div>
      ))}
    </div>
  );
}

function GoalTrend({ buckets, current, target, label }) {
  const max = Math.max(...buckets.map((b) => b.value), target, 1) * 1.08;
  return (
    <div className={`nbars${buckets.length > 12 ? ' nday' : ''}`} role='img' aria-label={`${label} against a target of ${wholeOrCents(target)}`}>
      {buckets.map((b, i) => (
        <div className='ncol' key={i} title={`${b.name}: ${preciseMoney(b.value)}`}>
          <div className='ntrack'>
            {i <= current && <i style={{ height: (b.value / max) * 100 + '%' }} />}
            <em className='ngoal' style={{ bottom: `calc(4px + (100% - 8px) * ${target / max})` }} />
          </div>
          <span>{b.label}</span>
        </div>
      ))}
    </div>
  );
}

const PRODUCTS = [];
const NAV = [
  ['overview', 'Overview', 'M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z', 'How your business is doing'],
  ['account', 'Account', 'M20 21a8 8 0 00-16 0M12 12a4 4 0 100-8 4 4 0 000 8z', 'Your profile and security'],
  ['settings', 'Settings', IC.settings, 'Manage your preferences'],
  ['team', 'Team', 'M16 21v-2a4 4 0 00-4-4H6a4 4 0 00-4 4v2M9 11a4 4 0 100-8 4 4 0 000 8zM20 8v6M23 11h-6', 'Manage business access'],
  ['sales', 'Sales', IC.receipt, 'Every sale you have recorded'],
  ['products', 'Products', 'M20 12l-8 8-9-9V3h8zM7.5 7.5h.01', 'Prices, margins and what sells most'],
  ['stock', 'Stock', IC.box, 'Stock levels, purchases and suppliers'],
  ['receive', 'Receive stock', 'M12 3v12M7 10l5 5 5-5M4 20h16', 'Record stock coming in'],
  ['slow', 'Slow stock', 'M12 7v5l3 2M21 12a9 9 0 11-3-6.7M21 4v5h-5', 'Stock that has stayed too long'],
  ['expenses', 'Expenses', IC.exp, 'Where your money goes'],
  ['customers', 'Customers', 'M16 20v-1a4 4 0 00-4-4H8a4 4 0 00-4 4v1M10 11a3.5 3.5 0 100-7 3.5 3.5 0 000 7zM20 20v-1a3.5 3.5 0 00-2.5-3.3M16 4.3a3.5 3.5 0 010 6.4', 'Your regulars and their history'],
  ['reports', 'Reports', 'M7 3h8l4 4v14H7zM15 3v4h4M10 12h6M10 16h6', 'Month by month results'],
  ['insights', 'Insights', IC.bulb, 'Forecasts and smart ideas'],
];

const BATCHES0 = [];

// image_url is an API-relative path, so it is resolved against the API base.
const productImage = (path) => (path ? new URL(path + '?size=400', API).href : '');
const businessProfileFromSettings = (settings) => ({
  name: settings.business_name, logo: settings.business_logo_url,
  zoom: settings.business_logo_zoom, x: settings.business_logo_x, y: settings.business_logo_y,
});
function BusinessLogo({ src, alt, zoom, x, y, preview = false }) {
  return (
    <span className={`business-logo-frame${preview ? ' business-logo-preview' : ''}`}>
      <img src={src} alt={alt} style={{ transform: `translate(${x}%, ${y}%) scale(${zoom / 100})` }} />
    </span>
  );
}
function BusinessBrand({ name, logo, zoom, x, y }) {
  return (
    <div className='nlogo'>
      <div>Nexa</div>
      {(name || logo) && <div className='business-brand'>
        {logo && <BusinessLogo src={productImage(logo)} alt='' zoom={zoom} x={x} y={y} />}
        {name && <span>{name}</span>}
      </div>}
    </div>
  );
}
// Maps API rows to the tuple shapes the dashboard keeps in state.
const productRow = (p) => [p.name, p.category, Number(p.price), Number(p.cost), 0, p.target_stock, p.supplier || '', productImage(p.image_url), p.id];
const batchRow = (b) => [b.id, b.product, b.quantity_received, b.quantity_left, b.age_days, Number(b.unit_cost), b.supplier || ''];
const dateLabel = (iso) => {
  if (!iso) return '';
  const d = new Date(iso + 'T00:00:00');
  return d.toLocaleString('en-US', { month: 'short' }) + ' ' + d.getDate();
};
const purchaseRow = (p) => [
  `${p.product} × ${p.quantity}`, p.supplier || '', Math.round(Number(p.total)), p.status,
  dateLabel(p.status === 'Delivered' ? p.delivered_on : p.ordered_on), p.product, p.quantity, p.id,
];

function Dashboard({ setTheme, onExit, workspaces = [], onWorkspaceChange, workspaceNotice }) {
  const [isStaff, setIsStaff] = useState(false);
  const [accountEmail, setAccountEmail] = useState('');
  const [nav, setNav] = useState('overview');
  const [m, setM] = useState(monthName());
  const [scn, setScn] = useState('Expected');
  const [pri, setPri] = useState('All');
  const [done, setDone] = useState({});
  const [dash, setDash] = useState(null);
  const [dashError, setDashError] = useState('');
  const [expenseSummary, setExpenseSummary] = useState({ items: [], by_category: [] });
  const [reportRows, setReportRows] = useState([]);
  const [sales, setSales] = useState([]);
  const [expList, setExpList] = useState([]);
  const [purchases, setPurchases] = useState([]);
  const [form, setForm] = useState(null);
  const [q, setQ] = useState('');
  const [sf, setSf] = useState('All');
  const [sort, setSort] = useState('sold');
  const [openC, setOpenC] = useState(null);
  const [prodList, setProdList] = useState(PRODUCTS);
  const [batches, setBatches] = useState(BATCHES0);
  const [limit, setLimit] = useState(45);
  const [disc, setDisc] = useState({});
  const [rf, setRf] = useState({ p: '__new', q: '', c: '', s: '', name: '', price: '', img: '', imgName: '' });
  const [rmsg, setRmsg] = useState('');
  const [stockMsg, setStockMsg] = useState('');
  const [receiveBusy, setReceiveBusy] = useState(false);
  const receiveLock = useRef(false);
  const imgRef = useRef(null);
  const [assistantQuestion, setAssistantQuestion] = useState('');
  const [assistantMessages, setAssistantMessages] = useState([]);
  const [assistantBusy, setAssistantBusy] = useState(false);
  const [assistantError, setAssistantError] = useState('');
  const assistantLock = useRef(false);
  const [assistantMode, setAssistantMode] = useState('algorithm');
  const [algorithmType, setAlgorithmType] = useState('profitability');
  const [algorithmResult, setAlgorithmResult] = useState(null);
  const [algorithmBusy, setAlgorithmBusy] = useState(false);
  const [algorithmError, setAlgorithmError] = useState('');
  const algorithmLock = useRef(false);
  const orderLock = useRef(false);
  const [goalData, setGoalData] = useState(null);
  const [goalChartData, setGoalChartData] = useState(null);
  const [goalForm, setGoalForm] = useState({ amount: '', period: 'month' });
  const [goalMsg, setGoalMsg] = useState({ text: '', error: false });
  const [goalBusy, setGoalBusy] = useState(false);
  const goalLock = useRef(false);
  const slowLimitOverridden = useRef(false);
  const [preferences, setPreferences] = useState(DEFAULT_PREFERENCES);
  const [businessProfile, setBusinessProfile] = useState({ name: '', logo: '', zoom: 100, x: 0, y: 0 });
  const [pendingLogo, setPendingLogo] = useState(null);
  const [logoError, setLogoError] = useState('');
  const [logoBusy, setLogoBusy] = useState(false);
  const logoInput = useRef(null);
  const logoSelection = useRef(0);
  const [settingsBusy, setSettingsBusy] = useState(false);
  const [settingsMsg, setSettingsMsg] = useState({ text: '', error: false });
  const [themeBusy, setThemeBusy] = useState(false);
  const [themeMsg, setThemeMsg] = useState({ text: '', error: false });
  const [accountMsg, setAccountMsg] = useState({ text: '', error: false });
  const figureLoadSequence = useRef(0);
  const activeWorkspace = workspaces.find((item) => String(item.id) === selectedWorkspace()) || workspaces[0];
  const canAccess = (scope) => activeWorkspace?.role === 'owner' || !!activeWorkspace?.permissions?.[scope]?.view;
  const canEdit = (scope) => activeWorkspace?.role === 'owner' || !!activeWorkspace?.permissions?.[scope]?.edit;

  useEffect(() => {
    currentUser(localStorage.getItem(TOKEN_KEY)).then((u) => {
      setIsStaff(!!u.is_staff);
      setAccountEmail(u.email || '');
    }).catch(() => {});
  }, []);

  useEffect(() => {
    if (!canAccess('inventory')) return;
    const token = localStorage.getItem(TOKEN_KEY);
    Promise.all([listProducts(token), listBatches(token), listPurchases(token)])
      .then(([productList, batchList, orderList]) => {
        setProdList(productList.map(productRow));
        setBatches(batchList.map(batchRow));
        setPurchases(orderList.map(purchaseRow));
      })
      .catch((error) => setStockMsg(error.message));
  }, []);

  const loadFigures = () => {
    const token = localStorage.getItem(TOKEN_KEY);
    const month = currentMonthKey();
    const sequence = ++figureLoadSequence.current;
    const requests = [];
    if (canAccess('dashboard')) requests.push(
      getDashboard(month, token).then((figures) => {
        if (sequence === figureLoadSequence.current) { setDash(figures); setDashError(''); }
      }).catch((error) => { if (sequence === figureLoadSequence.current) setDashError(error.message); }),
    );
    if (canAccess('expenses')) requests.push(
      listExpenses(month, token).then((expenses) => {
        if (sequence === figureLoadSequence.current) {
          setExpenseSummary(expenses);
          setExpList(expenses.items.map((e) => [e.category, toNum(e.amount), shortDate(e.date)]));
        }
      }).catch((error) => { if (sequence === figureLoadSequence.current) setDashError(error.message); }),
    );
    if (canAccess('sales')) requests.push(
      listSales(token).then((saleList) => {
        if (sequence === figureLoadSequence.current) setSales(saleList.map((s) => [s.customer, toNum(s.amount), s.status, shortDate(s.date), s.product || '', s.product ? s.quantity : 0]));
      }).catch((error) => { if (sequence === figureLoadSequence.current) setDashError(error.message); }),
    );
    if (canAccess('reports')) requests.push(
      getReports(token).then((reports) => {
        if (sequence === figureLoadSequence.current) setReportRows(reports);
      }).catch((error) => { if (sequence === figureLoadSequence.current) setDashError(error.message); }),
    );
    return Promise.all(requests);
  };
  useEffect(() => { loadFigures(); }, []);

  const applyGoal = (data) => {
    setGoalData(data);
    setGoalForm({ amount: data.revenue_goal == null ? '' : String(Number(data.revenue_goal)), period: data.goal_period });
    setPreferences((current) => ({ ...current, ...data }));
    setBusinessProfile(businessProfileFromSettings(data));
    activeCurrency = data.currency || activeCurrency;
    const timeZoneChanged = data.time_zone && data.time_zone !== activeTimeZone;
    activeTimeZone = data.time_zone || activeTimeZone;
    setM(monthName());
    setTheme(data.theme === 'dark');
    if (!slowLimitOverridden.current) setLimit(data.slow_stock_days || 45);
    if (timeZoneChanged) loadFigures();
  };
  const persistGoal = async (body, okText) => {
    if (goalLock.current) return;
    goalLock.current = true;
    setGoalBusy(true);
    setGoalMsg({ text: '', error: false });
    try {
      await updateSettings(body, localStorage.getItem(TOKEN_KEY));
      await loadGoal();
      setGoalMsg({ text: okText, error: false });
    } catch (error) {
      setGoalMsg({ text: error.message, error: true });
    } finally {
      goalLock.current = false;
      setGoalBusy(false);
    }
  };
  const saveGoal = (e) => {
    e.preventDefault();
    const amount = parseFloat(goalForm.amount);
    if (!(amount > 0)) return setGoalMsg({ text: 'Enter a sales goal above zero.', error: true });
    persistGoal({ revenue_goal: amount, goal_period: goalForm.period }, `Goal saved: ${preciseMoney(amount)} per ${goalForm.period}.`);
  };
  const clearGoal = () => persistGoal({ revenue_goal: null }, 'Revenue goal cleared.');

  const pickBusinessLogo = async (event) => {
    const input = event.target;
    const file = input.files && input.files[0];
    if (!file) return;
    const selection = ++logoSelection.current;
    setLogoError('');
    setLogoBusy(true);
    try {
      const image = await shrinkImage(file);
      if (selection === logoSelection.current) setPendingLogo(image);
    } catch (error) {
      if (selection === logoSelection.current) {
        input.value = '';
        setLogoError(error.message);
      }
    } finally {
      if (selection === logoSelection.current) setLogoBusy(false);
    }
  };

  const saveTheme = async (event) => {
    const theme = event.target.value;
    const previousTheme = preferences.theme;
    setPreferences((current) => ({ ...current, theme }));
    setTheme(theme === 'dark');
    setThemeBusy(true);
    setThemeMsg({ text: '', error: false });
    try {
      const saved = await updateSettings({ theme }, localStorage.getItem(TOKEN_KEY));
      setPreferences((current) => ({ ...current, theme: saved.theme }));
      setTheme(saved.theme === 'dark');
      setThemeMsg({ text: 'Theme saved.', error: false });
    } catch (error) {
      setPreferences((current) => ({ ...current, theme: previousTheme }));
      setTheme(previousTheme === 'dark');
      setThemeMsg({ text: error.message, error: true });
    } finally {
      setThemeBusy(false);
    }
  };

  const savePreferences = async (event) => {
    event.preventDefault();
    if (logoBusy) return;
    const currencyChanged = preferences.currency !== activeCurrency;
    if (currencyChanged && !window.confirm(
      'Changing the currency does not convert any previously recorded amounts. It only changes how the same numbers are labeled. Continue?',
    )) return;
    setSettingsBusy(true);
    setSettingsMsg({ text: '', error: false });
    try {
      const body = {
        currency: preferences.currency,
        confirm_currency_change: currencyChanged,
        time_zone: preferences.time_zone,
        business_name: preferences.business_name,
        business_logo_zoom: preferences.business_logo_zoom,
        business_logo_x: preferences.business_logo_x,
        business_logo_y: preferences.business_logo_y,
        business_email: preferences.business_email,
        business_phone: preferences.business_phone,
        low_stock_threshold: preferences.low_stock_threshold,
        slow_stock_days: preferences.slow_stock_days,
        reorder_lead_days: preferences.reorder_lead_days,
        safety_stock_days: preferences.safety_stock_days,
        reorder_target_days: preferences.reorder_target_days,
        notify_low_stock: preferences.notify_low_stock,
        notify_slow_stock: preferences.notify_slow_stock,
        notify_goal_reached: preferences.notify_goal_reached,
      };
      if (pendingLogo !== null) body.business_logo = pendingLogo;
      const saved = await updateSettings(body, localStorage.getItem(TOKEN_KEY));
      setPreferences((current) => ({ ...current, ...saved, theme: current.theme }));
      setBusinessProfile(businessProfileFromSettings(saved));
      setPendingLogo(null);
      if (logoInput.current) logoInput.current.value = '';
      activeCurrency = saved.currency;
      const timeZoneChanged = saved.time_zone !== activeTimeZone;
      activeTimeZone = saved.time_zone;
      setM(monthName());
      if (!slowLimitOverridden.current) setLimit(saved.slow_stock_days);
      if (timeZoneChanged) await loadFigures();
      setSettingsMsg({ text: 'Settings saved.', error: false });
    } catch (error) {
      setSettingsMsg({ text: error.message, error: true });
    } finally {
      setSettingsBusy(false);
    }
  };

  const sendEmailVerification = async () => {
    setSettingsBusy(true);
    setSettingsMsg({ text: '', error: false });
    try {
      const result = await verifySettingsEmail(localStorage.getItem(TOKEN_KEY));
      setSettingsMsg({ text: result.message, error: false });
    } catch (error) {
      setSettingsMsg({ text: error.message, error: true });
    } finally {
      setSettingsBusy(false);
    }
  };

  const requestConfirmation = async (action) => {
    setSettingsBusy(true);
    setAccountMsg({ text: '', error: false });
    try {
      const result = await requestAccountConfirmation(action, localStorage.getItem(TOKEN_KEY));
      setAccountMsg({ text: result.message + ' Open the link in that email to continue.', error: false });
    } catch (error) {
      setAccountMsg({ text: error.message, error: true });
    } finally {
      setSettingsBusy(false);
    }
  };

  const loadGoal = () => Promise.all([
    getSettings(localStorage.getItem(TOKEN_KEY)),
    getGoalSeries(localStorage.getItem(TOKEN_KEY)),
  ]).then(([settings, series]) => {
    applyGoal(settings);
    setGoalChartData(series);
  });
  useEffect(() => {
    if ((nav !== 'settings' && nav !== 'overview') || !canAccess('settings')) return;
    loadGoal().catch((error) => {
      if (nav === 'settings') setGoalMsg({ text: error.message, error: true });
    });
  }, [nav]);

  const D = dash || {};
  const rev = toNum(D.revenue), exp = toNum(D.expenses), gross = toNum(D.gross_profit), net = toNum(D.net_profit);
  const change = (key) => {
    if (!dash) return 'Loading figures';
    const v = D.change_vs_previous_pct[key];
    return v == null ? `No ${monthName(-1)} figures to compare` : `${v >= 0 ? '+' : ''}${Number(v).toFixed(1)}% vs ${monthName(-1)}`;
  };
  const series = (D.weekly_sales || [0, 0, 0, 0]).map(toNum);
  const goalSeries = goalChartData ? goalChart(goalChartData) : null;
  const fc = (D.forecast && D.forecast[scn]) || { next_week: 0, next_month: 0 };
  const factor = SC[scn];
  const nextWeek = Math.round(toNum(fc.next_week)), nextTotal = Math.round(toNum(fc.next_month));
  const top = (D.top_products || []).map((p) => [p.name, toNum(p.units)]);
  const maxUnits = top.length ? top[0][1] : 1;
  const cats = (expenseSummary.by_category || []).map((c) => [c.category, toNum(c.total)]);
  const maxCat = Math.max(...cats.map((c) => c[1]), 1);
  const pendingCount = toNum(D.pending_payments && D.pending_payments.count);
  const pendingTotal = toNum(D.pending_payments && D.pending_payments.total);
  const recs = RECS.filter((r) => pri === 'All' || r.pri === pri);
  const sold = Object.fromEntries(top);
  const stockOf = (n) => batches.filter((b) => b[1] === n).reduce((a, b) => a + b[3], 0);
  const ordered = Object.fromEntries(purchases.filter((x) => x[3] === 'Ordered').map((x) => [x[5], true]));
  const prods = prodList.map((p) => [p[0], p[1], p[2], p[3], stockOf(p[0]), p[5], p[6], p[7] || '', p[8]]);
  const low = prods.filter((p) => p[5] > 0 && p[4] / p[5] < Number(preferences.low_stock_threshold) && !ordered[p[0]]);
  const slow = batches.filter((b) => b[3] > 0 && b[4] > limit).sort((a, b) => b[4] - a[4]);
  const pend = sales.filter((s) => s[2] === 'Pending');

  const save = async ({ who, a, st, product, qty }) => {
    const token = localStorage.getItem(TOKEN_KEY);
    if (form === 'sale') {
      const body = { customer: who, amount: a, status: st };
      if (product) Object.assign(body, { product_id: product[8], quantity: qty });
      await createSale(body, token);
      loadFigures();
      loadGoal().catch(() => {});
      if (product) await refreshStock();
    } else {
      await createExpense({ category: who, amount: a }, token);
      loadFigures();
    }
    setM(monthName()); setForm(null);
  };
  const askAssistant = async (event) => {
    event.preventDefault();
    const question = assistantQuestion.trim();
    if (!question || assistantLock.current) return;
    assistantLock.current = true;
    setAssistantQuestion('');
    setAssistantError('');
    setAssistantMessages((messages) => [...messages, { role: 'user', text: question }]);
    setAssistantBusy(true);
    try {
      const month = currentMonthKey();
      const result = await chat({ question, month }, localStorage.getItem(TOKEN_KEY));
      setAssistantMessages((messages) => [...messages, { role: 'assistant', text: result.answer }]);
    } catch (error) {
      setAssistantError(error.message);
    } finally {
      assistantLock.current = false;
      setAssistantBusy(false);
    }
  };
  const runAlgorithm = async () => {
    if (algorithmLock.current) return;
    algorithmLock.current = true;
    setAlgorithmBusy(true);
    setAlgorithmError('');
    setAlgorithmResult(null);
    try {
      const month = currentMonthKey();
      const result = await analyze({ analysis: algorithmType, month }, localStorage.getItem(TOKEN_KEY));
      setAlgorithmResult(result);
    } catch (error) {
      setAlgorithmError(error.message);
    } finally {
      algorithmLock.current = false;
      setAlgorithmBusy(false);
    }
  };
  const refreshStock = async () => {
    const token = localStorage.getItem(TOKEN_KEY);
    try {
      const [batchList, orderList] = await Promise.all([listBatches(token), listPurchases(token)]);
      setBatches(batchList.map(batchRow));
      setPurchases(orderList.map(purchaseRow));
    } catch (error) {
      setStockMsg(error.message);
    }
  };
  const reorder = async (p) => {
    if (orderLock.current) return;
    orderLock.current = true;
    try {
      await createPurchase({ product_id: p[8], quantity: Math.max(1, p[5] - p[4]), unit_cost: p[3] }, localStorage.getItem(TOKEN_KEY));
      setStockMsg('');
      await refreshStock();
    } catch (error) {
      setStockMsg(error.message);
    } finally {
      orderLock.current = false;
    }
  };
  const receiveOrder = async (i) => {
    const pu = purchases[i];
    if (orderLock.current) return;
    orderLock.current = true;
    try {
      await receivePurchase(pu[7], localStorage.getItem(TOKEN_KEY));
      await refreshStock();
      setRmsg(`${pu[6]} × ${pu[5]} received into stock.`);
    } catch (error) {
      setRmsg(error.message);
    } finally {
      orderLock.current = false;
    }
  };
  const submitReceive = async (e) => {
    e.preventDefault();
    if (receiveLock.current) return;
    const qty = parseInt(rf.q, 10), cost = parseFloat(rf.c), price = parseFloat(rf.price);
    if (!(qty > 0) || !(cost > 0)) return setRmsg('Enter a quantity and a unit cost above zero.');
    if (!rf.s.trim()) return setRmsg('Enter the supplier name.');
    const supplier = rf.s.trim();
    const isNew = rf.p === '__new';
    const existing = isNew ? null : prodList.find((p) => p[0] === rf.p);
    if (!isNew && !existing) return setRmsg('Choose a product from the list.');
    let name = rf.p;
    const body = { quantity: qty, unit_cost: cost, supplier };
    if (isNew) {
      name = rf.name.trim();
      if (!name) return setRmsg('Give the new product a name.');
      const match = prodList.find((p) => p[0].toLowerCase() === name.toLowerCase());
      if (match) {
        name = match[0];
        body.product_id = match[8];
      } else {
        if (!(price > 0)) return setRmsg('Give the new product a selling price.');
        Object.assign(body, { new_product_name: name, price });
      }
    } else {
      body.product_id = existing[8];
    }
    if (rf.img) body.image = rf.img;
    receiveLock.current = true;
    setReceiveBusy(true);
    try {
      const { product } = await receiveStock(body, localStorage.getItem(TOKEN_KEY));
      setProdList((l) => (l.some((p) => p[8] === product.id) ? l.map((p) => (p[8] === product.id ? productRow(product) : p)) : [...l, productRow(product)]));
      await refreshStock();
      setRf({ p: '__new', q: '', c: '', s: '', name: '', price: '', img: '', imgName: '' });
      if (imgRef.current) imgRef.current.value = '';
      setRmsg(`${qty} × ${name} added to stock.`);
    } catch (error) {
      setRmsg(error.message);
    } finally {
      receiveLock.current = false;
      setReceiveBusy(false);
    }
  };
  const pc = (a) => (rev > 0 ? (a / rev) * 100 : 0);
  const goalProgress = goalData && goalData.progress;
  const goalPct = goalProgress ? goalProgress.percent : null;
  const goalCap = goalProgress
    ? `of the ${money(Number(goalProgress.goal))} goal ${GOAL_WORDS[goalProgress.period]}`
    : 'Set a revenue goal in Settings';
  const kpis = [
    ['Revenue', rev, change('revenue'), goalPct, IC.rev, goalCap],
    ['Gross profit', gross, change('gross_profit'), pc(gross), IC.gross, 'margin'],
    ['Expenses', exp, change('expenses'), pc(exp), IC.exp, 'of revenue'],
    ['Net profit', net, change('net_profit'), pc(net), IC.net, 'margin'],
  ];
  const Month = () => (
    <div className='nseg' role='group' aria-label='Month'>
      {[monthName()].map((x) => <button key={x} aria-pressed={m === x} onClick={() => setM(x)}>{x}</button>)}
    </div>
  );
  const Bar = ({ pct }) => <div className='dbar thin'><i style={{ width: Math.min(100, pct) + '%' }} /></div>;

  const views = {
    overview: () => (
      <>
        {dashError && <p className='nerr' role='alert'>{dashError}</p>}
        <div className='kpis'>
          {kpis.map(([l, v, d, p, ic, cap]) => (
            <div className='kpi flat metric' key={l}>
              <div className='kpi-head'><span className='dlab'>{l}</span><Ring pct={p} icon={ic} /></div>
              <b>{money(v)}</b>
              <small>{p == null ? cap : `${Math.round(Math.max(0, Math.min(999, p)))}% ${cap}`}</small><small className='kd'>{d}</small>
            </div>
          ))}
        </div>
        <div className='dgrid'>
          <section className='dc span2'>
            {goalSeries == null ? (
              <>
                <Title ic={IC.gross} right={<span className='nleg'><i />Actual<i className='fc' />Forecast</span>}>Sales by week, {m}</Title>
                <Trend series={series} next={nextWeek} key={m + scn + rev} />
              </>
            ) : (
              <>
                <Title ic={IC.gross} right={<span className='nleg'><i />{goalSeries.actual}<i className='gl' />{goalSeries.targetText}</span>}>{goalSeries.heading}</Title>
                <GoalTrend key={goalData.goal_period} buckets={goalSeries.buckets} current={goalSeries.current} target={goalSeries.target} label={goalSeries.heading} />
              </>
            )}
          </section>
          <section className='dc'>
            <Title ic={IC.star}>Best sellers, {m}</Title>
            <ol className='nlist'>
              {top.length === 0 && <li><p>No sales recorded yet.</p></li>}
              {top.slice(0, 4).map(([n, u], i) => (
                <li key={n}><div className='nrow2'><span>{n}{i === 0 && <em className='ntag'>Top seller</em>}</span><span>{u} sold</span></div>
                  <div className='dbar'><i style={{ width: (u / maxUnits) * 100 + '%' }} /></div></li>
              ))}
            </ol>
          </section>
          {[
            ['stock', IC.box, 'Needs attention', `${low.length} low on stock and ${slow.length} batch${slow.length === 1 ? '' : 'es'} sitting longer than ${limit} days.`, 'Open stock'],
            ['sales', IC.receipt, 'Waiting on payment', `${pendingCount} sale${pendingCount === 1 ? '' : 's'} pending, worth ${money(pendingTotal)}.`, 'Open sales'],
            ['insights', IC.bulb, 'Top idea', RECS.length ? RECS[0].text : 'Ideas will appear once you have recorded some activity.', 'See all ideas'],
          ].map(([id, ic, t, txt, btn]) => (
            <section className='dc' key={id}>
              <Title ic={ic}>{t}</Title><p>{txt}</p>
              <button className='dmini self' onClick={() => setNav(id)}>{btn}</button>
            </section>
          ))}
        </div>
      </>
    ),

    account: () => (
      <AccountSettings onEmailChange={setAccountEmail} onSignOut={onExit} />
    ),

    settings: () => (
      <>
        <div className='settings-intro'><div><span className='account-kicker'>PERSONALISE NEXA</span>
          <h2>Settings that fit your business</h2><p>Manage your account, preferences and business details.</p></div></div>
        <nav className='settings-categories' aria-label='Settings categories'>
          <button type='button' onClick={() => setNav('account')}>Account</button>
          {(activeWorkspace?.role === 'owner' || activeWorkspace?.can_manage_members) && <button type='button' onClick={() => setNav('team')}>Team sharing</button>}
          <a href='#settings-appearance'>Appearance</a>
          <a href='#settings-business'>Business</a>
          <a href='#settings-inventory'>Inventory</a>
          <a href='#settings-notifications'>Notifications</a>
          <a href='#settings-goals'>Goals</a>
          <a href='#settings-account'>Account &amp; data</a>
        </nav>
        <form className='dgrid settings-form' onSubmit={savePreferences}>
          <fieldset className='permission-locked' disabled={!canEdit('settings')}>
          <h2 className='settings-heading span3' id='settings-appearance'>Appearance</h2>
          <section className='dc'>
            <div className='theme-compact'>
              <div>
                <label htmlFor='theme-select' className='theme-label'>Theme</label>
                <p className='theme-desc'>Changes save immediately</p>
              </div>
              <select id='theme-select' className='theme-select' value={preferences.theme} onChange={saveTheme} disabled={themeBusy}>
                <option value='light'>Light</option><option value='dark'>Dark</option>
              </select>
            </div>
            {themeMsg.text && <p className={themeMsg.error ? 'nerr' : 'nok'} role={themeMsg.error ? 'alert' : 'status'}>{themeMsg.text}</p>}
          </section>
          <h2 className='settings-heading span3' id='settings-business'>Business</h2>
          <section className='dc'>
            <Title ic={IC.gross}>Business profile</Title>
            <label>Business name<input maxLength='120' value={preferences.business_name} onChange={(e) => setPreferences((p) => ({ ...p, business_name: e.target.value }))} /></label>
            <label>Company logo
              <input ref={logoInput} type='file' accept='image/png,image/jpeg,image/webp,image/gif' disabled={settingsBusy || logoBusy} onChange={pickBusinessLogo} />
            </label>
            <p>PNG, JPEG, WebP or GIF. Save settings to apply your logo.</p>
            {(pendingLogo || (pendingLogo === null && businessProfile.logo)) && <>
              <BusinessLogo preview src={pendingLogo === null ? productImage(businessProfile.logo) : pendingLogo}
                alt='Company logo preview' zoom={preferences.business_logo_zoom} x={preferences.business_logo_x} y={preferences.business_logo_y} />
              <label>Logo zoom: {preferences.business_logo_zoom}%
                <input type='range' min='100' max='300' step='5' value={preferences.business_logo_zoom}
                  onChange={(e) => setPreferences((p) => ({ ...p, business_logo_zoom: Number(e.target.value) }))} />
              </label>
              <label>Logo horizontal position: {preferences.business_logo_x}%
                <input type='range' min='-100' max='100' value={preferences.business_logo_x}
                  onChange={(e) => setPreferences((p) => ({ ...p, business_logo_x: Number(e.target.value) }))} />
              </label>
              <label>Logo vertical position: {preferences.business_logo_y}%
                <input type='range' min='-100' max='100' value={preferences.business_logo_y}
                  onChange={(e) => setPreferences((p) => ({ ...p, business_logo_y: Number(e.target.value) }))} />
              </label>
              <p>Positive values move the image right or down. Save settings to apply on desktop and mobile.</p>
              <button type='button' className='btn glass' disabled={settingsBusy || logoBusy} onClick={() =>
                setPreferences((p) => ({ ...p, business_logo_zoom: 100, business_logo_x: 0, business_logo_y: 0 }))
              }>Reset logo position</button>
              <button type='button' className='btn glass' disabled={settingsBusy || logoBusy} onClick={() => {
                logoSelection.current++;
                setPendingLogo('');
                setLogoError('');
                if (logoInput.current) logoInput.current.value = '';
              }}>Remove logo</button>
            </>}
            {logoError && <p className='nerr' role='alert'>{logoError}</p>}
            <label>Contact email<input type='email' maxLength='254' value={preferences.business_email} onChange={(e) => setPreferences((p) => ({ ...p, business_email: e.target.value }))} /></label>
            <label>Contact phone<input type='tel' maxLength='32' value={preferences.business_phone} onChange={(e) => setPreferences((p) => ({ ...p, business_phone: e.target.value }))} /></label>
          </section>
          <section className='dc'>
            <Title ic={IC.receipt}>Currency and time zone</Title>
            <label>Display currency
              <select value={preferences.currency} onChange={(e) => setPreferences((p) => ({ ...p, currency: e.target.value }))}>
                {CURRENCIES.map((code) => <option key={code} value={code}>{code}</option>)}
              </select>
            </label>
            <p>Currency changes only relabel existing amounts; no exchange-rate conversion is performed.</p>
            <label>Time zone
              <select value={preferences.time_zone} onChange={(e) => setPreferences((p) => ({ ...p, time_zone: e.target.value }))}>
                {!TIME_ZONES.includes(preferences.time_zone) && <option value={preferences.time_zone}>{preferences.time_zone}</option>}
                {TIME_ZONES.map((zone) => <option key={zone} value={zone}>{zone.replace(/_/g, ' ')}</option>)}
              </select>
            </label>
          </section>
          <h2 className='settings-heading span3' id='settings-inventory'>Inventory</h2>
          <section className='dc span3'>
            <Title ic={IC.box}>Inventory thresholds</Title>
            <label>Low-stock alert when stock is below target (%)
              <input type='number' min='1' max='100' step='1' value={Math.round(Number(preferences.low_stock_threshold) * 100)} onChange={(e) => setPreferences((p) => ({ ...p, low_stock_threshold: String(Number(e.target.value) / 100) }))} />
            </label>
            <label>Aged-stock threshold (days)
              <input type='number' min='1' max='3650' step='1' value={preferences.slow_stock_days} onChange={(e) => setPreferences((p) => ({ ...p, slow_stock_days: e.target.value }))} />
            </label>
            <label>Supplier lead time (days)
              <input type='number' min='1' max='365' step='1' value={preferences.reorder_lead_days} onChange={(e) => setPreferences((p) => ({ ...p, reorder_lead_days: e.target.value }))} />
            </label>
            <label>Safety stock buffer (days)
              <input type='number' min='1' max='365' step='1' value={preferences.safety_stock_days} onChange={(e) => setPreferences((p) => ({ ...p, safety_stock_days: e.target.value }))} />
            </label>
            <label>Reorder target cover (days)
              <input type='number' min='1' max='365' step='1' value={preferences.reorder_target_days} onChange={(e) => setPreferences((p) => ({ ...p, reorder_target_days: e.target.value }))} />
            </label>
          </section>
          <h2 className='settings-heading span3' id='settings-notifications'>Notifications</h2>
          <section className='dc span3'>
            <Title ic={IC.bulb}>Email alerts</Title>
            <p>Alerts are sent immediately when a condition is first met. Aged-stock alerts are detected on your next Nexa request after the age threshold.</p>
            <p>{preferences.email_verified ? `Alerts go to ${accountEmail || 'your verified account email'}.` : `Verify ${accountEmail || 'your account email'} before enabling alerts.`}</p>
            {!preferences.email_verified && <button type='button' className='btn glass' disabled={settingsBusy} onClick={sendEmailVerification}>Send verification email</button>}
            {!preferences.email_delivery_configured && <p className='nerr'>Secure email delivery is not configured on this server. Alerts remain unavailable until SMTP is configured.</p>}
            {[
              ['notify_low_stock', 'Low stock'],
              ['notify_slow_stock', 'Aged stock'],
              ['notify_goal_reached', 'Revenue goal reached'],
            ].map(([field, label]) => (
              <label className='ncheck' key={field}>
                <input type='checkbox' checked={preferences[field]} onChange={(e) => setPreferences((p) => ({ ...p, [field]: e.target.checked }))} />
                {label}
              </label>
            ))}
          </section>
          <div className='goal-actions span2'>
            <button type='submit' className='btn iri nbtn' disabled={settingsBusy || logoBusy}>{settingsBusy ? 'Saving…' : 'Save settings'}</button>
            {settingsMsg.text && <p className={settingsMsg.error ? 'nerr' : 'nok'} role={settingsMsg.error ? 'alert' : 'status'}>{settingsMsg.text}</p>}
          </div>
          </fieldset>
        </form>
        <div className='settings-sections'>
          <h2 className='settings-heading' id='settings-goals'>Goals</h2>
          <section className='dc'>
            <Title ic={IC.gross}>Revenue goal</Title>
            <p>Progress counts only paid sales in the selected period.</p>
            <form className='nform' onSubmit={saveGoal}>
              <fieldset className='permission-locked' disabled={!canEdit('settings')}>
              <label>Sales goal ({preferences.currency})
                <input type='number' min='0' step='0.01' value={goalForm.amount} onChange={(e) => setGoalForm((f) => ({ ...f, amount: e.target.value }))} />
              </label>
              <div className='goal-period'>
                <span>Goal period</span>
                <div className='nseg' role='group' aria-label='Goal period'>
                  {GOAL_PERIODS.map(([v, label]) => (
                    <button key={v} type='button' aria-pressed={goalForm.period === v} onClick={() => setGoalForm((f) => ({ ...f, period: v }))}>{label}</button>
                  ))}
                </div>
              </div>
              <div className='goal-actions'>
                <button type='submit' className='btn iri nbtn' disabled={goalBusy}>{goalBusy ? 'Saving…' : 'Save goal'}</button>
                <button type='button' className='btn glass' disabled={goalBusy || !goalData || goalData.revenue_goal == null} onClick={clearGoal}>Clear goal</button>
              </div>
              </fieldset>
            </form>
            {goalMsg.text && <p className={goalMsg.error ? 'nerr' : 'nok'} role={goalMsg.error ? 'alert' : 'status'}>{goalMsg.text}</p>}
            {goalData && goalData.progress && (
              <div className='goal-progress'>
                <div className='nrow2'>
                  <span>{preciseMoney(Number(goalData.progress.revenue))} of {preciseMoney(Number(goalData.progress.goal))} {GOAL_WORDS[goalData.progress.period]}</span>
                  <span>{goalData.progress.percent}%</span>
                </div>
                <Bar pct={goalData.progress.percent} />
                <p>{Number(goalData.progress.remaining) > 0 ? `${preciseMoney(Number(goalData.progress.remaining))} left to reach the goal.` : 'Goal reached.'} Period: {shortDate(goalData.progress.start)} to {shortDate(goalData.progress.end)}.</p>
              </div>
            )}
          </section>
          <h2 className='settings-heading' id='settings-account'>Account &amp; data</h2>
          <section className='dc'>
            <Title ic={IC.settings}>Account and data</Title>
            <p>CSV export and account deletion require a one-time email confirmation. Deletion permanently removes your account and its associated business data.</p>
            <div className='goal-actions'>
              <button type='button' className='btn glass' disabled={settingsBusy || !preferences.email_verified || !preferences.email_delivery_configured} onClick={() => requestConfirmation('export')}>Request CSV export</button>
              <button type='button' className='btn glass' disabled={settingsBusy || !preferences.email_verified || !preferences.email_delivery_configured} onClick={() => requestConfirmation('delete')}>Request account deletion</button>
            </div>
            {(!preferences.email_verified || !preferences.email_delivery_configured) && <p>Verify your account email and configure secure email delivery to use these actions.</p>}
            {accountMsg.text && <p className={accountMsg.error ? 'nerr' : 'nok'} role={accountMsg.error ? 'alert' : 'status'}>{accountMsg.text}</p>}
          </section>
        </div>
      </>
    ),

    team: () => <TeamSettings workspace={workspaces.find((item) => String(item.id) === selectedWorkspace()) || workspaces[0]} />,

    sales: () => {
      const list = sales.filter((s) => (sf === 'All' || s[2] === sf) && s[0].toLowerCase().includes(q.toLowerCase()));
      const paid = sales.filter((s) => s[2] === 'Paid').reduce((a, s) => a + s[1], 0);
      const pendAmt = pend.reduce((a, s) => a + s[1], 0);
      return (
        <>
          <div className='kpis three'>
            {[['Paid', money(paid), 'received so far'], ['Pending', money(pendAmt), `${pend.length} sales waiting`], ['Records', sales.length, 'sales logged']].map(([l, v, s]) => (
              <div className='kpi flat' key={l}><span className='dlab'>{l}</span><b>{v}</b><small>{s}</small></div>
            ))}
          </div>
          <section className='dc'>
            <div className='ct'>
              <input className='nsearch' placeholder='Search customer' value={q} onChange={(e) => setQ(e.target.value)} aria-label='Search sales by customer' />
              <div className='nseg sm' role='group' aria-label='Filter by status'>
                {['All', 'Paid', 'Pending'].map((f) => <button key={f} aria-pressed={sf === f} onClick={() => setSf(f)}>{f}</button>)}
              </div>
            </div>
            {list.length === 0 && <p>No sales match your search.</p>}
            {list.map(([w, a, s, d, p, q], i) => (
              <div className='npill' key={w + i + d}>
                <span className='nin xs'>{w[0]}</span><span>{w}</span><span className='nmut'>{p ? `${d} · ${p} × ${q}` : d}</span><b>{money(a)}</b>
                <span className={'chipS ' + (s === 'Paid' ? 'paid' : 'pend')}>{s}</span>
              </div>
            ))}
          </section>
        </>
      );
    },

    products: () => {
      const rows = prods.map(([n, c, p, k, s, t, sup]) => ({ n, c, p, k, s, t, sold: sold[n] || 0, mg: p > 0 ? ((p - k) / p) * 100 : 0 }))
        .filter((r) => r.n.toLowerCase().includes(q.toLowerCase()))
        .sort((a, b) => (sort === 'name' ? a.n.localeCompare(b.n) : sort === 'margin' ? b.mg - a.mg : sort === 'stock' ? a.s - b.s : b.sold - a.sold));
      const H = ({ k, children }) => <button aria-pressed={sort === k} onClick={() => setSort(k)}>{children}</button>;
      return (
        <section className='dc'>
          <div className='ct'><input className='nsearch' placeholder='Search products' value={q} onChange={(e) => setQ(e.target.value)} aria-label='Search products' />
            <span className='nmut ml'>Sorted by {sort}</span></div>
          <div className='nscroll'><div className='ntable'>
            <div className='nth'><H k='name'>Product</H><span>Category</span><span>Price</span><span>Cost</span><H k='margin'>Margin</H><H k='stock'>Stock</H><H k='sold'>Sold, {m}</H></div>
            {rows.map((r) => (
              <div className='ntr' key={r.n}>
                <b>{r.n}</b><span>{r.c}</span><span>{money(r.p)}</span><span>{preciseMoney(r.k)}</span>
                <span className='ncy'>{r.mg.toFixed(0)}%</span><span className={r.s / r.t < Number(preferences.low_stock_threshold) ? 'nwarn' : ''}>{r.s}</span><span>{r.sold}</span>
              </div>
            ))}
          </div></div>
        </section>
      );
    },

    stock: () => (
      <div className='dgrid'>
        <section className='dc span2'>
          <Title ic={IC.box}>Stock levels</Title>
          {stockMsg && <p className='nerr' role='alert'>{stockMsg}</p>}
          {prods.length === 0 && !stockMsg && <p>No products yet. Add one on the Receive stock page.</p>}
          {prods.map((p) => (
            <div className='nstock row' key={p[0]}>
              {p[7] ? <img className='pimg' src={p[7]} alt={p[0]} /> : <span className='nin'>{p[0][0]}</span>}
              <div className='grow'><div className='nrow2'><span>{p[0]}</span><span>{p[4]} of {p[5]}</span></div><Bar pct={(p[4] / p[5]) * 100} /></div>
              <button className='dmini' disabled={!canEdit('inventory') || ordered[p[0]]} onClick={() => reorder(p)}>{ordered[p[0]] ? 'Ordered ✓' : 'Reorder'}</button>
            </div>
          ))}
        </section>
        <section className='dc'>
          <Title ic={IC.star}>Suppliers</Title>
          {[...new Set(batches.map((b) => b[6]))].map((n) => <div className='npill col' key={n}><b className='l'>{n}</b></div>)}
          {batches.length === 0 && !stockMsg && <p>No suppliers yet.</p>}
        </section>
        <section className='dc span3'>
          <Title ic={IC.receipt}>Purchases</Title>
          {purchases.length === 0 && !stockMsg && <p>No purchases yet.</p>}
          {purchases.map(([it, sup, c, st, d], i) => (
            <div className='npill' key={it + i}><span className='nin xs'>{sup.slice(-1)}</span><span>{it}</span><span className='nmut'>{sup} · {d}</span><b>{money(c)}</b>
              <span className={'chipS ' + (st === 'Delivered' ? 'paid' : 'pend')}>{st}</span></div>
          ))}
        </section>
      </div>
    ),

    receive: () => {
      const orders = purchases.map((x, i) => [x, i]).filter(([x]) => x[3] === 'Ordered');
      const recent = [...batches].sort((a, b) => a[4] - b[4]).slice(0, 6);
      const isNew = rf.p === '__new';
      const set = (k) => (e) => setRf({ ...rf, [k]: e.target.value });
      const current = isNew ? null : prodList.find((p) => p[0] === rf.p);
      const preview = rf.img || (current && current[7]) || '';
      const pick = (e) => {
        const v = e.target.value;
        const pr = prodList.find((p) => p[0] === v);
        setRf({ ...rf, p: v, c: pr ? String(pr[3]) : rf.c, s: pr ? pr[6] : rf.s, img: '', imgName: '' });
        if (imgRef.current) imgRef.current.value = '';
      };
      const pickImage = async (e) => {
        const file = e.target.files && e.target.files[0];
        if (!file) return setRf((f) => ({ ...f, img: '', imgName: '' }));
        try {
          const img = await shrinkImage(file);
          setRf((f) => ({ ...f, img, imgName: file.name }));
          setRmsg('');
        } catch (error) {
          e.target.value = '';
          setRf((f) => ({ ...f, img: '', imgName: '' }));
          setRmsg(error.message);
        }
      };
      return (
        <div className='dgrid'>
          <section className='dc span2'>
            <Title ic={NAV.find((x) => x[0] === 'receive')[2]}>Enter new stock</Title>
            <form className='nform' onSubmit={submitReceive}>
              <fieldset className='permission-locked' disabled={!canEdit('inventory')}>
              <label>Product
                <select value={rf.p} onChange={pick}>
                  {prodList.map((p) => <option key={p[0]}>{p[0]}</option>)}
                  <option value='__new'>New product…</option>
                </select>
              </label>
              {isNew && <label>New product name<input type='text' value={rf.name} onChange={set('name')} /></label>}
              {isNew && <label>Selling price ({preferences.currency})<input type='number' min='0' step='0.01' value={rf.price} onChange={set('price')} /></label>}
              <label>Quantity received<input type='number' min='1' step='1' value={rf.q} onChange={set('q')} /></label>
              <label>Unit cost ({preferences.currency})<input type='number' min='0' step='0.01' value={rf.c} onChange={set('c')} /></label>
              <label>Supplier
                <input type='text' list='supl' value={rf.s} onChange={set('s')} />
                <datalist id='supl'>{[...new Set(batches.map((b) => b[6]))].map((n) => <option key={n} value={n} />)}</datalist>
              </label>
              <div className='photo-field'>
                <span>Product photo (optional)</span>
                <input ref={imgRef} type='file' className='photo-input' tabIndex={-1} aria-hidden='true' accept='image/png,image/jpeg,image/webp,image/gif' onChange={pickImage} />
                <div className='photo-drop'>
                  <span className='photo-thumb'>{preview ? <img src={preview} alt='Product photo preview' /> : <Ico d={IC.upload} s={24} />}</span>
                  <div className='photo-copy'>
                    <button type='button' className='btn glass photo-btn' disabled={receiveBusy} aria-describedby='photo-hint' onClick={() => imgRef.current && imgRef.current.click()}>
                      <Ico d={IC.upload} s={16} />Upload image
                    </button>
                    <span id='photo-hint' className='photo-hint'>{rf.imgName || (current && current[7] ? 'Current photo. Upload a new image to replace it.' : 'Choose a PNG, JPG, WebP or GIF up to 1 MB.')}</span>
                  </div>
                </div>
              </div>
              <button type='submit' className='btn iri nbtn' disabled={receiveBusy}>{receiveBusy ? 'Saving…' : 'Add to stock'}</button>
              </fieldset>
            </form>
            {rmsg && <p className='nok' role='status'>{rmsg}</p>}
            {stockMsg && <p className='nerr' role='alert'>{stockMsg}</p>}
          </section>
          <section className='dc'>
            <Title ic={IC.box}>Orders on the way</Title>
            {orders.length === 0 && <p>No open orders. Use Reorder on the Stock page to place one.</p>}
            {orders.map(([x, i]) => (
              <div className='npill col' key={x[0] + i}>
                <b className='l'>{x[0]}</b><span className='nmut'>{x[1]} · {money(x[2])}</span>
                <button className='dmini' disabled={!canEdit('inventory')} onClick={() => receiveOrder(i)}>Mark received</button>
              </div>
            ))}
          </section>
          <section className='dc span3'>
            <Title ic={IC.receipt}>Recently received</Title>
            {recent.map((b) => (
              <div className='npill' key={b[0]}>
                <span className='nin xs'>{b[1][0]}</span><span>{b[1]} × {b[2]}</span>
                <span className='nmut'>{b[6]} · {b[4] === 0 ? 'Today' : b[4] + ' days ago'}</span><b>{preciseMoney(b[5])} each</b>
              </div>
            ))}
          </section>
        </div>
      );
    },

    slow: () => {
      const live = batches.filter((b) => b[3] > 0);
      const units = slow.reduce((a, b) => a + b[3], 0);
      const tied = slow.reduce((a, b) => a + b[3] * b[5], 0);
      const oldest = live.reduce((a, b) => Math.max(a, b[4]), 0);
      const buckets = [['0-30', 0, 30], ['31-60', 31, 60], ['61-90', 61, 90], ['90+', 91, 9999]]
        .map(([l, lo, hi]) => [l, live.filter((b) => b[4] >= lo && b[4] <= hi).reduce((a, b) => a + b[3], 0)]);
      const bmax = Math.max(...buckets.map((x) => x[1]), 1);
      const watch = live.filter((b) => b[4] <= limit && b[4] > limit * 0.7);
      const list = [...slow, ...watch];
      const tip = (b) => (b[4] > limit * 2 ? 'Clear it: 25% off or put it in a bundle.' : b[4] > limit ? 'Try 15% off or pair it with a best seller.' : 'Close to the limit. Give it a push.');
      return (
        <>
          <div className='kpis'>
            {[['Batches too old', slow.length, `older than ${limit} days`], ['Units stuck', units, 'still on the shelf'], ['Money tied up', money(tied), 'at cost price'], ['Oldest stock', oldest + (oldest === 1 ? ' day' : ' days'), 'since it arrived']].map(([l, v, s]) => (
              <div className='kpi flat metric' key={l}><span className='dlab'>{l}</span><b>{v}</b><small>{s}</small></div>
            ))}
          </div>
          <div className='dgrid'>
            <section className='dc'>
              <Title ic={IC.gross}>Stock age, units left</Title>
              <div className='nbars short' role='img' aria-label={'Units left by age: ' + buckets.map((x) => x[0] + ' days ' + x[1]).join(', ')}>
                {buckets.map(([l, u], i) => (
                  <div className='ncol' key={l}>
                    <b>{u}</b>
                    <div className='ntrack'><i className={i === 0 ? '' : 'fc'} style={{ height: (u / bmax) * 100 + '%' }} /></div>
                    <span>{l}d</span>
                  </div>
                ))}
              </div>
            </section>
            <section className='dc span2'>
              <Title ic={NAV.find((x) => x[0] === 'slow')[2]} right={
                <div className='nseg sm' role='group' aria-label='Too long after how many days'>
                  {[30, 45, 60, 90].map((d) => <button key={d} aria-pressed={limit === d} onClick={() => { slowLimitOverridden.current = true; setLimit(d); }}>{d}d</button>)}
                </div>}>Sitting longer than {limit} days</Title>
              {list.length === 0 && <p>Nothing is sitting too long. Nice work.</p>}
              {list.map((b) => {
                const sd = Math.round(((b[2] - b[3]) / b[2]) * 100);
                return (
                  <div className='nbatch' key={b[0]}>
                    <div className='grow'>
                      <div className='nrow2'><span><b>{b[1]}</b> <span className='nmut'>· {b[6]}</span></span><span className={'chipS ' + (b[4] > limit ? 'late' : 'pend')}>{b[4]} days</span></div>
                      <Bar pct={sd} />
                      <div className='nrow2 sub'><span>{sd}% sold, {b[3]} left, {money(b[3] * b[5])} tied up</span><span>{tip(b)}</span></div>
                    </div>
                    <button className='dmini' aria-pressed={!!disc[b[0]]} onClick={() => setDisc({ ...disc, [b[0]]: !disc[b[0]] })}>{disc[b[0]] ? 'Discount on ✓' : 'Mark discounted'}</button>
                  </div>
                );
              })}
            </section>
          </div>
        </>
      );
    },

    expenses: () => (
      <div className='dgrid'>
        <section className='dc span2'>
          <Title ic={IC.exp} right={<b className='dbig sm'>{money(exp)}</b>}>Expenses by category, {m}</Title>
          {cats.length === 0 && <p>No expenses recorded yet.</p>}
          {cats.map(([n, v]) => (
            <div className='nstock' key={n}><div className='nrow2'><span>{n}</span><span>{money(v)}</span></div><Bar pct={(v / maxCat) * 100} /></div>
          ))}
        </section>
        <section className='dc'>
          <Title ic={IC.receipt}>Added by you</Title>
          {expList.length === 0 && <p>Nothing yet. Use + Expense to record one.</p>}
          {expList.map(([w, a, d], i) => <div className='npill' key={w + i}><span className='nin xs'>{w[0]}</span><span>{w}</span><span className='nmut'>{d}</span><b>{money(a)}</b></div>)}
        </section>
      </div>
    ),

    customers: () => {
      const map = {};
      sales.forEach(([w, a, , d]) => { const c = map[w] || (map[w] = [w, 0, 0, d]); c[1]++; c[2] += a; });
      const cust = Object.values(map);
      return (
      <section className='dc'>
        <Title ic={NAV.find((x) => x[0] === 'customers')[2]}>Customers</Title>
        {cust.length === 0 && <p>No customers yet. They appear as you record sales.</p>}
        {cust.map(([n, o, sp, last]) => (
          <div className='npill' key={n}>
            <span className='nin xs'>{n[0]}</span><span>{n}</span><span className='nmut'>{o} orders · last {last}</span><b>{money(sp)}</b>
          </div>
        ))}
      </section>
      );
    },

    reports: () => (
      <section className='dc'>
        <Title ic={NAV.find((x) => x[0] === 'reports')[2]}>Monthly reports</Title>
        <div className='nscroll'><div className='ntable'>
          <div className='nth r'><span>Period</span><span>Revenue</span><span>Expenses</span><span>Gross profit</span><span>Net profit</span></div>
          {reportRows.slice().reverse().map((r) => (
            <div className='ntr r' key={r.month}><b>{monthLabel(r.month)}</b><span>{money(toNum(r.revenue))}</span><span>{money(toNum(r.expenses))}</span><span>{money(toNum(r.gross_profit))}</span><span className='ncy'>{money(toNum(r.net_profit))}</span></div>
          ))}
        </div></div>
      </section>
    ),

    insights: () => (
      <div className='dgrid'>
        <section className='dc assistant-chat'>
          <div className='assistant-modes'>
            <div>
              <Title ic={IC.bulb}>Financial intelligence</Title>
              <p>Choose how you want to analyse your business.</p>
            </div>
            <div className='nseg' role='group' aria-label='Assistant mode'>
              <button type='button' aria-pressed={assistantMode === 'algorithm'} onClick={() => setAssistantMode('algorithm')}>Algorithms</button>
              <button type='button' aria-pressed={assistantMode === 'ai'} onClick={() => setAssistantMode('ai')}>AI assistant</button>
            </div>
          </div>
          {assistantMode === 'algorithm' ? (
            <>
              <p>Verified calculations and rule-based insights run on your data—no AI connection required.</p>
              <div className='analysis-options' role='group' aria-label='Choose an algorithm analysis'>
                {[
                  ['profitability', 'Profitability'],
                  ['sales_trends', 'Sales trends'],
                  ['expense_analysis', 'Expense analysis'],
                  ['product_rankings', 'Product rankings'],
                  ['stock_cover', 'Stock cover'],
                  ['reorder_planning', 'Reorder planning'],
                  ['aging_inventory', 'Aging inventory'],
                  ['break_even', 'Break-even estimate'],
                  ['customer_concentration', 'Customer concentration'],
                  ['cash_indicators', 'Cash-flow indicators'],
                ].map(([id, label]) => (
                  <button className='dmini' type='button' key={id} aria-pressed={algorithmType === id} disabled={algorithmBusy}
                    onClick={() => { setAlgorithmType(id); setAlgorithmResult(null); setAlgorithmError(''); }}>{label}</button>
                ))}
                <button className='btn iri nbtn' type='button' onClick={runAlgorithm} disabled={algorithmBusy}>
                  {algorithmBusy ? 'Analysing…' : 'Run analysis'}
                </button>
              </div>
              {algorithmError && <p className='assistant-error' role='alert'>{algorithmError}</p>}
            </>
          ) : (
            <>
              <p>Ask a question about verified monthly figures. Answers are generated by the configured AI service.</p>
          {assistantMessages.length === 0 && (
            <div className='assistant-prompts'>
              {['How did my business perform this month?', 'What are my biggest expenses?', 'What should I focus on next?'].map((prompt) => (
                <button className='dmini' type='button' key={prompt} onClick={() => setAssistantQuestion(prompt)}>{prompt}</button>
              ))}
            </div>
          )}
          {assistantMessages.length > 0 && (
            <div className='assistant-messages' role='log' aria-live='polite' aria-label='Assistant conversation'>
              {assistantMessages.map((message, index) => (
                <div className={'assistant-message ' + (message.role === 'user' ? 'user' : 'assistant')} key={index}>
                  <span className='assistant-label'>{message.role === 'user' ? 'You' : 'Nexa assistant'}</span>
                  <p>{message.text}</p>
                </div>
              ))}
            </div>
          )}
          <form className='assistant-form' onSubmit={askAssistant}>
            <textarea aria-label='Ask a question about your business' maxLength={1000} placeholder='Ask about revenue, expenses, or trends…'
              value={assistantQuestion} onChange={(event) => setAssistantQuestion(event.target.value)} disabled={assistantBusy} />
            <button className='btn iri nbtn' type='submit' disabled={assistantBusy || !assistantQuestion.trim()}>
              {assistantBusy ? 'Thinking…' : 'Ask'}
            </button>
          </form>
          {assistantError && <p className='assistant-error' role='alert'>{assistantError}</p>}
          <p className='assistant-note'>Only your question and aggregated monthly summary are sent to the configured AI service; customer and product names or transaction details are not shared. Answers are suggestions, not financial advice.</p>
            </>
          )}
        </section>
        {assistantMode === 'algorithm' && algorithmResult && (
          <section className='dc algorithm-results'>
            <Title ic={IC.gross} right={<span className='nmut'>{algorithmResult.period}</span>}>{algorithmResult.title}</Title>
            <div className='algorithm-metrics'>
              {algorithmResult.metrics.map((metric) => (
                <div className='algorithm-metric' key={metric.label}>
                  <span>{metric.label}</span>
                  <b>{metric.value === null ? '—' : metric.format === 'currency' ? preciseMoney(metric.value) : metric.format === 'percent' || metric.format === 'change' ? `${metric.value}%` : metric.value}</b>
                </div>
              ))}
            </div>
            {algorithmResult.series && (
              <div className='algorithm-series' aria-label='Monthly sales and moving averages'>
                {algorithmResult.series.map((point) => {
                  const peak = Math.max(...algorithmResult.series.map((item) => Number(item.revenue)), 1);
                  return (
                    <div className='algorithm-series-row' key={point.period}>
                      <span>{point.label}</span>
                      <div className='algorithm-series-track'><i style={{ width: `${Math.max(Number(point.revenue) > 0 ? 2 : 0, Number(point.revenue) / peak * 100)}%` }} /></div>
                      <div className='algorithm-series-values'><b>{preciseMoney(point.revenue)}</b><span>3mo avg {preciseMoney(point.moving_average)}</span></div>
                    </div>
                  );
                })}
              </div>
            )}
            {algorithmResult.categories && (
              <div className='algorithm-table'>
                {algorithmResult.categories.length === 0
                  ? <div className='algorithm-empty'><p>No expense categories were recorded for this period.</p></div>
                  : <>
                    <div className='algorithm-row'><b>Category</b><b>Amount</b><b className='optional'>vs prior</b><b>Share</b></div>
                    {algorithmResult.categories.map((row) => (
                      <div className='algorithm-row' key={row.category}>
                        <b>{row.category}</b><span>{preciseMoney(row.amount)}</span>
                        <span className='optional'>{row.change_pct === null ? '—' : `${row.change_pct}%`}</span>
                        <span>{row.share_pct === null ? '—' : `${row.share_pct}%`}</span>
                      </div>
                    ))}
                  </>}
              </div>
            )}
            {algorithmResult.products && (
              <div className='algorithm-table'>
                {algorithmResult.products.length === 0
                  ? <div className='algorithm-empty'><p>No product-linked sales were recorded for this period.</p></div>
                  : <>
                    <div className='algorithm-row'><b>Product</b><b>Revenue</b><b className='optional'>Units</b><b>Gross profit</b></div>
                    {algorithmResult.products.map((row) => (
                      <div className='algorithm-row' key={row.rank}>
                        <b>{row.rank}. {row.product}</b><span>{preciseMoney(row.revenue)}</span>
                        <span className='optional'>{row.units}</span><span>{preciseMoney(row.gross_profit)}</span>
                      </div>
                    ))}
                  </>}
              </div>
            )}
            {algorithmResult.reorders && (
              <div className='algorithm-table'>
                {algorithmResult.reorders.length === 0 ? <div className='algorithm-empty'><p>No products are tracked yet.</p></div> : <>
                  <div className='algorithm-row'><b>Product</b><b>Stock + ordered</b><b className='optional'>Reorder point</b><b>Order units</b></div>
                  {algorithmResult.reorders.map((row) => (
                    <div className='algorithm-row' key={row.product}>
                      <b>{row.product}</b><span>{row.stock} + {row.incoming}</span>
                      <span className='optional'>{row.reorder_point === null ? '—' : row.reorder_point}</span>
                      <span>{row.reorder_point === null ? 'No data' : row.suggested_quantity}</span>
                    </div>
                  ))}
                </>}
              </div>
            )}
            {algorithmResult.inventory && (
              <div className='algorithm-table'>
                {algorithmResult.inventory.length === 0 ? <div className='algorithm-empty'><p>No stock is currently on hand.</p></div> : <>
                  <div className='algorithm-row'><b>Product</b><b>Aged units</b><b className='optional'>Total value</b><b>Aged value</b></div>
                  {algorithmResult.inventory.map((row) => (
                    <div className='algorithm-row' key={row.product}>
                      <b>{row.product}</b><span>{row.aged_units}</span><span className='optional'>{preciseMoney(row.value)}</span><span>{preciseMoney(row.aged_value)}</span>
                    </div>
                  ))}
                </>}
              </div>
            )}
            {algorithmResult.customer_rows && (
              <div className='algorithm-table'>
                {algorithmResult.customer_rows.length === 0 ? <div className='algorithm-empty'><p>No identified customer revenue in this period.</p></div> : <>
                  <div className='algorithm-row'><b>Customer</b><b>Paid sales</b><b className='optional'>Share of revenue</b><b>Share</b></div>
                  {algorithmResult.customer_rows.map((row) => (
                    <div className='algorithm-row' key={row.customer}>
                      <b>{row.customer}</b><span>{preciseMoney(row.revenue)}</span><span className='optional'>of total paid</span><span>{row.share_pct === null ? '—' : `${row.share_pct}%`}</span>
                    </div>
                  ))}
                </>}
              </div>
            )}
            {algorithmResult.stock && (
              <div className='algorithm-table'>
                {algorithmResult.stock.length === 0
                  ? <div className='algorithm-empty'><p>No products are tracked yet. Receive stock to start.</p></div>
                  : <>
                    <div className='algorithm-row'><b>Product</b><b>Stock</b><b className='optional'>Cover</b><b>Status</b></div>
                    {algorithmResult.stock.map((row) => (
                      <div className='algorithm-row' key={row.product}>
                        <b>{row.product}</b><span>{row.stock}</span>
                        <span className='optional'>{row.days_cover === null ? '—' : `${row.days_cover} days`}</span>
                        <span>{row.status}{row.reorder_qty > 0 ? ` · order ${row.reorder_qty}` : ''}</span>
                      </div>
                    ))}
                  </>}
              </div>
            )}
            <ul className='algorithm-insights'>
              {algorithmResult.insights.map((insight, index) => <li key={index}>{insight}</li>)}
            </ul>
            <p className='assistant-note'>Calculated from recorded transactions for this period. Insights are descriptive, not financial advice.</p>
          </section>
        )}
        <section className='dc span2'>
          <Title ic={IC.bulb} right={<div className='nseg sm' role='group' aria-label='Filter by priority'>
            {['All', 'High'].map((p) => <button key={p} aria-pressed={pri === p} onClick={() => setPri(p)}>{p}</button>)}</div>}>Smart ideas for you</Title>
          <ul className='nrecs'>
            {recs.length === 0 && <li><p>No ideas yet. They will show up as your data grows.</p></li>}
            {recs.map((r) => (
              <li key={r.id} className={done[r.id] ? 'done' : ''}>
                <span className={'pri ' + r.pri.toLowerCase()}>{r.pri}</span>
                <div><b>{r.cat}</b><p>{r.text}</p></div>
                <button className='dmini' aria-pressed={!!done[r.id]} onClick={() => setDone({ ...done, [r.id]: !done[r.id] })}>{done[r.id] ? 'Undo' : 'Done'}</button>
              </li>
            ))}
          </ul>
        </section>
        <section className='dc'>
          <Title ic={IC.net}>Forecast for {monthName(1)}</Title>
          <div className='nscn' role='group' aria-label='Scenario'>
            {Object.keys(SC).map((s) => <button key={s} aria-pressed={scn === s} onClick={() => setScn(s)}><i>{s[0]}</i><span>{s}</span></button>)}
          </div>
          <b className='dbig'>{money(nextTotal)}</b>
          <p>{((factor - 1) * 100 >= 0 ? '+' : '') + ((factor - 1) * 100).toFixed(0)}% on {m}. Based on your weekly trend and best sellers.</p>
        </section>
        <section className='dc span3'>
          <Title ic={IC.gross} right={<span className='nleg'><i />Actual<i className='fc' />Forecast</span>}>Sales by week, {m}</Title>
          <Trend series={series} next={nextWeek} key={m + scn + rev} />
        </section>
      </div>
    ),
  };

  const scopeForNav = {
    overview: 'dashboard', sales: 'sales', products: 'inventory', stock: 'inventory',
    receive: 'inventory', slow: 'inventory', expenses: 'expenses', customers: 'customers',
    reports: 'reports', insights: 'insights', settings: 'settings',
  };
  const visibleNav = NAV.filter(([id]) => {
    if (id === 'account') return true;
    if (id === 'team') return activeWorkspace?.role === 'owner' || activeWorkspace?.can_manage_members;
    const scope = scopeForNav[id];
    return activeWorkspace?.role === 'owner' || !!activeWorkspace?.permissions?.[scope]?.view;
  });
  const displayedNav = visibleNav.some(([id]) => id === nav) ? nav : visibleNav[0]?.[0] || 'account';
  const cur = NAV.find((n) => n[0] === displayedNav) || NAV[0];
  const showMonth = ['overview', 'products', 'expenses', 'insights'].includes(displayedNav);
  const go = (id) => { setNav(id); setQ(''); window.scrollTo(0, 0); };

  return (
    <div className='dash'>
      <div className='mobile-brand'><BusinessBrand {...businessProfile} /></div>
      <div className='nshell'>
        <nav className='nside' aria-label='Main menu'>
          <BusinessBrand {...businessProfile} />
          <span className='ngrp'>Menu</span>
          {visibleNav.map(([id, label, ic], i) => (
            <React.Fragment key={id}>
              {id === 'sales' && <span className='ngrp'>Libraries</span>}
              <button className='nnav' aria-current={displayedNav === id ? 'page' : undefined} onClick={() => go(id)}>
                <span className='nin'><Ico d={ic} s={17} /></span><span className='nlab'>{label}</span>
              </button>
            </React.Fragment>
          ))}
        </nav>

        <main className='nmain'>
          <header className='ntop'>
            <div><h1>{cur[1]}</h1><p>{preferences.business_name ? `${preferences.business_name} · ${cur[3]}` : cur[3]}</p></div>
            <div className='ntools'>
              {workspaces.length > 1 && <label className='workspace-picker'>Business
                <select aria-label='Business workspace' value={activeWorkspace?.id || ''} onChange={(event) => onWorkspaceChange(event.target.value)}>
                  {workspaces.map((workspace) => <option key={workspace.id} value={workspace.id}>{workspace.name} · {workspace.role}</option>)}
                </select>
              </label>}
              {showMonth && <Month />}
              {displayedNav !== 'settings' && displayedNav !== 'account' && displayedNav !== 'team' && <>
                {canEdit('sales') && <button className='btn iri nbtn' onClick={() => setForm('sale')}>+ Sale</button>}
                {canEdit('expenses') && <button className='btn glass nbtn' onClick={() => setForm('expense')}>+ Expense</button>}
              </>}
              {isStaff && <a className='dpill' href={ADMIN_URL} target='_blank' rel='noopener'>Admin</a>}
              <button className='dpill' onClick={onExit}>Sign out</button>
            </div>
          </header>
          {workspaceNotice && <p className='nok' role='status'>{workspaceNotice}</p>}
          <div key={displayedNav} className='nview'>{views[displayedNav]()}</div>
        </main>
      </div>
      {form && <RecordSheet type={form} onClose={() => setForm(null)} onSave={save} products={prods} currency={preferences.currency} />}
    </div>
  );
}

export default function App() {
  const [mode, setMode] = useState(null);
  const [view, setView] = useState('welcome');
  const [workspaces, setWorkspaces] = useState([]);
  const [activeWorkspaceId, setActiveWorkspaceId] = useState(selectedWorkspace());
  const [workspaceNotice, setWorkspaceNotice] = useState('');
  const [teamInvite, setTeamInvite] = useState(null);
  const [teamInviteMessage, setTeamInviteMessage] = useState({ text: '', error: false });
  const [accountChallenge, setAccountChallenge] = useState(null);
  const [accountConfirmation, setAccountConfirmation] = useState('');
  const [accountChallengeMessage, setAccountChallengeMessage] = useState({ text: '', error: false });
  const [accountChallengeBusy, setAccountChallengeBusy] = useState(false);
  const [passwordResetChallenge, setPasswordResetChallenge] = useState(null);
  const [passwordResetForm, setPasswordResetForm] = useState({ password: '', password2: '' });
  const [passwordResetMessage, setPasswordResetMessage] = useState({ text: '', error: false });
  const [passwordResetBusy, setPasswordResetBusy] = useState(false);
  useEffect(() => { document.body.classList.toggle('inapp', view === 'app'); document.body.classList.toggle('welcome', view === 'welcome'); window.scrollTo(0, 0); }, [view]);
  const [dark, setDark] = useState(false);
  const setTheme = (enabled) => { setDark(enabled); document.documentElement.dataset.theme = enabled ? "dark" : "light"; };

  const loadWorkspaceUser = async (token) => {
    try {
      return await currentUser(token);
    } catch (error) {
      if (error.status !== 403 || !selectedWorkspace()) throw error;
      selectWorkspace(null);
      const user = await currentUser(token);
      setWorkspaceNotice("Your previous business workspace is no longer available. Showing your personal business.");
      return user;
    }
  };
  const openApp = async (inviteToken = null) => {
    const token = localStorage.getItem(TOKEN_KEY);
    const user = await loadWorkspaceUser(token);
    const workspaceId = selectedWorkspace() || String(user.active_workspace_id);
    selectWorkspace(workspaceId);
    setActiveWorkspaceId(workspaceId);
    setWorkspaces(user.workspaces || []);
    setView('app');
    if (inviteToken) {
      try {
        const accepted = await acceptTeamInvitation(inviteToken, token);
        const acceptedId = String(accepted.workspace.id);
        selectWorkspace(acceptedId);
        setActiveWorkspaceId(acceptedId);
        const updatedUser = await currentUser(token);
        setWorkspaces(updatedUser.workspaces || []);
        setTeamInvite(null);
        setWorkspaceNotice(`You joined ${accepted.workspace.name}.`);
      } catch (error) {
        setWorkspaceNotice(error.message);
      }
    }
  };
  useEffect(() => {
    const url = new URL(window.location.href);
    const hashParams = new URLSearchParams(url.hash.slice(1));
    const invitationToken = hashParams.get('team_invite');
    const resetToken = hashParams.get('password_reset');
    const action = url.searchParams.get('account_action') || hashParams.get('account_action');
    const challengeToken = url.searchParams.get('token') || hashParams.get('token');
    if (resetToken) {
      setPasswordResetChallenge({ token: resetToken });
      url.searchParams.delete('password_reset');
      url.searchParams.delete('token');
      url.searchParams.delete('account_action');
      url.hash = '';
      window.history.replaceState(null, '', url.pathname + url.search);
      return;
    }
    if (invitationToken) {
      setTeamInvite({ token: invitationToken, preview: null });
      url.hash = '';
      window.history.replaceState(null, '', url.pathname + url.search);
      previewTeamInvitation(invitationToken).then((preview) => {
        setTeamInvite({ token: invitationToken, preview });
      }).catch((error) => {
        setTeamInvite({ token: invitationToken, preview: null });
        setTeamInviteMessage({ text: error.message, error: true });
      });
    }
    if (['export', 'delete'].includes(action) && challengeToken) {
      setAccountChallenge({ action, token: challengeToken });
      url.searchParams.delete('account_action');
      url.searchParams.delete('token');
      url.hash = '';
      window.history.replaceState(null, '', url.pathname + url.search);
      return;
    }
    if (challengeToken) {
      verifyMagicLink(challengeToken).then((session) => {
        localStorage.setItem(TOKEN_KEY, session.token);
        url.searchParams.delete('token');
        url.hash = '';
        window.history.replaceState(null, '', url.pathname + url.search);
        openApp(invitationToken).catch((error) => {
          setTeamInviteMessage({ text: error.message, error: true });
        });
      }).catch((error) => {
        setAccountChallengeMessage({ text: error.message, error: true });
        url.searchParams.delete('token');
        url.hash = '';
        window.history.replaceState(null, '', url.pathname + url.search);
      });
      return;
    }
    const t = localStorage.getItem(TOKEN_KEY);
    if (!t) return;
    openApp(invitationToken).catch((e) => { if (!/reach/.test(e.message)) localStorage.removeItem(TOKEN_KEY); });
  }, []);
  const confirmAccountAction = async (event) => {
    event.preventDefault();
    if (!accountChallenge) return;
    setAccountChallengeBusy(true);
    setAccountChallengeMessage({ text: '', error: false });
    try {
      if (accountChallenge.action === 'export') {
        const blob = await exportAccountData(accountChallenge.token, accountConfirmation);
        const url = window.URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = 'nexa-account-export.csv';
        document.body.appendChild(link);
        link.click();
        link.remove();
        window.URL.revokeObjectURL(url);
        setAccountChallenge(null);
        setAccountConfirmation('');
        setAccountChallengeMessage({ text: 'Your CSV export was downloaded.', error: false });
      } else {
        const result = await deleteAccount(accountChallenge.token, accountConfirmation);
        localStorage.removeItem(TOKEN_KEY);
        localStorage.removeItem(WORKSPACE_KEY);
        setAccountChallenge({ completed: true });
        setAccountChallengeMessage({ text: result.message, error: false });
      }
    } catch (error) {
      setAccountChallengeMessage({ text: error.message, error: true });
    } finally {
      setAccountChallengeBusy(false);
    }
  };
  const submitPasswordReset = async (event) => {
    event.preventDefault();
    if (!passwordResetChallenge || passwordResetBusy) return;
    setPasswordResetMessage({ text: '', error: false });
    if (passwordResetForm.password !== passwordResetForm.password2) {
      setPasswordResetMessage({ text: 'The passwords do not match.', error: true });
      return;
    }
    setPasswordResetBusy(true);
    try {
      const result = await resetPassword({
        token: passwordResetChallenge.token,
        password: passwordResetForm.password,
        password2: passwordResetForm.password2,
      });
      localStorage.removeItem(TOKEN_KEY);
      setPasswordResetChallenge({ completed: true });
      setPasswordResetForm({ password: '', password2: '' });
      setPasswordResetMessage({ text: result.detail, error: false });
    } catch (error) {
      setPasswordResetMessage({ text: error.message, error: true });
    } finally {
      setPasswordResetBusy(false);
    }
  };
  const signOut = () => {
    const t = localStorage.getItem(TOKEN_KEY);
    localStorage.removeItem(TOKEN_KEY);
    selectWorkspace(null);
    if (t) logout(t).catch(() => {});
    activeCurrency = 'USD';
    activeTimeZone = 'Africa/Harare';
    setAccountChallengeMessage({ text: '', error: false });
    setTheme(false); setView('welcome');
  };
  if (accountChallenge && !accountChallenge.completed) return (
    <div className='landing-page'>
      <nav><div className='logo'><i />Nexa</div></nav>
      <main className='hero'>
        <span className='tag'>Secure account confirmation</span>
        <h1>{accountChallenge.action === 'delete' ? 'Delete your account?' : 'Download your data?'}</h1>
        <p className='sub'>
          {accountChallenge.action === 'delete'
            ? 'This permanently deletes your Nexa account and associated business data.'
            : 'This creates a private CSV export of your Nexa business data.'}
        </p>
        <form className='nform' onSubmit={confirmAccountAction}>
          <label>Type {accountChallenge.action.toUpperCase()} to confirm
            <input autoComplete='off' value={accountConfirmation} onChange={(e) => setAccountConfirmation(e.target.value)} />
          </label>
          <button type='submit' className='btn iri' disabled={accountChallengeBusy}>
            {accountChallengeBusy ? 'Processing…' : accountChallenge.action === 'delete' ? 'Delete account' : 'Download CSV'}
          </button>
        </form>
        {accountChallengeMessage.text && <p className={accountChallengeMessage.error ? 'nerr' : 'nok'} role={accountChallengeMessage.error ? 'alert' : 'status'}>{accountChallengeMessage.text}</p>}
        <button className='btn glass' onClick={() => { setAccountChallenge(null); setAccountConfirmation(''); }}>Cancel</button>
      </main>
    </div>
  );
  if (accountChallenge && accountChallenge.completed) return (
    <div className='landing-page'><main className='hero'><h1>Account deleted</h1><p className='sub'>{accountChallengeMessage.text}</p></main></div>
  );
  if (passwordResetChallenge && !passwordResetChallenge.completed) return (
    <div className='landing-page'>
      <nav><div className='logo'><i />Nexa</div></nav>
      <main className='hero'>
        <span className='tag'>Secure password reset</span>
        <h1>Choose a new password</h1>
        <p className='sub'>Your password must meet Nexa's password requirements. Reset links expire after a short time and can only be used once.</p>
        <form className='nform' onSubmit={submitPasswordReset}>
          <label>New password
            <input type='password' autoComplete='new-password' required value={passwordResetForm.password} onChange={(event) => setPasswordResetForm({ ...passwordResetForm, password: event.target.value })} />
          </label>
          <label>Re-enter new password
            <input type='password' autoComplete='new-password' required value={passwordResetForm.password2} onChange={(event) => setPasswordResetForm({ ...passwordResetForm, password2: event.target.value })} />
          </label>
          <button type='submit' className='btn iri' disabled={passwordResetBusy}>{passwordResetBusy ? 'Updating…' : 'Set new password'}</button>
        </form>
        {passwordResetMessage.text && <p className={passwordResetMessage.error ? 'nerr' : 'nok'} role={passwordResetMessage.error ? 'alert' : 'status'}>{passwordResetMessage.text}</p>}
        <button className='btn glass' onClick={() => { setPasswordResetChallenge(null); setMode('signin'); }}>Return to sign in</button>
      </main>
    </div>
  );
  if (passwordResetChallenge && passwordResetChallenge.completed) return (
    <div className='landing-page'>
      <main className='hero'>
        <h1>Password reset complete</h1>
        <p className='sub'>{passwordResetMessage.text}</p>
        <button className='btn iri' onClick={() => { setPasswordResetChallenge(null); setMode('signin'); }}>Sign in</button>
      </main>
    </div>
  );
  if (view === 'app') return <Dashboard
    key={activeWorkspaceId}
    setTheme={setTheme}
    onExit={signOut}
    workspaces={workspaces}
    workspaceNotice={workspaceNotice}
    onWorkspaceChange={(id) => {
      selectWorkspace(id);
      setActiveWorkspaceId(String(id));
      setWorkspaceNotice('');
    }}
  />;
  return (
    <>
      <div className="landing-page">
        <nav>
          <div className="logo"><i />Nexa</div>
          <button className="btn glass" onClick={() => setMode("signin")}>Sign in</button>
        </nav>
        <main className="hero">
          {teamInvite && <section className='dc team-invite-landing'>
            <span className='account-kicker'>BUSINESS INVITATION</span>
            <h2>{teamInvite.preview ? `Join ${teamInvite.preview.business_name}` : 'Accept your business invitation'}</h2>
            <p>{teamInvite.preview
              ? `This invitation was sent to ${teamInvite.preview.email}. Sign in or create an account with that email to join.`
              : 'Sign in or create an account with the invited email address to continue.'}</p>
            <div className='goal-actions'>
              <button className='btn iri' onClick={() => setMode('signin')}>Sign in to accept</button>
              <button className='btn glass' onClick={() => setMode('signup')}>Create account</button>
            </div>
            {teamInviteMessage.text && <p className={teamInviteMessage.error ? 'nerr' : 'nok'} role={teamInviteMessage.error ? 'alert' : 'status'}>{teamInviteMessage.text}</p>}
          </section>}
          {accountChallengeMessage.text && <p className={accountChallengeMessage.error ? 'nerr' : 'nok'} role={accountChallengeMessage.error ? 'alert' : 'status'}>{accountChallengeMessage.text}</p>}
          <span className="tag">Business intelligence, reimagined</span>
          <h1>Run your business with <em>foresight</em></h1>
          <p className="sub">Record every sale, purchase and expense in one place. Nexa shows what sells most, how each month is going, and what to do next.</p>
          <div className="cta">
            <button className="btn iri" onClick={() => setMode("signup")}>Get started</button>
            <button className="btn glass" onClick={() => setMode("signin")}>I have an account</button>
          </div>
          <div className="pills">
            <span className="pill">Sales and stock tracking</span>
            <span className="pill">Smart strategy ideas</span>
            <span className="pill">Monthly forecasts</span>
          </div>
        </main>
        <aside className="float f1" aria-hidden="true"><span>Slow stock flagged after</span><b>45 days</b></aside>
        <aside className="float f2" aria-hidden="true"><span>Next-month forecast</span><b>3 scenarios</b></aside>
      </div>
      {mode && <AuthSheet mode={mode} onClose={() => setMode(null)} onEnter={() => {
        setMode(null);
        openApp(teamInvite?.token).catch((error) => {
          setTeamInviteMessage({ text: error.message, error: true });
        });
      }} onSwitch={setMode} />}
    </>
  );
}
