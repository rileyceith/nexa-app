const { useState, useEffect, useLayoutEffect, useRef } = React;

const LOCAL_DEV = location.protocol === "file:" || ["localhost", "127.0.0.1"].includes(location.hostname);
// Locally the API is on port 8000 of the same host as the page, so localhost and 127.0.0.1 both work.
const LOCAL_API_HOST = location.protocol === "file:" ? "localhost" : location.hostname;
const API = window.NEXA_MOBILE ? window.NEXA_API : (window.NEXA_API || (LOCAL_DEV ? `http://${LOCAL_API_HOST}:8000/api` : "https://api.Nexa-app.com/api"));
// The Django admin lives next to the API.
const ADMIN_URL = API ? API.replace(/\/api\/?$/, "") + "/admin/" : "";
const TOKEN_KEY = "nexa_token";
async function call(path, body, token, method) {
  if (!API) throw new Error("The mobile app's server address has not been configured.");
  let r;
  try {
    r = await fetch(API + path, {
      method: method || (body ? "POST" : "GET"),
      headers: { "Content-Type": "application/json", ...(token ? { Authorization: "Bearer " + token } : {}) },
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (e) {
    throw new Error("Cannot reach the server. Start the backend and try again.");
  }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || (
    r.status === 404 && path.startsWith("/assistant/")
      ? "Assistant endpoints are unavailable. Restart Django and reload the app."
      : "Something went wrong."
  ));
  return data;
}

const IMAGE_TYPES = ['image/png', 'image/jpeg', 'image/webp', 'image/gif'];
const IMAGE_MAX_SIDE = 1024;
const IMAGE_MAX_BYTES = 1024 * 1024;

const readFile = (file) => new Promise((resolve, reject) => {
  const reader = new FileReader();
  reader.onload = () => resolve(reader.result);
  reader.onerror = () => reject(new Error('That file could not be read.'));
  reader.readAsDataURL(file);
});

// Small files are sent unchanged; anything larger is resized and re-encoded as JPEG.
async function shrinkImage(file) {
  if (!IMAGE_TYPES.includes(file.type)) throw new Error('Choose a PNG, JPEG, WebP or GIF image.');
  const src = await readFile(file);
  const img = new Image();
  img.src = src;
  try {
    await img.decode();
  } catch (e) {
    throw new Error('That file is not a valid image.');
  }
  const side = Math.max(img.naturalWidth, img.naturalHeight);
  if (file.size <= IMAGE_MAX_BYTES && side <= IMAGE_MAX_SIDE) return src;
  const scale = Math.min(1, IMAGE_MAX_SIDE / side);
  const canvas = document.createElement('canvas');
  canvas.width = Math.max(1, Math.round(img.naturalWidth * scale));
  canvas.height = Math.max(1, Math.round(img.naturalHeight * scale));
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#fff';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
  for (const quality of [0.85, 0.7, 0.5]) {
    const out = canvas.toDataURL('image/jpeg', quality);
    if ((out.length - out.indexOf(',') - 1) * 0.75 <= IMAGE_MAX_BYTES) return out;
  }
  throw new Error('That photo is still too large after resizing. Try a smaller image.');
}

function Sheet({ mode, onClose, onEnter, onSwitch }) {
  const [f, setF] = useState({ username: "", email: "", password: "", password2: "", terms: false });
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const submittingRef = useRef(false);
  const [showTerms, setShowTerms] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const leavingRef = useRef(false);
  const ref = useRef(null);
  const sheetRef = useRef(null);
  const lastH = useRef(0);
  const reduceMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const leave = (done) => {
    if (leavingRef.current) return;
    leavingRef.current = true;
    setLeaving(true);
    setTimeout(done, reduceMotion() ? 0 : 200);
  };
  useEffect(() => {
    ref.current && ref.current.focus();
    const esc = (e) => e.key === "Escape" && leave(onClose);
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, []);
  useLayoutEffect(() => {
    const el = sheetRef.current;
    const shown = el.style.height ? el.offsetHeight : lastH.current;
    el.style.transition = "none";
    el.style.height = "";
    const to = el.offsetHeight;
    lastH.current = to;
    if (!shown || Math.abs(to - shown) < 1 || reduceMotion()) return;
    el.style.height = shown + "px";
    el.style.overflow = "hidden";
    void el.offsetHeight;
    el.style.transition = "height .3s cubic-bezier(.2,.7,.2,1)";
    el.style.height = to + "px";
  });
  const settleHeight = (e) => {
    if (e.target !== e.currentTarget || e.propertyName !== "height") return;
    e.currentTarget.style.transition = "";
    e.currentTarget.style.height = "";
    e.currentTarget.style.overflow = "";
  };
  const signup = mode === "signup";
  const set = (k) => (e) => setF({ ...f, [k]: k === "terms" ? e.target.checked : e.target.value });
  const submit = async (e) => {
    e.preventDefault();
    if (leavingRef.current || submittingRef.current) return;
    setErr("");
    if (signup) {
      if (f.password !== f.password2) return setErr("The passwords do not match.");
      if (!f.terms) return setErr("You must accept the terms and conditions.");
    }
    submittingRef.current = true;
    setBusy(true);
    try {
      const res = await call(signup ? "/auth/register/" : "/auth/login/",
        signup ? { username: f.username, email: f.email, password: f.password, password2: f.password2, accepted_terms: f.terms }
               : { username: f.username, password: f.password });
      localStorage.setItem(TOKEN_KEY, res.token);
      leave(() => onEnter(res.user));
      return;
    } catch (x) {
      setErr(x.message);
    } finally {
      submittingRef.current = false;
      setBusy(false);
    }
  };
  return (
    <div className={leaving ? "scrim auth-scrim leaving" : "scrim auth-scrim"} onClick={() => leave(onClose)}>
      <form className={leaving ? "sheet auth-sheet leaving" : "sheet auth-sheet"} ref={sheetRef} role="dialog" aria-modal="true" aria-labelledby="st"
        onClick={(e) => e.stopPropagation()} onSubmit={submit} onTransitionEnd={settleHeight} noValidate>
        <div className="hd" key={mode}>
          <h2 id="st">{signup ? "Create your Nexa account" : "Welcome back"}</h2>
          <p>{signup ? "Choose an email, username and password." : "Sign in with your username and password."}</p>
        </div>
        <label>Username
          <input ref={ref} type="text" required autoComplete="username" value={f.username} onChange={set("username")} />
        </label>
        {signup && (
          <label>Email
            <input type="email" required autoComplete="email" value={f.email} onChange={set("email")} />
          </label>
        )}
        <label>Password
          <input type="password" required autoComplete={signup ? "new-password" : "current-password"} value={f.password} onChange={set("password")} />
        </label>
        {signup && (
          <label>Re-enter password
            <input type="password" required autoComplete="new-password" value={f.password2} onChange={set("password2")} />
          </label>
        )}
        {signup && (
          <>
            <label className="agree">
              <input type="checkbox" checked={f.terms} onChange={set("terms")} />
              <span>I accept the <button type="button" className="linkbtn" onClick={() => setShowTerms(!showTerms)}>terms and conditions</button></span>
            </label>
            {showTerms && (
              <div className="terms">
                <p>1. Nexa helps you record and review your business activity. You are responsible for the accuracy of what you enter.</p>
                <p>2. Keep your password private. You are responsible for activity on your account.</p>
                <p>3. We store your account and business records to run the service and do not sell them.</p>
                <p>4. Forecasts and ideas are estimates, not financial advice.</p>
              </div>
            )}
          </>
        )}
        {err && <p className="err" role="alert">{err}</p>}
        <div className="row">
          <button type="button" className="btn glass" onClick={() => leave(onClose)}>Cancel</button>
          <button type="submit" className={busy ? "btn iri busy" : "btn iri"} disabled={busy}>{busy ? "Please wait…" : signup ? "Create account" : "Sign in"}</button>
        </div>
        <p className="switch">
          {signup ? "Already have an account? " : "New to Nexa? "}
          <button type="button" className="linkbtn" onClick={() => onSwitch(signup ? "signin" : "signup")}>{signup ? "Sign in" : "Create one"}</button>
        </p>
      </form>
    </div>
  );
}

function smoothPath(p) {
  let d = `M${p[0][0]},${p[0][1]}`;
  for (let i = 0; i < p.length - 1; i++) {
    const a = p[i - 1] || p[i], b = p[i], c = p[i + 1], e = p[i + 2] || c;
    d += ` C${b[0] + (c[0] - a[0]) / 6},${b[1] + (c[1] - a[1]) / 6} ${c[0] - (e[0] - b[0]) / 6},${c[1] - (e[1] - b[1]) / 6} ${c[0]},${c[1]}`;
  }
  return d;
}
const money = (n) => '$' + Math.round(n).toLocaleString('en-US');
const preciseMoney = (n) => '$' + Number(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const wholeOrCents = (n) => (Number.isInteger(n) ? money(n) : preciseMoney(n));
const NOW = new Date();
const CUR = NOW.toLocaleString('en-US', { month: 'short' });
const CUR_NEXT = new Date(NOW.getFullYear(), NOW.getMonth() + 1, 1).toLocaleString('en-US', { month: 'short' });
const MONTHS = [CUR];
const NEXT = { [CUR]: CUR_NEXT };
const THIS_MONTH = `${NOW.getFullYear()}-${String(NOW.getMonth() + 1).padStart(2, '0')}`;
const PREV_MONTH = new Date(NOW.getFullYear(), NOW.getMonth() - 1, 1).toLocaleString('en-US', { month: 'short' });
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
    day: { buckets: bars(shortDate, (iso, i) => (i === 0 || (i + 1) % 5 === 0 ? String(i + 1) : '')), heading: `Daily sales, ${CUR}`, actual: 'Daily sales', targetText: `Daily target ${wholeOrCents(target)}` },
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
          <b>{v >= 1000 ? '$' + (v / 1000).toFixed(1) + 'k' : money(v)}</b>
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

function RecordSheet({ type, onClose, onSave, products = [] }) {
  const [who, setWho] = useState('');
  const [amt, setAmt] = useState('');
  const [st, setSt] = useState('Paid');
  const [productId, setProductId] = useState('');
  const [qty, setQty] = useState('1');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const savingRef = useRef(false);
  const ref = useRef(null);
  useEffect(() => {
    ref.current && ref.current.focus();
    const esc = (e) => e.key === 'Escape' && !savingRef.current && onClose();
    window.addEventListener('keydown', esc);
    return () => window.removeEventListener('keydown', esc);
  }, []);
  const sale = type === 'sale';
  const product = sale ? products.find((p) => String(p[8]) === productId) || null : null;
  const qtyNum = Number(qty);
  const pickProduct = (id) => {
    const item = products.find((p) => String(p[8]) === id);
    setProductId(id);
    setQty('1');
    if (item) setAmt(Number(item[2]).toFixed(2));
  };
  const changeQty = (value) => {
    setQty(value);
    if (product && Number(value) > 0) setAmt((Number(product[2]) * Number(value)).toFixed(2));
  };
  const submit = async (event) => {
    event.preventDefault();
    const amount = parseFloat(amt);
    if (!(amount > 0) || savingRef.current) return;
    if (product) {
      if (!Number.isInteger(qtyNum) || qtyNum < 1) {
        setError('Quantity must be a whole number of at least 1.');
        return;
      }
      if (qtyNum > product[4]) {
        setError(`Only ${product[4]} ${product[0]} in stock.`);
        return;
      }
    }
    savingRef.current = true;
    setSaving(true);
    setError('');
    try {
      await onSave({ who: who.trim() || (sale ? 'Walk-in' : 'General'), a: amount, st, product, qty: qtyNum });
    } catch (saveError) {
      savingRef.current = false;
      setSaving(false);
      setError(saveError.message);
    }
  };
  return (
    <div className='scrim' onClick={() => !saving && onClose()}>
      <form className='sheet' role='dialog' aria-modal='true' aria-labelledby='rt' onClick={(e) => e.stopPropagation()}
        onSubmit={submit}>
        <h2 id='rt'>{sale ? 'Record a sale' : 'Record an expense'}</h2>
        <p>{sale ? 'It is added to this month and updates your totals.' : 'It is added to this month and comes off your profit.'}</p>
        <label>{sale ? 'Customer' : 'Category'}<input ref={ref} type='text' value={who} onChange={(e) => setWho(e.target.value)} placeholder={sale ? 'Walk-in' : 'Utilities'} disabled={saving} /></label>
        {sale && (
          <label>Product
            <select value={productId} onChange={(e) => pickProduct(e.target.value)} disabled={saving}>
              <option value=''>No product</option>
              {products.map((p) => (
                <option key={p[8]} value={String(p[8])} disabled={p[4] <= 0}>
                  {p[4] > 0 ? `${p[0]} · ${p[4]} in stock` : `${p[0]} · out of stock`}
                </option>
              ))}
            </select>
          </label>
        )}
        {product && (
          <label>{`Quantity · ${product[4]} in stock`}
            <input type='number' min='1' max={product[4]} step='1' required value={qty} onChange={(e) => changeQty(e.target.value)} disabled={saving} />
          </label>
        )}
        <label>Amount (USD)<input type='number' min='0' step='0.01' required value={amt} onChange={(e) => setAmt(e.target.value)} disabled={saving} /></label>
        {sale && (
          <div className='nseg' role='group' aria-label='Payment status' style={{ marginBottom: 12 }}>
            {['Paid', 'Pending'].map((s) => <button type='button' key={s} aria-pressed={st === s} onClick={() => setSt(s)} disabled={saving}>{s}</button>)}
          </div>
        )}
        {error && <p className='err' role='alert'>{error}</p>}
        <div className='row'>
          <button type='button' className='btn glass' onClick={onClose} disabled={saving}>Cancel</button>
          <button type='submit' className='btn iri' disabled={saving}>{saving ? 'Saving…' : 'Save'}</button>
        </div>
      </form>
    </div>
  );
}

const PRODUCTS = [];
const NAV = [
  ['overview', 'Overview', 'M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z', 'How your business is doing'],
  ['settings', 'Settings', IC.settings, 'Manage your preferences'],
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

function Dashboard({ dark, setTheme, onExit }) {
  const [isStaff, setIsStaff] = useState(false);
  const [nav, setNav] = useState('overview');
  const [m, setM] = useState(CUR);
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

  useEffect(() => {
    call('/me/', null, localStorage.getItem(TOKEN_KEY)).then((u) => setIsStaff(!!u.is_staff)).catch(() => {});
  }, []);

  useEffect(() => {
    const token = localStorage.getItem(TOKEN_KEY);
    Promise.all([call('/products/', null, token), call('/batches/', null, token), call('/purchases/', null, token)])
      .then(([productList, batchList, orderList]) => {
        setProdList(productList.map(productRow));
        setBatches(batchList.map(batchRow));
        setPurchases(orderList.map(purchaseRow));
      })
      .catch((error) => setStockMsg(error.message));
  }, []);

  const loadFigures = () => {
    const token = localStorage.getItem(TOKEN_KEY);
    return Promise.all([
      call(`/dashboard/?month=${THIS_MONTH}`, null, token),
      call(`/expenses/?month=${THIS_MONTH}`, null, token),
      call('/sales/', null, token),
      call('/reports/', null, token),
    ])
      .then(([figures, expenses, saleList, reports]) => {
        setDash(figures);
        setExpenseSummary(expenses);
        setExpList(expenses.items.map((e) => [e.category, toNum(e.amount), shortDate(e.date)]));
        setSales(saleList.map((s) => [s.customer, toNum(s.amount), s.status, shortDate(s.date), s.product || '', s.product ? s.quantity : 0]));
        setReportRows(reports);
        setDashError('');
      })
      .catch((error) => setDashError(error.message));
  };
  useEffect(() => { loadFigures(); }, []);

  const applyGoal = (data) => {
    setGoalData(data);
    setGoalForm({ amount: data.revenue_goal == null ? '' : String(Number(data.revenue_goal)), period: data.goal_period });
  };
  const persistGoal = async (body, okText) => {
    if (goalLock.current) return;
    goalLock.current = true;
    setGoalBusy(true);
    setGoalMsg({ text: '', error: false });
    try {
      await call('/settings/', body, localStorage.getItem(TOKEN_KEY), 'PATCH');
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

  const loadGoal = () => Promise.all([
    call('/settings/', null, localStorage.getItem(TOKEN_KEY)),
    call('/settings/series/', null, localStorage.getItem(TOKEN_KEY)),
  ]).then(([settings, series]) => {
    applyGoal(settings);
    setGoalChartData(series);
  });
  useEffect(() => {
    if (nav !== 'settings' && nav !== 'overview') return;
    loadGoal().catch((error) => {
      if (nav === 'settings') setGoalMsg({ text: error.message, error: true });
    });
  }, [nav]);

  const D = dash || {};
  const rev = toNum(D.revenue), exp = toNum(D.expenses), gross = toNum(D.gross_profit), net = toNum(D.net_profit);
  const change = (key) => {
    if (!dash) return 'Loading figures';
    const v = D.change_vs_previous_pct[key];
    return v == null ? `No ${PREV_MONTH} figures to compare` : `${v >= 0 ? '+' : ''}${Number(v).toFixed(1)}% vs ${PREV_MONTH}`;
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
  const low = prods.filter((p) => p[5] > 0 && p[4] / p[5] < 0.35 && !ordered[p[0]]);
  const slow = batches.filter((b) => b[3] > 0 && b[4] > limit).sort((a, b) => b[4] - a[4]);
  const pend = sales.filter((s) => s[2] === 'Pending');

  const save = async ({ who, a, st, product, qty }) => {
    const token = localStorage.getItem(TOKEN_KEY);
    if (form === 'sale') {
      const body = { customer: who, amount: a, status: st };
      if (product) Object.assign(body, { product_id: product[8], quantity: qty });
      await call('/sales/', body, token);
      loadFigures();
      loadGoal().catch(() => {});
      if (product) await refreshStock();
    } else {
      await call('/expenses/', { category: who, amount: a }, token);
      loadFigures();
    }
    setM(CUR); setForm(null);
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
      const month = `${NOW.getFullYear()}-${String(NOW.getMonth() + 1).padStart(2, '0')}`;
      const result = await call('/assistant/chat/', { question, month }, localStorage.getItem(TOKEN_KEY));
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
      const month = `${NOW.getFullYear()}-${String(NOW.getMonth() + 1).padStart(2, '0')}`;
      const result = await call('/assistant/analyze/', { analysis: algorithmType, month }, localStorage.getItem(TOKEN_KEY));
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
      const [batchList, orderList] = await Promise.all([call('/batches/', null, token), call('/purchases/', null, token)]);
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
      await call('/purchases/', { product_id: p[8], quantity: Math.max(1, p[5] - p[4]), unit_cost: p[3] }, localStorage.getItem(TOKEN_KEY));
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
      await call(`/purchases/${pu[7]}/receive/`, {}, localStorage.getItem(TOKEN_KEY));
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
      const { product } = await call('/receive/', body, localStorage.getItem(TOKEN_KEY));
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
      {MONTHS.map((x) => <button key={x} aria-pressed={m === x} onClick={() => setM(x)}>{x}</button>)}
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

    settings: () => (
      <div className='dgrid'>
        <section className='dc'>
          <Title ic={IC.settings}>Appearance</Title>
          <p>Choose the theme for your dashboard.</p>
          <div className='nseg' role='group' aria-label='Color theme'>
            <button aria-pressed={!dark} onClick={() => setTheme(false)}>Light</button>
            <button aria-pressed={dark} onClick={() => setTheme(true)}>Dark</button>
          </div>
        </section>
        <section className='dc span2'>
          <Title ic={IC.gross}>Revenue goal</Title>
          <p>Set a sales target for a day, week, month or year. Progress counts only paid sales in the period.</p>
          <form className='nform' onSubmit={saveGoal}>
            <label>Sales goal (USD)
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
      </div>
    ),

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
                <b>{r.n}</b><span>{r.c}</span><span>{money(r.p)}</span><span>{'$' + r.k.toFixed(2)}</span>
                <span className='ncy'>{r.mg.toFixed(0)}%</span><span className={r.s / r.t < 0.35 ? 'nwarn' : ''}>{r.s}</span><span>{r.sold}</span>
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
              <button className='dmini' disabled={ordered[p[0]]} onClick={() => reorder(p)}>{ordered[p[0]] ? 'Ordered ✓' : 'Reorder'}</button>
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
              <label>Product
                <select value={rf.p} onChange={pick}>
                  {prodList.map((p) => <option key={p[0]}>{p[0]}</option>)}
                  <option value='__new'>New product…</option>
                </select>
              </label>
              {isNew && <label>New product name<input type='text' value={rf.name} onChange={set('name')} /></label>}
              {isNew && <label>Selling price (USD)<input type='number' min='0' step='0.01' value={rf.price} onChange={set('price')} /></label>}
              <label>Quantity received<input type='number' min='1' step='1' value={rf.q} onChange={set('q')} /></label>
              <label>Unit cost (USD)<input type='number' min='0' step='0.01' value={rf.c} onChange={set('c')} /></label>
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
                <button className='dmini' onClick={() => receiveOrder(i)}>Mark received</button>
              </div>
            ))}
          </section>
          <section className='dc span3'>
            <Title ic={IC.receipt}>Recently received</Title>
            {recent.map((b) => (
              <div className='npill' key={b[0]}>
                <span className='nin xs'>{b[1][0]}</span><span>{b[1]} × {b[2]}</span>
                <span className='nmut'>{b[6]} · {b[4] === 0 ? 'Today' : b[4] + ' days ago'}</span><b>{'$' + b[5].toFixed(2)} each</b>
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
                  {[30, 45, 60, 90].map((d) => <button key={d} aria-pressed={limit === d} onClick={() => setLimit(d)}>{d}d</button>)}
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
          <Title ic={IC.net}>Forecast for {NEXT[m]}</Title>
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

  const cur = NAV.find((n) => n[0] === nav);
  const showMonth = ['overview', 'products', 'expenses', 'insights'].includes(nav);
  const go = (id) => { setNav(id); setQ(''); window.scrollTo(0, 0); };

  return (
    <div className='dash'>
      <div className='nshell'>
        <nav className='nside' aria-label='Main menu'>
          <div className='nlogo'><span className='nin sm'><Ico d={IC.gross} s={18} /></span>Nexa</div>
          <span className='ngrp'>Menu</span>
          {NAV.map(([id, label, ic], i) => (
            <React.Fragment key={id}>
              {id === 'sales' && <span className='ngrp'>Libraries</span>}
              <button className='nnav' aria-current={nav === id ? 'page' : undefined} onClick={() => go(id)}>
                <span className='nin'><Ico d={ic} s={17} /></span><span className='nlab'>{label}</span>
              </button>
            </React.Fragment>
          ))}
        </nav>

        <main className='nmain'>
          <header className='ntop'>
            <div><h1>{cur[1]}</h1><p>{cur[3]}</p></div>
            <div className='ntools'>
              {showMonth && <Month />}
              {nav !== 'settings' && <>
                <button className='btn iri nbtn' onClick={() => setForm('sale')}>+ Sale</button>
                <button className='btn glass nbtn' onClick={() => setForm('expense')}>+ Expense</button>
              </>}
              {isStaff && <a className='dpill' href={ADMIN_URL} target='_blank' rel='noopener'>Admin</a>}
              <button className='dpill' onClick={onExit}>Sign out</button>
            </div>
          </header>
          <div key={nav} className='nview'>{views[nav]()}</div>
        </main>
      </div>
      {form && <RecordSheet type={form} onClose={() => setForm(null)} onSave={save} products={prods} />}
    </div>
  );
}

function App() {
  const [mode, setMode] = useState(null);
  const [view, setView] = useState('welcome');
  useEffect(() => { document.body.classList.toggle('inapp', view === 'app'); document.body.classList.toggle('welcome', view === 'welcome'); window.scrollTo(0, 0); }, [view]);
  const [dark, setDark] = useState(false);
  const setTheme = (enabled) => { setDark(enabled); document.documentElement.dataset.theme = enabled ? "dark" : "light"; };
  useEffect(() => {
    const t = localStorage.getItem(TOKEN_KEY);
    if (!t) return;
    call("/me/", null, t).then(() => setView('app')).catch((e) => { if (!/reach/.test(e.message)) localStorage.removeItem(TOKEN_KEY); });
  }, []);
  const signOut = () => {
    const t = localStorage.getItem(TOKEN_KEY);
    localStorage.removeItem(TOKEN_KEY);
    if (t) call("/auth/logout/", {}, t).catch(() => {});
    setTheme(false); setView('welcome');
  };
  if (view === 'app') return <Dashboard dark={dark} setTheme={setTheme} onExit={signOut} />;
  return (
    <>
      <div className="landing-page">
        <nav>
          <div className="logo"><i />Nexa</div>
          <button className="btn glass" onClick={() => setMode("signin")}>Sign in</button>
        </nav>
        <main className="hero">
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
      {mode && <Sheet mode={mode} onClose={() => setMode(null)} onEnter={() => { setMode(null); setView('app'); }} onSwitch={setMode} />}
    </>
  );
}
ReactDOM.createRoot(document.getElementById("root")).render(<App />);

/* Original orb: gentle pointer parallax, paused for reduced motion. */
const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
const video = document.getElementById("orb");
if (reduce) { video.removeAttribute("autoplay"); video.pause(); }
else {
  const p = video.play(); if (p && p.catch) p.catch(() => {});
  addEventListener("pointermove", (e) => {
    const r = document.documentElement.style;
    r.setProperty("--px", ((e.clientX / innerWidth - .5) * 28) + "px");
    r.setProperty("--py", ((e.clientY / innerHeight - .5) * 20) + "px");
  });
}
