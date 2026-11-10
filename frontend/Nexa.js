const {
  useState,
  useEffect,
  useLayoutEffect,
  useRef
} = React;
const LOCAL_DEV = location.protocol === "file:" || ["localhost", "127.0.0.1"].includes(location.hostname);
// Locally the API is on port 8000 of the same host as the page, so localhost and 127.0.0.1 both work.
const LOCAL_API_HOST = location.protocol === "file:" ? "localhost" : location.hostname;
const API = window.NEXA_MOBILE ? window.NEXA_API : window.NEXA_API || (LOCAL_DEV ? `http://${LOCAL_API_HOST}:8000/api` : "https://api.Nexa-app.com/api");
// The Django admin lives next to the API.
const ADMIN_URL = API ? API.replace(/\/api\/?$/, "") + "/admin/" : "";
const TOKEN_KEY = "nexa_token";
async function call(path, body, token, method) {
  if (!API) throw new Error("The mobile app's server address has not been configured.");
  let r;
  try {
    r = await fetch(API + path, {
      method: method || (body ? "POST" : "GET"),
      headers: {
        "Content-Type": "application/json",
        ...(token ? {
          Authorization: "Bearer " + token
        } : {})
      },
      body: body ? JSON.stringify(body) : undefined
    });
  } catch (e) {
    throw new Error("Cannot reach the server. Start the backend and try again.");
  }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || (r.status === 404 && path.startsWith("/assistant/") ? "Assistant endpoints are unavailable. Restart Django and reload the app." : "Something went wrong."));
  return data;
}
const IMAGE_TYPES = ['image/png', 'image/jpeg', 'image/webp', 'image/gif'];
const IMAGE_MAX_SIDE = 1024;
const IMAGE_MAX_BYTES = 1024 * 1024;
const readFile = file => new Promise((resolve, reject) => {
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
function Sheet({
  mode,
  onClose,
  onEnter,
  onSwitch
}) {
  const [f, setF] = useState({
    username: "",
    email: "",
    password: "",
    password2: "",
    terms: false
  });
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
  const leave = done => {
    if (leavingRef.current) return;
    leavingRef.current = true;
    setLeaving(true);
    setTimeout(done, reduceMotion() ? 0 : 200);
  };
  useEffect(() => {
    ref.current && ref.current.focus();
    const esc = e => e.key === "Escape" && leave(onClose);
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
  const settleHeight = e => {
    if (e.target !== e.currentTarget || e.propertyName !== "height") return;
    e.currentTarget.style.transition = "";
    e.currentTarget.style.height = "";
    e.currentTarget.style.overflow = "";
  };
  const signup = mode === "signup";
  const set = k => e => setF({
    ...f,
    [k]: k === "terms" ? e.target.checked : e.target.value
  });
  const submit = async e => {
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
      const res = await call(signup ? "/auth/register/" : "/auth/login/", signup ? {
        username: f.username,
        email: f.email,
        password: f.password,
        password2: f.password2,
        accepted_terms: f.terms
      } : {
        username: f.username,
        password: f.password
      });
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
  return /*#__PURE__*/React.createElement("div", {
    className: leaving ? "scrim auth-scrim leaving" : "scrim auth-scrim",
    onClick: () => leave(onClose)
  }, /*#__PURE__*/React.createElement("form", {
    className: leaving ? "sheet auth-sheet leaving" : "sheet auth-sheet",
    ref: sheetRef,
    role: "dialog",
    "aria-modal": "true",
    "aria-labelledby": "st",
    onClick: e => e.stopPropagation(),
    onSubmit: submit,
    onTransitionEnd: settleHeight,
    noValidate: true
  }, /*#__PURE__*/React.createElement("div", {
    className: "hd",
    key: mode
  }, /*#__PURE__*/React.createElement("h2", {
    id: "st"
  }, signup ? "Create your Nexa account" : "Welcome back"), /*#__PURE__*/React.createElement("p", null, signup ? "Choose an email, username and password." : "Sign in with your username and password.")), /*#__PURE__*/React.createElement("label", null, "Username", /*#__PURE__*/React.createElement("input", {
    ref: ref,
    type: "text",
    required: true,
    autoComplete: "username",
    value: f.username,
    onChange: set("username")
  })), signup && /*#__PURE__*/React.createElement("label", null, "Email", /*#__PURE__*/React.createElement("input", {
    type: "email",
    required: true,
    autoComplete: "email",
    value: f.email,
    onChange: set("email")
  })), /*#__PURE__*/React.createElement("label", null, "Password", /*#__PURE__*/React.createElement("input", {
    type: "password",
    required: true,
    autoComplete: signup ? "new-password" : "current-password",
    value: f.password,
    onChange: set("password")
  })), signup && /*#__PURE__*/React.createElement("label", null, "Re-enter password", /*#__PURE__*/React.createElement("input", {
    type: "password",
    required: true,
    autoComplete: "new-password",
    value: f.password2,
    onChange: set("password2")
  })), signup && /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("label", {
    className: "agree"
  }, /*#__PURE__*/React.createElement("input", {
    type: "checkbox",
    checked: f.terms,
    onChange: set("terms")
  }), /*#__PURE__*/React.createElement("span", null, "I accept the ", /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "linkbtn",
    onClick: () => setShowTerms(!showTerms)
  }, "terms and conditions"))), showTerms && /*#__PURE__*/React.createElement("div", {
    className: "terms"
  }, /*#__PURE__*/React.createElement("p", null, "1. Nexa helps you record and review your business activity. You are responsible for the accuracy of what you enter."), /*#__PURE__*/React.createElement("p", null, "2. Keep your password private. You are responsible for activity on your account."), /*#__PURE__*/React.createElement("p", null, "3. We store your account and business records to run the service and do not sell them."), /*#__PURE__*/React.createElement("p", null, "4. Forecasts and ideas are estimates, not financial advice."))), err && /*#__PURE__*/React.createElement("p", {
    className: "err",
    role: "alert"
  }, err), /*#__PURE__*/React.createElement("div", {
    className: "row"
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn glass",
    onClick: () => leave(onClose)
  }, "Cancel"), /*#__PURE__*/React.createElement("button", {
    type: "submit",
    className: busy ? "btn iri busy" : "btn iri",
    disabled: busy
  }, busy ? "Please wait…" : signup ? "Create account" : "Sign in")), /*#__PURE__*/React.createElement("p", {
    className: "switch"
  }, signup ? "Already have an account? " : "New to Nexa? ", /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "linkbtn",
    onClick: () => onSwitch(signup ? "signin" : "signup")
  }, signup ? "Sign in" : "Create one"))));
}
function smoothPath(p) {
  let d = `M${p[0][0]},${p[0][1]}`;
  for (let i = 0; i < p.length - 1; i++) {
    const a = p[i - 1] || p[i],
      b = p[i],
      c = p[i + 1],
      e = p[i + 2] || c;
    d += ` C${b[0] + (c[0] - a[0]) / 6},${b[1] + (c[1] - a[1]) / 6} ${c[0] - (e[0] - b[0]) / 6},${c[1] - (e[1] - b[1]) / 6} ${c[0]},${c[1]}`;
  }
  return d;
}
const money = n => '$' + Math.round(n).toLocaleString('en-US');
const preciseMoney = n => '$' + Number(n).toLocaleString('en-US', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2
});
const wholeOrCents = n => Number.isInteger(n) ? money(n) : preciseMoney(n);
const NOW = new Date();
const CUR = NOW.toLocaleString('en-US', {
  month: 'short'
});
const CUR_NEXT = new Date(NOW.getFullYear(), NOW.getMonth() + 1, 1).toLocaleString('en-US', {
  month: 'short'
});
const MONTHS = [CUR];
const NEXT = {
  [CUR]: CUR_NEXT
};
const THIS_MONTH = `${NOW.getFullYear()}-${String(NOW.getMonth() + 1).padStart(2, '0')}`;
const PREV_MONTH = new Date(NOW.getFullYear(), NOW.getMonth() - 1, 1).toLocaleString('en-US', {
  month: 'short'
});
const toNum = v => Number(v) || 0;
const monthLabel = key => new Date(key + '-01T00:00:00').toLocaleDateString('en-US', {
  month: 'short',
  year: 'numeric'
});
// The series comes from settings/series/. A yearly goal is charted as monthly bars against a twelfth of the goal.
const goalChart = series => {
  const dateOf = iso => new Date(iso + 'T00:00:00');
  const monthShort = iso => dateOf(iso).toLocaleDateString('en-US', {
    month: 'short'
  });
  const monthYear = iso => dateOf(iso).toLocaleDateString('en-US', {
    month: 'short',
    year: 'numeric'
  });
  const target = toNum(series.target);
  const bars = (name, label) => series.buckets.map((b, i) => ({
    name: name(b.start, i),
    label: label(b.start, i),
    value: toNum(b.amount)
  }));
  const charts = {
    day: {
      buckets: bars(shortDate, (iso, i) => i === 0 || (i + 1) % 5 === 0 ? String(i + 1) : ''),
      heading: `Daily sales, ${CUR}`,
      actual: 'Daily sales',
      targetText: `Daily target ${wholeOrCents(target)}`
    },
    week: {
      buckets: bars(iso => `Week of ${shortDate(iso)}`, shortDate),
      heading: 'Weekly sales, last 8 weeks',
      actual: 'Weekly sales',
      targetText: `Weekly target ${wholeOrCents(target)}`
    },
    month: {
      buckets: bars(monthYear, monthShort),
      heading: 'Monthly sales, last 6 months',
      actual: 'Monthly sales',
      targetText: `Monthly target ${wholeOrCents(target)}`
    },
    year: {
      buckets: bars(monthYear, monthShort),
      heading: `Monthly sales, ${dateOf(series.buckets[0].start).getFullYear()}`,
      actual: 'Monthly sales',
      targetText: `Monthly target ${wholeOrCents(target)}`
    }
  };
  return {
    ...charts[series.period],
    current: series.current,
    target
  };
};
const SC = {
  Conservative: 0.97,
  Expected: 1.08,
  Optimistic: 1.2
};
const RECS = [];
const GOAL_PERIODS = [['day', 'Day'], ['week', 'Week'], ['month', 'Month'], ['year', 'Year']];
const GOAL_WORDS = {
  day: 'today',
  week: 'this week',
  month: 'this month',
  year: 'this year'
};
const shortDate = iso => new Date(iso + 'T00:00:00').toLocaleDateString('en-US', {
  month: 'short',
  day: 'numeric'
});
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
  upload: 'M12 16V4M7 9l5-5 5 5M4 16v3a2 2 0 002 2h12a2 2 0 002-2v-3'
};
function Ico({
  d,
  s = 22
}) {
  return /*#__PURE__*/React.createElement("svg", {
    width: s,
    height: s,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: "1.8",
    strokeLinecap: "round",
    strokeLinejoin: "round",
    "aria-hidden": "true"
  }, /*#__PURE__*/React.createElement("path", {
    d: d
  }));
}
function Title({
  ic,
  children,
  right
}) {
  return /*#__PURE__*/React.createElement("div", {
    className: "ct"
  }, /*#__PURE__*/React.createElement("span", {
    className: "nin sm"
  }, /*#__PURE__*/React.createElement(Ico, {
    d: ic,
    s: 18
  })), /*#__PURE__*/React.createElement("span", {
    className: "dlab"
  }, children), right);
}
function Ring({
  pct,
  icon
}) {
  const C = 2 * Math.PI * 34,
    p = Math.max(0, Math.min(100, pct));
  return /*#__PURE__*/React.createElement("div", {
    className: "nring"
  }, /*#__PURE__*/React.createElement("svg", {
    viewBox: "0 0 88 88",
    "aria-hidden": "true"
  }, /*#__PURE__*/React.createElement("circle", {
    cx: "44",
    cy: "44",
    r: "34",
    className: "rt"
  }), /*#__PURE__*/React.createElement("circle", {
    cx: "44",
    cy: "44",
    r: "34",
    className: "rf",
    strokeDasharray: C,
    strokeDashoffset: C * (1 - p / 100),
    transform: "rotate(-90 44 44)"
  })), /*#__PURE__*/React.createElement("span", {
    className: "nin"
  }, /*#__PURE__*/React.createElement(Ico, {
    d: icon,
    s: 22
  })));
}
function Trend({
  series,
  next
}) {
  const vals = [...series, next],
    max = Math.max(...vals, 1) * 1.08;
  const labels = ['Wk 1', 'Wk 2', 'Wk 3', 'Wk 4', 'Next'];
  return /*#__PURE__*/React.createElement("div", {
    className: "nbars",
    role: "img",
    "aria-label": `Weekly sales ${series.map(money).join(', ')} with a forecast of ${money(next)} for next week`
  }, vals.map((v, i) => /*#__PURE__*/React.createElement("div", {
    className: "ncol",
    key: i
  }, /*#__PURE__*/React.createElement("b", null, v >= 1000 ? '$' + (v / 1000).toFixed(1) + 'k' : money(v)), /*#__PURE__*/React.createElement("div", {
    className: "ntrack"
  }, /*#__PURE__*/React.createElement("i", {
    className: i === 4 ? 'fc' : '',
    style: {
      height: v / max * 100 + '%'
    }
  })), /*#__PURE__*/React.createElement("span", null, labels[i]))));
}
function GoalTrend({
  buckets,
  current,
  target,
  label
}) {
  const max = Math.max(...buckets.map(b => b.value), target, 1) * 1.08;
  return /*#__PURE__*/React.createElement("div", {
    className: `nbars${buckets.length > 12 ? ' nday' : ''}`,
    role: "img",
    "aria-label": `${label} against a target of ${wholeOrCents(target)}`
  }, buckets.map((b, i) => /*#__PURE__*/React.createElement("div", {
    className: "ncol",
    key: i,
    title: `${b.name}: ${preciseMoney(b.value)}`
  }, /*#__PURE__*/React.createElement("div", {
    className: "ntrack"
  }, i <= current && /*#__PURE__*/React.createElement("i", {
    style: {
      height: b.value / max * 100 + '%'
    }
  }), /*#__PURE__*/React.createElement("em", {
    className: "ngoal",
    style: {
      bottom: `calc(4px + (100% - 8px) * ${target / max})`
    }
  })), /*#__PURE__*/React.createElement("span", null, b.label))));
}
function RecordSheet({
  type,
  onClose,
  onSave,
  products = []
}) {
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
    const esc = e => e.key === 'Escape' && !savingRef.current && onClose();
    window.addEventListener('keydown', esc);
    return () => window.removeEventListener('keydown', esc);
  }, []);
  const sale = type === 'sale';
  const product = sale ? products.find(p => String(p[8]) === productId) || null : null;
  const qtyNum = Number(qty);
  const pickProduct = id => {
    const item = products.find(p => String(p[8]) === id);
    setProductId(id);
    setQty('1');
    if (item) setAmt(Number(item[2]).toFixed(2));
  };
  const changeQty = value => {
    setQty(value);
    if (product && Number(value) > 0) setAmt((Number(product[2]) * Number(value)).toFixed(2));
  };
  const submit = async event => {
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
      await onSave({
        who: who.trim() || (sale ? 'Walk-in' : 'General'),
        a: amount,
        st,
        product,
        qty: qtyNum
      });
    } catch (saveError) {
      savingRef.current = false;
      setSaving(false);
      setError(saveError.message);
    }
  };
  return /*#__PURE__*/React.createElement("div", {
    className: "scrim",
    onClick: () => !saving && onClose()
  }, /*#__PURE__*/React.createElement("form", {
    className: "sheet",
    role: "dialog",
    "aria-modal": "true",
    "aria-labelledby": "rt",
    onClick: e => e.stopPropagation(),
    onSubmit: submit
  }, /*#__PURE__*/React.createElement("h2", {
    id: "rt"
  }, sale ? 'Record a sale' : 'Record an expense'), /*#__PURE__*/React.createElement("p", null, sale ? 'It is added to this month and updates your totals.' : 'It is added to this month and comes off your profit.'), /*#__PURE__*/React.createElement("label", null, sale ? 'Customer' : 'Category', /*#__PURE__*/React.createElement("input", {
    ref: ref,
    type: "text",
    value: who,
    onChange: e => setWho(e.target.value),
    placeholder: sale ? 'Walk-in' : 'Utilities',
    disabled: saving
  })), sale && /*#__PURE__*/React.createElement("label", null, "Product", /*#__PURE__*/React.createElement("select", {
    value: productId,
    onChange: e => pickProduct(e.target.value),
    disabled: saving
  }, /*#__PURE__*/React.createElement("option", {
    value: ""
  }, "No product"), products.map(p => /*#__PURE__*/React.createElement("option", {
    key: p[8],
    value: String(p[8]),
    disabled: p[4] <= 0
  }, p[4] > 0 ? `${p[0]} · ${p[4]} in stock` : `${p[0]} · out of stock`)))), product && /*#__PURE__*/React.createElement("label", null, `Quantity · ${product[4]} in stock`, /*#__PURE__*/React.createElement("input", {
    type: "number",
    min: "1",
    max: product[4],
    step: "1",
    required: true,
    value: qty,
    onChange: e => changeQty(e.target.value),
    disabled: saving
  })), /*#__PURE__*/React.createElement("label", null, "Amount (USD)", /*#__PURE__*/React.createElement("input", {
    type: "number",
    min: "0",
    step: "0.01",
    required: true,
    value: amt,
    onChange: e => setAmt(e.target.value),
    disabled: saving
  })), sale && /*#__PURE__*/React.createElement("div", {
    className: "nseg",
    role: "group",
    "aria-label": "Payment status",
    style: {
      marginBottom: 12
    }
  }, ['Paid', 'Pending'].map(s => /*#__PURE__*/React.createElement("button", {
    type: "button",
    key: s,
    "aria-pressed": st === s,
    onClick: () => setSt(s),
    disabled: saving
  }, s))), error && /*#__PURE__*/React.createElement("p", {
    className: "err",
    role: "alert"
  }, error), /*#__PURE__*/React.createElement("div", {
    className: "row"
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn glass",
    onClick: onClose,
    disabled: saving
  }, "Cancel"), /*#__PURE__*/React.createElement("button", {
    type: "submit",
    className: "btn iri",
    disabled: saving
  }, saving ? 'Saving…' : 'Save'))));
}
const PRODUCTS = [];
const NAV = [['overview', 'Overview', 'M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z', 'How your business is doing'], ['settings', 'Settings', IC.settings, 'Manage your preferences'], ['sales', 'Sales', IC.receipt, 'Every sale you have recorded'], ['products', 'Products', 'M20 12l-8 8-9-9V3h8zM7.5 7.5h.01', 'Prices, margins and what sells most'], ['stock', 'Stock', IC.box, 'Stock levels, purchases and suppliers'], ['receive', 'Receive stock', 'M12 3v12M7 10l5 5 5-5M4 20h16', 'Record stock coming in'], ['slow', 'Slow stock', 'M12 7v5l3 2M21 12a9 9 0 11-3-6.7M21 4v5h-5', 'Stock that has stayed too long'], ['expenses', 'Expenses', IC.exp, 'Where your money goes'], ['customers', 'Customers', 'M16 20v-1a4 4 0 00-4-4H8a4 4 0 00-4 4v1M10 11a3.5 3.5 0 100-7 3.5 3.5 0 000 7zM20 20v-1a3.5 3.5 0 00-2.5-3.3M16 4.3a3.5 3.5 0 010 6.4', 'Your regulars and their history'], ['reports', 'Reports', 'M7 3h8l4 4v14H7zM15 3v4h4M10 12h6M10 16h6', 'Month by month results'], ['insights', 'Insights', IC.bulb, 'Forecasts and smart ideas']];
const BATCHES0 = [];

// image_url is an API-relative path, so it is resolved against the API base.
const productImage = path => path ? new URL(path + '?size=400', API).href : '';
// Maps API rows to the tuple shapes the dashboard keeps in state.
const productRow = p => [p.name, p.category, Number(p.price), Number(p.cost), 0, p.target_stock, p.supplier || '', productImage(p.image_url), p.id];
const batchRow = b => [b.id, b.product, b.quantity_received, b.quantity_left, b.age_days, Number(b.unit_cost), b.supplier || ''];
const dateLabel = iso => {
  if (!iso) return '';
  const d = new Date(iso + 'T00:00:00');
  return d.toLocaleString('en-US', {
    month: 'short'
  }) + ' ' + d.getDate();
};
const purchaseRow = p => [`${p.product} × ${p.quantity}`, p.supplier || '', Math.round(Number(p.total)), p.status, dateLabel(p.status === 'Delivered' ? p.delivered_on : p.ordered_on), p.product, p.quantity, p.id];
function Dashboard({
  dark,
  setTheme,
  onExit
}) {
  const [isStaff, setIsStaff] = useState(false);
  const [nav, setNav] = useState('overview');
  const [m, setM] = useState(CUR);
  const [scn, setScn] = useState('Expected');
  const [pri, setPri] = useState('All');
  const [done, setDone] = useState({});
  const [dash, setDash] = useState(null);
  const [dashError, setDashError] = useState('');
  const [expenseSummary, setExpenseSummary] = useState({
    items: [],
    by_category: []
  });
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
  const [rf, setRf] = useState({
    p: '__new',
    q: '',
    c: '',
    s: '',
    name: '',
    price: '',
    img: '',
    imgName: ''
  });
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
  const [goalForm, setGoalForm] = useState({
    amount: '',
    period: 'month'
  });
  const [goalMsg, setGoalMsg] = useState({
    text: '',
    error: false
  });
  const [goalBusy, setGoalBusy] = useState(false);
  const goalLock = useRef(false);
  useEffect(() => {
    call('/me/', null, localStorage.getItem(TOKEN_KEY)).then(u => setIsStaff(!!u.is_staff)).catch(() => {});
  }, []);
  useEffect(() => {
    const token = localStorage.getItem(TOKEN_KEY);
    Promise.all([call('/products/', null, token), call('/batches/', null, token), call('/purchases/', null, token)]).then(([productList, batchList, orderList]) => {
      setProdList(productList.map(productRow));
      setBatches(batchList.map(batchRow));
      setPurchases(orderList.map(purchaseRow));
    }).catch(error => setStockMsg(error.message));
  }, []);
  const loadFigures = () => {
    const token = localStorage.getItem(TOKEN_KEY);
    return Promise.all([call(`/dashboard/?month=${THIS_MONTH}`, null, token), call(`/expenses/?month=${THIS_MONTH}`, null, token), call('/sales/', null, token), call('/reports/', null, token)]).then(([figures, expenses, saleList, reports]) => {
      setDash(figures);
      setExpenseSummary(expenses);
      setExpList(expenses.items.map(e => [e.category, toNum(e.amount), shortDate(e.date)]));
      setSales(saleList.map(s => [s.customer, toNum(s.amount), s.status, shortDate(s.date), s.product || '', s.product ? s.quantity : 0]));
      setReportRows(reports);
      setDashError('');
    }).catch(error => setDashError(error.message));
  };
  useEffect(() => {
    loadFigures();
  }, []);
  const applyGoal = data => {
    setGoalData(data);
    setGoalForm({
      amount: data.revenue_goal == null ? '' : String(Number(data.revenue_goal)),
      period: data.goal_period
    });
  };
  const persistGoal = async (body, okText) => {
    if (goalLock.current) return;
    goalLock.current = true;
    setGoalBusy(true);
    setGoalMsg({
      text: '',
      error: false
    });
    try {
      await call('/settings/', body, localStorage.getItem(TOKEN_KEY), 'PATCH');
      await loadGoal();
      setGoalMsg({
        text: okText,
        error: false
      });
    } catch (error) {
      setGoalMsg({
        text: error.message,
        error: true
      });
    } finally {
      goalLock.current = false;
      setGoalBusy(false);
    }
  };
  const saveGoal = e => {
    e.preventDefault();
    const amount = parseFloat(goalForm.amount);
    if (!(amount > 0)) return setGoalMsg({
      text: 'Enter a sales goal above zero.',
      error: true
    });
    persistGoal({
      revenue_goal: amount,
      goal_period: goalForm.period
    }, `Goal saved: ${preciseMoney(amount)} per ${goalForm.period}.`);
  };
  const clearGoal = () => persistGoal({
    revenue_goal: null
  }, 'Revenue goal cleared.');
  const loadGoal = () => Promise.all([call('/settings/', null, localStorage.getItem(TOKEN_KEY)), call('/settings/series/', null, localStorage.getItem(TOKEN_KEY))]).then(([settings, series]) => {
    applyGoal(settings);
    setGoalChartData(series);
  });
  useEffect(() => {
    if (nav !== 'settings' && nav !== 'overview') return;
    loadGoal().catch(error => {
      if (nav === 'settings') setGoalMsg({
        text: error.message,
        error: true
      });
    });
  }, [nav]);
  const D = dash || {};
  const rev = toNum(D.revenue),
    exp = toNum(D.expenses),
    gross = toNum(D.gross_profit),
    net = toNum(D.net_profit);
  const change = key => {
    if (!dash) return 'Loading figures';
    const v = D.change_vs_previous_pct[key];
    return v == null ? `No ${PREV_MONTH} figures to compare` : `${v >= 0 ? '+' : ''}${Number(v).toFixed(1)}% vs ${PREV_MONTH}`;
  };
  const series = (D.weekly_sales || [0, 0, 0, 0]).map(toNum);
  const goalSeries = goalChartData ? goalChart(goalChartData) : null;
  const fc = D.forecast && D.forecast[scn] || {
    next_week: 0,
    next_month: 0
  };
  const factor = SC[scn];
  const nextWeek = Math.round(toNum(fc.next_week)),
    nextTotal = Math.round(toNum(fc.next_month));
  const top = (D.top_products || []).map(p => [p.name, toNum(p.units)]);
  const maxUnits = top.length ? top[0][1] : 1;
  const cats = (expenseSummary.by_category || []).map(c => [c.category, toNum(c.total)]);
  const maxCat = Math.max(...cats.map(c => c[1]), 1);
  const pendingCount = toNum(D.pending_payments && D.pending_payments.count);
  const pendingTotal = toNum(D.pending_payments && D.pending_payments.total);
  const recs = RECS.filter(r => pri === 'All' || r.pri === pri);
  const sold = Object.fromEntries(top);
  const stockOf = n => batches.filter(b => b[1] === n).reduce((a, b) => a + b[3], 0);
  const ordered = Object.fromEntries(purchases.filter(x => x[3] === 'Ordered').map(x => [x[5], true]));
  const prods = prodList.map(p => [p[0], p[1], p[2], p[3], stockOf(p[0]), p[5], p[6], p[7] || '', p[8]]);
  const low = prods.filter(p => p[5] > 0 && p[4] / p[5] < 0.35 && !ordered[p[0]]);
  const slow = batches.filter(b => b[3] > 0 && b[4] > limit).sort((a, b) => b[4] - a[4]);
  const pend = sales.filter(s => s[2] === 'Pending');
  const save = async ({
    who,
    a,
    st,
    product,
    qty
  }) => {
    const token = localStorage.getItem(TOKEN_KEY);
    if (form === 'sale') {
      const body = {
        customer: who,
        amount: a,
        status: st
      };
      if (product) Object.assign(body, {
        product_id: product[8],
        quantity: qty
      });
      await call('/sales/', body, token);
      loadFigures();
      loadGoal().catch(() => {});
      if (product) await refreshStock();
    } else {
      await call('/expenses/', {
        category: who,
        amount: a
      }, token);
      loadFigures();
    }
    setM(CUR);
    setForm(null);
  };
  const askAssistant = async event => {
    event.preventDefault();
    const question = assistantQuestion.trim();
    if (!question || assistantLock.current) return;
    assistantLock.current = true;
    setAssistantQuestion('');
    setAssistantError('');
    setAssistantMessages(messages => [...messages, {
      role: 'user',
      text: question
    }]);
    setAssistantBusy(true);
    try {
      const month = `${NOW.getFullYear()}-${String(NOW.getMonth() + 1).padStart(2, '0')}`;
      const result = await call('/assistant/chat/', {
        question,
        month
      }, localStorage.getItem(TOKEN_KEY));
      setAssistantMessages(messages => [...messages, {
        role: 'assistant',
        text: result.answer
      }]);
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
      const result = await call('/assistant/analyze/', {
        analysis: algorithmType,
        month
      }, localStorage.getItem(TOKEN_KEY));
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
  const reorder = async p => {
    if (orderLock.current) return;
    orderLock.current = true;
    try {
      await call('/purchases/', {
        product_id: p[8],
        quantity: Math.max(1, p[5] - p[4]),
        unit_cost: p[3]
      }, localStorage.getItem(TOKEN_KEY));
      setStockMsg('');
      await refreshStock();
    } catch (error) {
      setStockMsg(error.message);
    } finally {
      orderLock.current = false;
    }
  };
  const receiveOrder = async i => {
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
  const submitReceive = async e => {
    e.preventDefault();
    if (receiveLock.current) return;
    const qty = parseInt(rf.q, 10),
      cost = parseFloat(rf.c),
      price = parseFloat(rf.price);
    if (!(qty > 0) || !(cost > 0)) return setRmsg('Enter a quantity and a unit cost above zero.');
    if (!rf.s.trim()) return setRmsg('Enter the supplier name.');
    const supplier = rf.s.trim();
    const isNew = rf.p === '__new';
    const existing = isNew ? null : prodList.find(p => p[0] === rf.p);
    if (!isNew && !existing) return setRmsg('Choose a product from the list.');
    let name = rf.p;
    const body = {
      quantity: qty,
      unit_cost: cost,
      supplier
    };
    if (isNew) {
      name = rf.name.trim();
      if (!name) return setRmsg('Give the new product a name.');
      const match = prodList.find(p => p[0].toLowerCase() === name.toLowerCase());
      if (match) {
        name = match[0];
        body.product_id = match[8];
      } else {
        if (!(price > 0)) return setRmsg('Give the new product a selling price.');
        Object.assign(body, {
          new_product_name: name,
          price
        });
      }
    } else {
      body.product_id = existing[8];
    }
    if (rf.img) body.image = rf.img;
    receiveLock.current = true;
    setReceiveBusy(true);
    try {
      const {
        product
      } = await call('/receive/', body, localStorage.getItem(TOKEN_KEY));
      setProdList(l => l.some(p => p[8] === product.id) ? l.map(p => p[8] === product.id ? productRow(product) : p) : [...l, productRow(product)]);
      await refreshStock();
      setRf({
        p: '__new',
        q: '',
        c: '',
        s: '',
        name: '',
        price: '',
        img: '',
        imgName: ''
      });
      if (imgRef.current) imgRef.current.value = '';
      setRmsg(`${qty} × ${name} added to stock.`);
    } catch (error) {
      setRmsg(error.message);
    } finally {
      receiveLock.current = false;
      setReceiveBusy(false);
    }
  };
  const pc = a => rev > 0 ? a / rev * 100 : 0;
  const goalProgress = goalData && goalData.progress;
  const goalPct = goalProgress ? goalProgress.percent : null;
  const goalCap = goalProgress ? `of the ${money(Number(goalProgress.goal))} goal ${GOAL_WORDS[goalProgress.period]}` : 'Set a revenue goal in Settings';
  const kpis = [['Revenue', rev, change('revenue'), goalPct, IC.rev, goalCap], ['Gross profit', gross, change('gross_profit'), pc(gross), IC.gross, 'margin'], ['Expenses', exp, change('expenses'), pc(exp), IC.exp, 'of revenue'], ['Net profit', net, change('net_profit'), pc(net), IC.net, 'margin']];
  const Month = () => /*#__PURE__*/React.createElement("div", {
    className: "nseg",
    role: "group",
    "aria-label": "Month"
  }, MONTHS.map(x => /*#__PURE__*/React.createElement("button", {
    key: x,
    "aria-pressed": m === x,
    onClick: () => setM(x)
  }, x)));
  const Bar = ({
    pct
  }) => /*#__PURE__*/React.createElement("div", {
    className: "dbar thin"
  }, /*#__PURE__*/React.createElement("i", {
    style: {
      width: Math.min(100, pct) + '%'
    }
  }));
  const views = {
    overview: () => /*#__PURE__*/React.createElement(React.Fragment, null, dashError && /*#__PURE__*/React.createElement("p", {
      className: "nerr",
      role: "alert"
    }, dashError), /*#__PURE__*/React.createElement("div", {
      className: "kpis"
    }, kpis.map(([l, v, d, p, ic, cap]) => /*#__PURE__*/React.createElement("div", {
      className: "kpi flat metric",
      key: l
    }, /*#__PURE__*/React.createElement("div", {
      className: "kpi-head"
    }, /*#__PURE__*/React.createElement("span", {
      className: "dlab"
    }, l), /*#__PURE__*/React.createElement(Ring, {
      pct: p,
      icon: ic
    })), /*#__PURE__*/React.createElement("b", null, money(v)), /*#__PURE__*/React.createElement("small", null, p == null ? cap : `${Math.round(Math.max(0, Math.min(999, p)))}% ${cap}`), /*#__PURE__*/React.createElement("small", {
      className: "kd"
    }, d)))), /*#__PURE__*/React.createElement("div", {
      className: "dgrid"
    }, /*#__PURE__*/React.createElement("section", {
      className: "dc span2"
    }, goalSeries == null ? /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement(Title, {
      ic: IC.gross,
      right: /*#__PURE__*/React.createElement("span", {
        className: "nleg"
      }, /*#__PURE__*/React.createElement("i", null), "Actual", /*#__PURE__*/React.createElement("i", {
        className: "fc"
      }), "Forecast")
    }, "Sales by week, ", m), /*#__PURE__*/React.createElement(Trend, {
      series: series,
      next: nextWeek,
      key: m + scn + rev
    })) : /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement(Title, {
      ic: IC.gross,
      right: /*#__PURE__*/React.createElement("span", {
        className: "nleg"
      }, /*#__PURE__*/React.createElement("i", null), goalSeries.actual, /*#__PURE__*/React.createElement("i", {
        className: "gl"
      }), goalSeries.targetText)
    }, goalSeries.heading), /*#__PURE__*/React.createElement(GoalTrend, {
      key: goalData.goal_period,
      buckets: goalSeries.buckets,
      current: goalSeries.current,
      target: goalSeries.target,
      label: goalSeries.heading
    }))), /*#__PURE__*/React.createElement("section", {
      className: "dc"
    }, /*#__PURE__*/React.createElement(Title, {
      ic: IC.star
    }, "Best sellers, ", m), /*#__PURE__*/React.createElement("ol", {
      className: "nlist"
    }, top.length === 0 && /*#__PURE__*/React.createElement("li", null, /*#__PURE__*/React.createElement("p", null, "No sales recorded yet.")), top.slice(0, 4).map(([n, u], i) => /*#__PURE__*/React.createElement("li", {
      key: n
    }, /*#__PURE__*/React.createElement("div", {
      className: "nrow2"
    }, /*#__PURE__*/React.createElement("span", null, n, i === 0 && /*#__PURE__*/React.createElement("em", {
      className: "ntag"
    }, "Top seller")), /*#__PURE__*/React.createElement("span", null, u, " sold")), /*#__PURE__*/React.createElement("div", {
      className: "dbar"
    }, /*#__PURE__*/React.createElement("i", {
      style: {
        width: u / maxUnits * 100 + '%'
      }
    })))))), [['stock', IC.box, 'Needs attention', `${low.length} low on stock and ${slow.length} batch${slow.length === 1 ? '' : 'es'} sitting longer than ${limit} days.`, 'Open stock'], ['sales', IC.receipt, 'Waiting on payment', `${pendingCount} sale${pendingCount === 1 ? '' : 's'} pending, worth ${money(pendingTotal)}.`, 'Open sales'], ['insights', IC.bulb, 'Top idea', RECS.length ? RECS[0].text : 'Ideas will appear once you have recorded some activity.', 'See all ideas']].map(([id, ic, t, txt, btn]) => /*#__PURE__*/React.createElement("section", {
      className: "dc",
      key: id
    }, /*#__PURE__*/React.createElement(Title, {
      ic: ic
    }, t), /*#__PURE__*/React.createElement("p", null, txt), /*#__PURE__*/React.createElement("button", {
      className: "dmini self",
      onClick: () => setNav(id)
    }, btn))))),
    settings: () => /*#__PURE__*/React.createElement("div", {
      className: "dgrid"
    }, /*#__PURE__*/React.createElement("section", {
      className: "dc"
    }, /*#__PURE__*/React.createElement(Title, {
      ic: IC.settings
    }, "Appearance"), /*#__PURE__*/React.createElement("p", null, "Choose the theme for your dashboard."), /*#__PURE__*/React.createElement("div", {
      className: "nseg",
      role: "group",
      "aria-label": "Color theme"
    }, /*#__PURE__*/React.createElement("button", {
      "aria-pressed": !dark,
      onClick: () => setTheme(false)
    }, "Light"), /*#__PURE__*/React.createElement("button", {
      "aria-pressed": dark,
      onClick: () => setTheme(true)
    }, "Dark"))), /*#__PURE__*/React.createElement("section", {
      className: "dc span2"
    }, /*#__PURE__*/React.createElement(Title, {
      ic: IC.gross
    }, "Revenue goal"), /*#__PURE__*/React.createElement("p", null, "Set a sales target for a day, week, month or year. Progress counts only paid sales in the period."), /*#__PURE__*/React.createElement("form", {
      className: "nform",
      onSubmit: saveGoal
    }, /*#__PURE__*/React.createElement("label", null, "Sales goal (USD)", /*#__PURE__*/React.createElement("input", {
      type: "number",
      min: "0",
      step: "0.01",
      value: goalForm.amount,
      onChange: e => setGoalForm(f => ({
        ...f,
        amount: e.target.value
      }))
    })), /*#__PURE__*/React.createElement("div", {
      className: "goal-period"
    }, /*#__PURE__*/React.createElement("span", null, "Goal period"), /*#__PURE__*/React.createElement("div", {
      className: "nseg",
      role: "group",
      "aria-label": "Goal period"
    }, GOAL_PERIODS.map(([v, label]) => /*#__PURE__*/React.createElement("button", {
      key: v,
      type: "button",
      "aria-pressed": goalForm.period === v,
      onClick: () => setGoalForm(f => ({
        ...f,
        period: v
      }))
    }, label)))), /*#__PURE__*/React.createElement("div", {
      className: "goal-actions"
    }, /*#__PURE__*/React.createElement("button", {
      type: "submit",
      className: "btn iri nbtn",
      disabled: goalBusy
    }, goalBusy ? 'Saving…' : 'Save goal'), /*#__PURE__*/React.createElement("button", {
      type: "button",
      className: "btn glass",
      disabled: goalBusy || !goalData || goalData.revenue_goal == null,
      onClick: clearGoal
    }, "Clear goal"))), goalMsg.text && /*#__PURE__*/React.createElement("p", {
      className: goalMsg.error ? 'nerr' : 'nok',
      role: goalMsg.error ? 'alert' : 'status'
    }, goalMsg.text), goalData && goalData.progress && /*#__PURE__*/React.createElement("div", {
      className: "goal-progress"
    }, /*#__PURE__*/React.createElement("div", {
      className: "nrow2"
    }, /*#__PURE__*/React.createElement("span", null, preciseMoney(Number(goalData.progress.revenue)), " of ", preciseMoney(Number(goalData.progress.goal)), " ", GOAL_WORDS[goalData.progress.period]), /*#__PURE__*/React.createElement("span", null, goalData.progress.percent, "%")), /*#__PURE__*/React.createElement(Bar, {
      pct: goalData.progress.percent
    }), /*#__PURE__*/React.createElement("p", null, Number(goalData.progress.remaining) > 0 ? `${preciseMoney(Number(goalData.progress.remaining))} left to reach the goal.` : 'Goal reached.', " Period: ", shortDate(goalData.progress.start), " to ", shortDate(goalData.progress.end), ".")))),
    sales: () => {
      const list = sales.filter(s => (sf === 'All' || s[2] === sf) && s[0].toLowerCase().includes(q.toLowerCase()));
      const paid = sales.filter(s => s[2] === 'Paid').reduce((a, s) => a + s[1], 0);
      const pendAmt = pend.reduce((a, s) => a + s[1], 0);
      return /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
        className: "kpis three"
      }, [['Paid', money(paid), 'received so far'], ['Pending', money(pendAmt), `${pend.length} sales waiting`], ['Records', sales.length, 'sales logged']].map(([l, v, s]) => /*#__PURE__*/React.createElement("div", {
        className: "kpi flat",
        key: l
      }, /*#__PURE__*/React.createElement("span", {
        className: "dlab"
      }, l), /*#__PURE__*/React.createElement("b", null, v), /*#__PURE__*/React.createElement("small", null, s)))), /*#__PURE__*/React.createElement("section", {
        className: "dc"
      }, /*#__PURE__*/React.createElement("div", {
        className: "ct"
      }, /*#__PURE__*/React.createElement("input", {
        className: "nsearch",
        placeholder: "Search customer",
        value: q,
        onChange: e => setQ(e.target.value),
        "aria-label": "Search sales by customer"
      }), /*#__PURE__*/React.createElement("div", {
        className: "nseg sm",
        role: "group",
        "aria-label": "Filter by status"
      }, ['All', 'Paid', 'Pending'].map(f => /*#__PURE__*/React.createElement("button", {
        key: f,
        "aria-pressed": sf === f,
        onClick: () => setSf(f)
      }, f)))), list.length === 0 && /*#__PURE__*/React.createElement("p", null, "No sales match your search."), list.map(([w, a, s, d, p, q], i) => /*#__PURE__*/React.createElement("div", {
        className: "npill",
        key: w + i + d
      }, /*#__PURE__*/React.createElement("span", {
        className: "nin xs"
      }, w[0]), /*#__PURE__*/React.createElement("span", null, w), /*#__PURE__*/React.createElement("span", {
        className: "nmut"
      }, p ? `${d} · ${p} × ${q}` : d), /*#__PURE__*/React.createElement("b", null, money(a)), /*#__PURE__*/React.createElement("span", {
        className: 'chipS ' + (s === 'Paid' ? 'paid' : 'pend')
      }, s)))));
    },
    products: () => {
      const rows = prods.map(([n, c, p, k, s, t, sup]) => ({
        n,
        c,
        p,
        k,
        s,
        t,
        sold: sold[n] || 0,
        mg: p > 0 ? (p - k) / p * 100 : 0
      })).filter(r => r.n.toLowerCase().includes(q.toLowerCase())).sort((a, b) => sort === 'name' ? a.n.localeCompare(b.n) : sort === 'margin' ? b.mg - a.mg : sort === 'stock' ? a.s - b.s : b.sold - a.sold);
      const H = ({
        k,
        children
      }) => /*#__PURE__*/React.createElement("button", {
        "aria-pressed": sort === k,
        onClick: () => setSort(k)
      }, children);
      return /*#__PURE__*/React.createElement("section", {
        className: "dc"
      }, /*#__PURE__*/React.createElement("div", {
        className: "ct"
      }, /*#__PURE__*/React.createElement("input", {
        className: "nsearch",
        placeholder: "Search products",
        value: q,
        onChange: e => setQ(e.target.value),
        "aria-label": "Search products"
      }), /*#__PURE__*/React.createElement("span", {
        className: "nmut ml"
      }, "Sorted by ", sort)), /*#__PURE__*/React.createElement("div", {
        className: "nscroll"
      }, /*#__PURE__*/React.createElement("div", {
        className: "ntable"
      }, /*#__PURE__*/React.createElement("div", {
        className: "nth"
      }, /*#__PURE__*/React.createElement(H, {
        k: "name"
      }, "Product"), /*#__PURE__*/React.createElement("span", null, "Category"), /*#__PURE__*/React.createElement("span", null, "Price"), /*#__PURE__*/React.createElement("span", null, "Cost"), /*#__PURE__*/React.createElement(H, {
        k: "margin"
      }, "Margin"), /*#__PURE__*/React.createElement(H, {
        k: "stock"
      }, "Stock"), /*#__PURE__*/React.createElement(H, {
        k: "sold"
      }, "Sold, ", m)), rows.map(r => /*#__PURE__*/React.createElement("div", {
        className: "ntr",
        key: r.n
      }, /*#__PURE__*/React.createElement("b", null, r.n), /*#__PURE__*/React.createElement("span", null, r.c), /*#__PURE__*/React.createElement("span", null, money(r.p)), /*#__PURE__*/React.createElement("span", null, '$' + r.k.toFixed(2)), /*#__PURE__*/React.createElement("span", {
        className: "ncy"
      }, r.mg.toFixed(0), "%"), /*#__PURE__*/React.createElement("span", {
        className: r.s / r.t < 0.35 ? 'nwarn' : ''
      }, r.s), /*#__PURE__*/React.createElement("span", null, r.sold))))));
    },
    stock: () => /*#__PURE__*/React.createElement("div", {
      className: "dgrid"
    }, /*#__PURE__*/React.createElement("section", {
      className: "dc span2"
    }, /*#__PURE__*/React.createElement(Title, {
      ic: IC.box
    }, "Stock levels"), stockMsg && /*#__PURE__*/React.createElement("p", {
      className: "nerr",
      role: "alert"
    }, stockMsg), prods.length === 0 && !stockMsg && /*#__PURE__*/React.createElement("p", null, "No products yet. Add one on the Receive stock page."), prods.map(p => /*#__PURE__*/React.createElement("div", {
      className: "nstock row",
      key: p[0]
    }, p[7] ? /*#__PURE__*/React.createElement("img", {
      className: "pimg",
      src: p[7],
      alt: p[0]
    }) : /*#__PURE__*/React.createElement("span", {
      className: "nin"
    }, p[0][0]), /*#__PURE__*/React.createElement("div", {
      className: "grow"
    }, /*#__PURE__*/React.createElement("div", {
      className: "nrow2"
    }, /*#__PURE__*/React.createElement("span", null, p[0]), /*#__PURE__*/React.createElement("span", null, p[4], " of ", p[5])), /*#__PURE__*/React.createElement(Bar, {
      pct: p[4] / p[5] * 100
    })), /*#__PURE__*/React.createElement("button", {
      className: "dmini",
      disabled: ordered[p[0]],
      onClick: () => reorder(p)
    }, ordered[p[0]] ? 'Ordered ✓' : 'Reorder')))), /*#__PURE__*/React.createElement("section", {
      className: "dc"
    }, /*#__PURE__*/React.createElement(Title, {
      ic: IC.star
    }, "Suppliers"), [...new Set(batches.map(b => b[6]))].map(n => /*#__PURE__*/React.createElement("div", {
      className: "npill col",
      key: n
    }, /*#__PURE__*/React.createElement("b", {
      className: "l"
    }, n))), batches.length === 0 && !stockMsg && /*#__PURE__*/React.createElement("p", null, "No suppliers yet.")), /*#__PURE__*/React.createElement("section", {
      className: "dc span3"
    }, /*#__PURE__*/React.createElement(Title, {
      ic: IC.receipt
    }, "Purchases"), purchases.length === 0 && !stockMsg && /*#__PURE__*/React.createElement("p", null, "No purchases yet."), purchases.map(([it, sup, c, st, d], i) => /*#__PURE__*/React.createElement("div", {
      className: "npill",
      key: it + i
    }, /*#__PURE__*/React.createElement("span", {
      className: "nin xs"
    }, sup.slice(-1)), /*#__PURE__*/React.createElement("span", null, it), /*#__PURE__*/React.createElement("span", {
      className: "nmut"
    }, sup, " \xB7 ", d), /*#__PURE__*/React.createElement("b", null, money(c)), /*#__PURE__*/React.createElement("span", {
      className: 'chipS ' + (st === 'Delivered' ? 'paid' : 'pend')
    }, st))))),
    receive: () => {
      const orders = purchases.map((x, i) => [x, i]).filter(([x]) => x[3] === 'Ordered');
      const recent = [...batches].sort((a, b) => a[4] - b[4]).slice(0, 6);
      const isNew = rf.p === '__new';
      const set = k => e => setRf({
        ...rf,
        [k]: e.target.value
      });
      const current = isNew ? null : prodList.find(p => p[0] === rf.p);
      const preview = rf.img || current && current[7] || '';
      const pick = e => {
        const v = e.target.value;
        const pr = prodList.find(p => p[0] === v);
        setRf({
          ...rf,
          p: v,
          c: pr ? String(pr[3]) : rf.c,
          s: pr ? pr[6] : rf.s,
          img: '',
          imgName: ''
        });
        if (imgRef.current) imgRef.current.value = '';
      };
      const pickImage = async e => {
        const file = e.target.files && e.target.files[0];
        if (!file) return setRf(f => ({
          ...f,
          img: '',
          imgName: ''
        }));
        try {
          const img = await shrinkImage(file);
          setRf(f => ({
            ...f,
            img,
            imgName: file.name
          }));
          setRmsg('');
        } catch (error) {
          e.target.value = '';
          setRf(f => ({
            ...f,
            img: '',
            imgName: ''
          }));
          setRmsg(error.message);
        }
      };
      return /*#__PURE__*/React.createElement("div", {
        className: "dgrid"
      }, /*#__PURE__*/React.createElement("section", {
        className: "dc span2"
      }, /*#__PURE__*/React.createElement(Title, {
        ic: NAV.find(x => x[0] === 'receive')[2]
      }, "Enter new stock"), /*#__PURE__*/React.createElement("form", {
        className: "nform",
        onSubmit: submitReceive
      }, /*#__PURE__*/React.createElement("label", null, "Product", /*#__PURE__*/React.createElement("select", {
        value: rf.p,
        onChange: pick
      }, prodList.map(p => /*#__PURE__*/React.createElement("option", {
        key: p[0]
      }, p[0])), /*#__PURE__*/React.createElement("option", {
        value: "__new"
      }, "New product\u2026"))), isNew && /*#__PURE__*/React.createElement("label", null, "New product name", /*#__PURE__*/React.createElement("input", {
        type: "text",
        value: rf.name,
        onChange: set('name')
      })), isNew && /*#__PURE__*/React.createElement("label", null, "Selling price (USD)", /*#__PURE__*/React.createElement("input", {
        type: "number",
        min: "0",
        step: "0.01",
        value: rf.price,
        onChange: set('price')
      })), /*#__PURE__*/React.createElement("label", null, "Quantity received", /*#__PURE__*/React.createElement("input", {
        type: "number",
        min: "1",
        step: "1",
        value: rf.q,
        onChange: set('q')
      })), /*#__PURE__*/React.createElement("label", null, "Unit cost (USD)", /*#__PURE__*/React.createElement("input", {
        type: "number",
        min: "0",
        step: "0.01",
        value: rf.c,
        onChange: set('c')
      })), /*#__PURE__*/React.createElement("label", null, "Supplier", /*#__PURE__*/React.createElement("input", {
        type: "text",
        list: "supl",
        value: rf.s,
        onChange: set('s')
      }), /*#__PURE__*/React.createElement("datalist", {
        id: "supl"
      }, [...new Set(batches.map(b => b[6]))].map(n => /*#__PURE__*/React.createElement("option", {
        key: n,
        value: n
      })))), /*#__PURE__*/React.createElement("div", {
        className: "photo-field"
      }, /*#__PURE__*/React.createElement("span", null, "Product photo (optional)"), /*#__PURE__*/React.createElement("input", {
        ref: imgRef,
        type: "file",
        className: "photo-input",
        tabIndex: -1,
        "aria-hidden": "true",
        accept: "image/png,image/jpeg,image/webp,image/gif",
        onChange: pickImage
      }), /*#__PURE__*/React.createElement("div", {
        className: "photo-drop"
      }, /*#__PURE__*/React.createElement("span", {
        className: "photo-thumb"
      }, preview ? /*#__PURE__*/React.createElement("img", {
        src: preview,
        alt: "Product photo preview"
      }) : /*#__PURE__*/React.createElement(Ico, {
        d: IC.upload,
        s: 24
      })), /*#__PURE__*/React.createElement("div", {
        className: "photo-copy"
      }, /*#__PURE__*/React.createElement("button", {
        type: "button",
        className: "btn glass photo-btn",
        disabled: receiveBusy,
        "aria-describedby": "photo-hint",
        onClick: () => imgRef.current && imgRef.current.click()
      }, /*#__PURE__*/React.createElement(Ico, {
        d: IC.upload,
        s: 16
      }), "Upload image"), /*#__PURE__*/React.createElement("span", {
        id: "photo-hint",
        className: "photo-hint"
      }, rf.imgName || (current && current[7] ? 'Current photo. Upload a new image to replace it.' : 'Choose a PNG, JPG, WebP or GIF up to 1 MB.'))))), /*#__PURE__*/React.createElement("button", {
        type: "submit",
        className: "btn iri nbtn",
        disabled: receiveBusy
      }, receiveBusy ? 'Saving…' : 'Add to stock')), rmsg && /*#__PURE__*/React.createElement("p", {
        className: "nok",
        role: "status"
      }, rmsg), stockMsg && /*#__PURE__*/React.createElement("p", {
        className: "nerr",
        role: "alert"
      }, stockMsg)), /*#__PURE__*/React.createElement("section", {
        className: "dc"
      }, /*#__PURE__*/React.createElement(Title, {
        ic: IC.box
      }, "Orders on the way"), orders.length === 0 && /*#__PURE__*/React.createElement("p", null, "No open orders. Use Reorder on the Stock page to place one."), orders.map(([x, i]) => /*#__PURE__*/React.createElement("div", {
        className: "npill col",
        key: x[0] + i
      }, /*#__PURE__*/React.createElement("b", {
        className: "l"
      }, x[0]), /*#__PURE__*/React.createElement("span", {
        className: "nmut"
      }, x[1], " \xB7 ", money(x[2])), /*#__PURE__*/React.createElement("button", {
        className: "dmini",
        onClick: () => receiveOrder(i)
      }, "Mark received")))), /*#__PURE__*/React.createElement("section", {
        className: "dc span3"
      }, /*#__PURE__*/React.createElement(Title, {
        ic: IC.receipt
      }, "Recently received"), recent.map(b => /*#__PURE__*/React.createElement("div", {
        className: "npill",
        key: b[0]
      }, /*#__PURE__*/React.createElement("span", {
        className: "nin xs"
      }, b[1][0]), /*#__PURE__*/React.createElement("span", null, b[1], " \xD7 ", b[2]), /*#__PURE__*/React.createElement("span", {
        className: "nmut"
      }, b[6], " \xB7 ", b[4] === 0 ? 'Today' : b[4] + ' days ago'), /*#__PURE__*/React.createElement("b", null, '$' + b[5].toFixed(2), " each")))));
    },
    slow: () => {
      const live = batches.filter(b => b[3] > 0);
      const units = slow.reduce((a, b) => a + b[3], 0);
      const tied = slow.reduce((a, b) => a + b[3] * b[5], 0);
      const oldest = live.reduce((a, b) => Math.max(a, b[4]), 0);
      const buckets = [['0-30', 0, 30], ['31-60', 31, 60], ['61-90', 61, 90], ['90+', 91, 9999]].map(([l, lo, hi]) => [l, live.filter(b => b[4] >= lo && b[4] <= hi).reduce((a, b) => a + b[3], 0)]);
      const bmax = Math.max(...buckets.map(x => x[1]), 1);
      const watch = live.filter(b => b[4] <= limit && b[4] > limit * 0.7);
      const list = [...slow, ...watch];
      const tip = b => b[4] > limit * 2 ? 'Clear it: 25% off or put it in a bundle.' : b[4] > limit ? 'Try 15% off or pair it with a best seller.' : 'Close to the limit. Give it a push.';
      return /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
        className: "kpis"
      }, [['Batches too old', slow.length, `older than ${limit} days`], ['Units stuck', units, 'still on the shelf'], ['Money tied up', money(tied), 'at cost price'], ['Oldest stock', oldest + (oldest === 1 ? ' day' : ' days'), 'since it arrived']].map(([l, v, s]) => /*#__PURE__*/React.createElement("div", {
        className: "kpi flat metric",
        key: l
      }, /*#__PURE__*/React.createElement("span", {
        className: "dlab"
      }, l), /*#__PURE__*/React.createElement("b", null, v), /*#__PURE__*/React.createElement("small", null, s)))), /*#__PURE__*/React.createElement("div", {
        className: "dgrid"
      }, /*#__PURE__*/React.createElement("section", {
        className: "dc"
      }, /*#__PURE__*/React.createElement(Title, {
        ic: IC.gross
      }, "Stock age, units left"), /*#__PURE__*/React.createElement("div", {
        className: "nbars short",
        role: "img",
        "aria-label": 'Units left by age: ' + buckets.map(x => x[0] + ' days ' + x[1]).join(', ')
      }, buckets.map(([l, u], i) => /*#__PURE__*/React.createElement("div", {
        className: "ncol",
        key: l
      }, /*#__PURE__*/React.createElement("b", null, u), /*#__PURE__*/React.createElement("div", {
        className: "ntrack"
      }, /*#__PURE__*/React.createElement("i", {
        className: i === 0 ? '' : 'fc',
        style: {
          height: u / bmax * 100 + '%'
        }
      })), /*#__PURE__*/React.createElement("span", null, l, "d"))))), /*#__PURE__*/React.createElement("section", {
        className: "dc span2"
      }, /*#__PURE__*/React.createElement(Title, {
        ic: NAV.find(x => x[0] === 'slow')[2],
        right: /*#__PURE__*/React.createElement("div", {
          className: "nseg sm",
          role: "group",
          "aria-label": "Too long after how many days"
        }, [30, 45, 60, 90].map(d => /*#__PURE__*/React.createElement("button", {
          key: d,
          "aria-pressed": limit === d,
          onClick: () => setLimit(d)
        }, d, "d")))
      }, "Sitting longer than ", limit, " days"), list.length === 0 && /*#__PURE__*/React.createElement("p", null, "Nothing is sitting too long. Nice work."), list.map(b => {
        const sd = Math.round((b[2] - b[3]) / b[2] * 100);
        return /*#__PURE__*/React.createElement("div", {
          className: "nbatch",
          key: b[0]
        }, /*#__PURE__*/React.createElement("div", {
          className: "grow"
        }, /*#__PURE__*/React.createElement("div", {
          className: "nrow2"
        }, /*#__PURE__*/React.createElement("span", null, /*#__PURE__*/React.createElement("b", null, b[1]), " ", /*#__PURE__*/React.createElement("span", {
          className: "nmut"
        }, "\xB7 ", b[6])), /*#__PURE__*/React.createElement("span", {
          className: 'chipS ' + (b[4] > limit ? 'late' : 'pend')
        }, b[4], " days")), /*#__PURE__*/React.createElement(Bar, {
          pct: sd
        }), /*#__PURE__*/React.createElement("div", {
          className: "nrow2 sub"
        }, /*#__PURE__*/React.createElement("span", null, sd, "% sold, ", b[3], " left, ", money(b[3] * b[5]), " tied up"), /*#__PURE__*/React.createElement("span", null, tip(b)))), /*#__PURE__*/React.createElement("button", {
          className: "dmini",
          "aria-pressed": !!disc[b[0]],
          onClick: () => setDisc({
            ...disc,
            [b[0]]: !disc[b[0]]
          })
        }, disc[b[0]] ? 'Discount on ✓' : 'Mark discounted'));
      }))));
    },
    expenses: () => /*#__PURE__*/React.createElement("div", {
      className: "dgrid"
    }, /*#__PURE__*/React.createElement("section", {
      className: "dc span2"
    }, /*#__PURE__*/React.createElement(Title, {
      ic: IC.exp,
      right: /*#__PURE__*/React.createElement("b", {
        className: "dbig sm"
      }, money(exp))
    }, "Expenses by category, ", m), cats.length === 0 && /*#__PURE__*/React.createElement("p", null, "No expenses recorded yet."), cats.map(([n, v]) => /*#__PURE__*/React.createElement("div", {
      className: "nstock",
      key: n
    }, /*#__PURE__*/React.createElement("div", {
      className: "nrow2"
    }, /*#__PURE__*/React.createElement("span", null, n), /*#__PURE__*/React.createElement("span", null, money(v))), /*#__PURE__*/React.createElement(Bar, {
      pct: v / maxCat * 100
    })))), /*#__PURE__*/React.createElement("section", {
      className: "dc"
    }, /*#__PURE__*/React.createElement(Title, {
      ic: IC.receipt
    }, "Added by you"), expList.length === 0 && /*#__PURE__*/React.createElement("p", null, "Nothing yet. Use + Expense to record one."), expList.map(([w, a, d], i) => /*#__PURE__*/React.createElement("div", {
      className: "npill",
      key: w + i
    }, /*#__PURE__*/React.createElement("span", {
      className: "nin xs"
    }, w[0]), /*#__PURE__*/React.createElement("span", null, w), /*#__PURE__*/React.createElement("span", {
      className: "nmut"
    }, d), /*#__PURE__*/React.createElement("b", null, money(a)))))),
    customers: () => {
      const map = {};
      sales.forEach(([w, a,, d]) => {
        const c = map[w] || (map[w] = [w, 0, 0, d]);
        c[1]++;
        c[2] += a;
      });
      const cust = Object.values(map);
      return /*#__PURE__*/React.createElement("section", {
        className: "dc"
      }, /*#__PURE__*/React.createElement(Title, {
        ic: NAV.find(x => x[0] === 'customers')[2]
      }, "Customers"), cust.length === 0 && /*#__PURE__*/React.createElement("p", null, "No customers yet. They appear as you record sales."), cust.map(([n, o, sp, last]) => /*#__PURE__*/React.createElement("div", {
        className: "npill",
        key: n
      }, /*#__PURE__*/React.createElement("span", {
        className: "nin xs"
      }, n[0]), /*#__PURE__*/React.createElement("span", null, n), /*#__PURE__*/React.createElement("span", {
        className: "nmut"
      }, o, " orders \xB7 last ", last), /*#__PURE__*/React.createElement("b", null, money(sp)))));
    },
    reports: () => /*#__PURE__*/React.createElement("section", {
      className: "dc"
    }, /*#__PURE__*/React.createElement(Title, {
      ic: NAV.find(x => x[0] === 'reports')[2]
    }, "Monthly reports"), /*#__PURE__*/React.createElement("div", {
      className: "nscroll"
    }, /*#__PURE__*/React.createElement("div", {
      className: "ntable"
    }, /*#__PURE__*/React.createElement("div", {
      className: "nth r"
    }, /*#__PURE__*/React.createElement("span", null, "Period"), /*#__PURE__*/React.createElement("span", null, "Revenue"), /*#__PURE__*/React.createElement("span", null, "Expenses"), /*#__PURE__*/React.createElement("span", null, "Gross profit"), /*#__PURE__*/React.createElement("span", null, "Net profit")), reportRows.slice().reverse().map(r => /*#__PURE__*/React.createElement("div", {
      className: "ntr r",
      key: r.month
    }, /*#__PURE__*/React.createElement("b", null, monthLabel(r.month)), /*#__PURE__*/React.createElement("span", null, money(toNum(r.revenue))), /*#__PURE__*/React.createElement("span", null, money(toNum(r.expenses))), /*#__PURE__*/React.createElement("span", null, money(toNum(r.gross_profit))), /*#__PURE__*/React.createElement("span", {
      className: "ncy"
    }, money(toNum(r.net_profit)))))))),
    insights: () => /*#__PURE__*/React.createElement("div", {
      className: "dgrid"
    }, /*#__PURE__*/React.createElement("section", {
      className: "dc assistant-chat"
    }, /*#__PURE__*/React.createElement("div", {
      className: "assistant-modes"
    }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(Title, {
      ic: IC.bulb
    }, "Financial intelligence"), /*#__PURE__*/React.createElement("p", null, "Choose how you want to analyse your business.")), /*#__PURE__*/React.createElement("div", {
      className: "nseg",
      role: "group",
      "aria-label": "Assistant mode"
    }, /*#__PURE__*/React.createElement("button", {
      type: "button",
      "aria-pressed": assistantMode === 'algorithm',
      onClick: () => setAssistantMode('algorithm')
    }, "Algorithms"), /*#__PURE__*/React.createElement("button", {
      type: "button",
      "aria-pressed": assistantMode === 'ai',
      onClick: () => setAssistantMode('ai')
    }, "AI assistant"))), assistantMode === 'algorithm' ? /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("p", null, "Verified calculations and rule-based insights run on your data\u2014no AI connection required."), /*#__PURE__*/React.createElement("div", {
      className: "analysis-options",
      role: "group",
      "aria-label": "Choose an algorithm analysis"
    }, [['profitability', 'Profitability'], ['sales_trends', 'Sales trends'], ['expense_analysis', 'Expense analysis'], ['product_rankings', 'Product rankings'], ['stock_cover', 'Stock cover'], ['reorder_planning', 'Reorder planning'], ['aging_inventory', 'Aging inventory'], ['break_even', 'Break-even estimate'], ['customer_concentration', 'Customer concentration'], ['cash_indicators', 'Cash-flow indicators']].map(([id, label]) => /*#__PURE__*/React.createElement("button", {
      className: "dmini",
      type: "button",
      key: id,
      "aria-pressed": algorithmType === id,
      disabled: algorithmBusy,
      onClick: () => {
        setAlgorithmType(id);
        setAlgorithmResult(null);
        setAlgorithmError('');
      }
    }, label)), /*#__PURE__*/React.createElement("button", {
      className: "btn iri nbtn",
      type: "button",
      onClick: runAlgorithm,
      disabled: algorithmBusy
    }, algorithmBusy ? 'Analysing…' : 'Run analysis')), algorithmError && /*#__PURE__*/React.createElement("p", {
      className: "assistant-error",
      role: "alert"
    }, algorithmError)) : /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("p", null, "Ask a question about verified monthly figures. Answers are generated by the configured AI service."), assistantMessages.length === 0 && /*#__PURE__*/React.createElement("div", {
      className: "assistant-prompts"
    }, ['How did my business perform this month?', 'What are my biggest expenses?', 'What should I focus on next?'].map(prompt => /*#__PURE__*/React.createElement("button", {
      className: "dmini",
      type: "button",
      key: prompt,
      onClick: () => setAssistantQuestion(prompt)
    }, prompt))), assistantMessages.length > 0 && /*#__PURE__*/React.createElement("div", {
      className: "assistant-messages",
      role: "log",
      "aria-live": "polite",
      "aria-label": "Assistant conversation"
    }, assistantMessages.map((message, index) => /*#__PURE__*/React.createElement("div", {
      className: 'assistant-message ' + (message.role === 'user' ? 'user' : 'assistant'),
      key: index
    }, /*#__PURE__*/React.createElement("span", {
      className: "assistant-label"
    }, message.role === 'user' ? 'You' : 'Nexa assistant'), /*#__PURE__*/React.createElement("p", null, message.text)))), /*#__PURE__*/React.createElement("form", {
      className: "assistant-form",
      onSubmit: askAssistant
    }, /*#__PURE__*/React.createElement("textarea", {
      "aria-label": "Ask a question about your business",
      maxLength: 1000,
      placeholder: "Ask about revenue, expenses, or trends\u2026",
      value: assistantQuestion,
      onChange: event => setAssistantQuestion(event.target.value),
      disabled: assistantBusy
    }), /*#__PURE__*/React.createElement("button", {
      className: "btn iri nbtn",
      type: "submit",
      disabled: assistantBusy || !assistantQuestion.trim()
    }, assistantBusy ? 'Thinking…' : 'Ask')), assistantError && /*#__PURE__*/React.createElement("p", {
      className: "assistant-error",
      role: "alert"
    }, assistantError), /*#__PURE__*/React.createElement("p", {
      className: "assistant-note"
    }, "Only your question and aggregated monthly summary are sent to the configured AI service; customer and product names or transaction details are not shared. Answers are suggestions, not financial advice."))), assistantMode === 'algorithm' && algorithmResult && /*#__PURE__*/React.createElement("section", {
      className: "dc algorithm-results"
    }, /*#__PURE__*/React.createElement(Title, {
      ic: IC.gross,
      right: /*#__PURE__*/React.createElement("span", {
        className: "nmut"
      }, algorithmResult.period)
    }, algorithmResult.title), /*#__PURE__*/React.createElement("div", {
      className: "algorithm-metrics"
    }, algorithmResult.metrics.map(metric => /*#__PURE__*/React.createElement("div", {
      className: "algorithm-metric",
      key: metric.label
    }, /*#__PURE__*/React.createElement("span", null, metric.label), /*#__PURE__*/React.createElement("b", null, metric.value === null ? '—' : metric.format === 'currency' ? preciseMoney(metric.value) : metric.format === 'percent' || metric.format === 'change' ? `${metric.value}%` : metric.value)))), algorithmResult.series && /*#__PURE__*/React.createElement("div", {
      className: "algorithm-series",
      "aria-label": "Monthly sales and moving averages"
    }, algorithmResult.series.map(point => {
      const peak = Math.max(...algorithmResult.series.map(item => Number(item.revenue)), 1);
      return /*#__PURE__*/React.createElement("div", {
        className: "algorithm-series-row",
        key: point.period
      }, /*#__PURE__*/React.createElement("span", null, point.label), /*#__PURE__*/React.createElement("div", {
        className: "algorithm-series-track"
      }, /*#__PURE__*/React.createElement("i", {
        style: {
          width: `${Math.max(Number(point.revenue) > 0 ? 2 : 0, Number(point.revenue) / peak * 100)}%`
        }
      })), /*#__PURE__*/React.createElement("div", {
        className: "algorithm-series-values"
      }, /*#__PURE__*/React.createElement("b", null, preciseMoney(point.revenue)), /*#__PURE__*/React.createElement("span", null, "3mo avg ", preciseMoney(point.moving_average))));
    })), algorithmResult.categories && /*#__PURE__*/React.createElement("div", {
      className: "algorithm-table"
    }, algorithmResult.categories.length === 0 ? /*#__PURE__*/React.createElement("div", {
      className: "algorithm-empty"
    }, /*#__PURE__*/React.createElement("p", null, "No expense categories were recorded for this period.")) : /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
      className: "algorithm-row"
    }, /*#__PURE__*/React.createElement("b", null, "Category"), /*#__PURE__*/React.createElement("b", null, "Amount"), /*#__PURE__*/React.createElement("b", {
      className: "optional"
    }, "vs prior"), /*#__PURE__*/React.createElement("b", null, "Share")), algorithmResult.categories.map(row => /*#__PURE__*/React.createElement("div", {
      className: "algorithm-row",
      key: row.category
    }, /*#__PURE__*/React.createElement("b", null, row.category), /*#__PURE__*/React.createElement("span", null, preciseMoney(row.amount)), /*#__PURE__*/React.createElement("span", {
      className: "optional"
    }, row.change_pct === null ? '—' : `${row.change_pct}%`), /*#__PURE__*/React.createElement("span", null, row.share_pct === null ? '—' : `${row.share_pct}%`))))), algorithmResult.products && /*#__PURE__*/React.createElement("div", {
      className: "algorithm-table"
    }, algorithmResult.products.length === 0 ? /*#__PURE__*/React.createElement("div", {
      className: "algorithm-empty"
    }, /*#__PURE__*/React.createElement("p", null, "No product-linked sales were recorded for this period.")) : /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
      className: "algorithm-row"
    }, /*#__PURE__*/React.createElement("b", null, "Product"), /*#__PURE__*/React.createElement("b", null, "Revenue"), /*#__PURE__*/React.createElement("b", {
      className: "optional"
    }, "Units"), /*#__PURE__*/React.createElement("b", null, "Gross profit")), algorithmResult.products.map(row => /*#__PURE__*/React.createElement("div", {
      className: "algorithm-row",
      key: row.rank
    }, /*#__PURE__*/React.createElement("b", null, row.rank, ". ", row.product), /*#__PURE__*/React.createElement("span", null, preciseMoney(row.revenue)), /*#__PURE__*/React.createElement("span", {
      className: "optional"
    }, row.units), /*#__PURE__*/React.createElement("span", null, preciseMoney(row.gross_profit)))))), algorithmResult.reorders && /*#__PURE__*/React.createElement("div", {
      className: "algorithm-table"
    }, algorithmResult.reorders.length === 0 ? /*#__PURE__*/React.createElement("div", {
      className: "algorithm-empty"
    }, /*#__PURE__*/React.createElement("p", null, "No products are tracked yet.")) : /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
      className: "algorithm-row"
    }, /*#__PURE__*/React.createElement("b", null, "Product"), /*#__PURE__*/React.createElement("b", null, "Stock + ordered"), /*#__PURE__*/React.createElement("b", {
      className: "optional"
    }, "Reorder point"), /*#__PURE__*/React.createElement("b", null, "Order units")), algorithmResult.reorders.map(row => /*#__PURE__*/React.createElement("div", {
      className: "algorithm-row",
      key: row.product
    }, /*#__PURE__*/React.createElement("b", null, row.product), /*#__PURE__*/React.createElement("span", null, row.stock, " + ", row.incoming), /*#__PURE__*/React.createElement("span", {
      className: "optional"
    }, row.reorder_point === null ? '—' : row.reorder_point), /*#__PURE__*/React.createElement("span", null, row.reorder_point === null ? 'No data' : row.suggested_quantity))))), algorithmResult.inventory && /*#__PURE__*/React.createElement("div", {
      className: "algorithm-table"
    }, algorithmResult.inventory.length === 0 ? /*#__PURE__*/React.createElement("div", {
      className: "algorithm-empty"
    }, /*#__PURE__*/React.createElement("p", null, "No stock is currently on hand.")) : /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
      className: "algorithm-row"
    }, /*#__PURE__*/React.createElement("b", null, "Product"), /*#__PURE__*/React.createElement("b", null, "Aged units"), /*#__PURE__*/React.createElement("b", {
      className: "optional"
    }, "Total value"), /*#__PURE__*/React.createElement("b", null, "Aged value")), algorithmResult.inventory.map(row => /*#__PURE__*/React.createElement("div", {
      className: "algorithm-row",
      key: row.product
    }, /*#__PURE__*/React.createElement("b", null, row.product), /*#__PURE__*/React.createElement("span", null, row.aged_units), /*#__PURE__*/React.createElement("span", {
      className: "optional"
    }, preciseMoney(row.value)), /*#__PURE__*/React.createElement("span", null, preciseMoney(row.aged_value)))))), algorithmResult.customer_rows && /*#__PURE__*/React.createElement("div", {
      className: "algorithm-table"
    }, algorithmResult.customer_rows.length === 0 ? /*#__PURE__*/React.createElement("div", {
      className: "algorithm-empty"
    }, /*#__PURE__*/React.createElement("p", null, "No identified customer revenue in this period.")) : /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
      className: "algorithm-row"
    }, /*#__PURE__*/React.createElement("b", null, "Customer"), /*#__PURE__*/React.createElement("b", null, "Paid sales"), /*#__PURE__*/React.createElement("b", {
      className: "optional"
    }, "Share of revenue"), /*#__PURE__*/React.createElement("b", null, "Share")), algorithmResult.customer_rows.map(row => /*#__PURE__*/React.createElement("div", {
      className: "algorithm-row",
      key: row.customer
    }, /*#__PURE__*/React.createElement("b", null, row.customer), /*#__PURE__*/React.createElement("span", null, preciseMoney(row.revenue)), /*#__PURE__*/React.createElement("span", {
      className: "optional"
    }, "of total paid"), /*#__PURE__*/React.createElement("span", null, row.share_pct === null ? '—' : `${row.share_pct}%`))))), algorithmResult.stock && /*#__PURE__*/React.createElement("div", {
      className: "algorithm-table"
    }, algorithmResult.stock.length === 0 ? /*#__PURE__*/React.createElement("div", {
      className: "algorithm-empty"
    }, /*#__PURE__*/React.createElement("p", null, "No products are tracked yet. Receive stock to start.")) : /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
      className: "algorithm-row"
    }, /*#__PURE__*/React.createElement("b", null, "Product"), /*#__PURE__*/React.createElement("b", null, "Stock"), /*#__PURE__*/React.createElement("b", {
      className: "optional"
    }, "Cover"), /*#__PURE__*/React.createElement("b", null, "Status")), algorithmResult.stock.map(row => /*#__PURE__*/React.createElement("div", {
      className: "algorithm-row",
      key: row.product
    }, /*#__PURE__*/React.createElement("b", null, row.product), /*#__PURE__*/React.createElement("span", null, row.stock), /*#__PURE__*/React.createElement("span", {
      className: "optional"
    }, row.days_cover === null ? '—' : `${row.days_cover} days`), /*#__PURE__*/React.createElement("span", null, row.status, row.reorder_qty > 0 ? ` · order ${row.reorder_qty}` : ''))))), /*#__PURE__*/React.createElement("ul", {
      className: "algorithm-insights"
    }, algorithmResult.insights.map((insight, index) => /*#__PURE__*/React.createElement("li", {
      key: index
    }, insight))), /*#__PURE__*/React.createElement("p", {
      className: "assistant-note"
    }, "Calculated from recorded transactions for this period. Insights are descriptive, not financial advice.")), /*#__PURE__*/React.createElement("section", {
      className: "dc span2"
    }, /*#__PURE__*/React.createElement(Title, {
      ic: IC.bulb,
      right: /*#__PURE__*/React.createElement("div", {
        className: "nseg sm",
        role: "group",
        "aria-label": "Filter by priority"
      }, ['All', 'High'].map(p => /*#__PURE__*/React.createElement("button", {
        key: p,
        "aria-pressed": pri === p,
        onClick: () => setPri(p)
      }, p)))
    }, "Smart ideas for you"), /*#__PURE__*/React.createElement("ul", {
      className: "nrecs"
    }, recs.length === 0 && /*#__PURE__*/React.createElement("li", null, /*#__PURE__*/React.createElement("p", null, "No ideas yet. They will show up as your data grows.")), recs.map(r => /*#__PURE__*/React.createElement("li", {
      key: r.id,
      className: done[r.id] ? 'done' : ''
    }, /*#__PURE__*/React.createElement("span", {
      className: 'pri ' + r.pri.toLowerCase()
    }, r.pri), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("b", null, r.cat), /*#__PURE__*/React.createElement("p", null, r.text)), /*#__PURE__*/React.createElement("button", {
      className: "dmini",
      "aria-pressed": !!done[r.id],
      onClick: () => setDone({
        ...done,
        [r.id]: !done[r.id]
      })
    }, done[r.id] ? 'Undo' : 'Done'))))), /*#__PURE__*/React.createElement("section", {
      className: "dc"
    }, /*#__PURE__*/React.createElement(Title, {
      ic: IC.net
    }, "Forecast for ", NEXT[m]), /*#__PURE__*/React.createElement("div", {
      className: "nscn",
      role: "group",
      "aria-label": "Scenario"
    }, Object.keys(SC).map(s => /*#__PURE__*/React.createElement("button", {
      key: s,
      "aria-pressed": scn === s,
      onClick: () => setScn(s)
    }, /*#__PURE__*/React.createElement("i", null, s[0]), /*#__PURE__*/React.createElement("span", null, s)))), /*#__PURE__*/React.createElement("b", {
      className: "dbig"
    }, money(nextTotal)), /*#__PURE__*/React.createElement("p", null, ((factor - 1) * 100 >= 0 ? '+' : '') + ((factor - 1) * 100).toFixed(0), "% on ", m, ". Based on your weekly trend and best sellers.")), /*#__PURE__*/React.createElement("section", {
      className: "dc span3"
    }, /*#__PURE__*/React.createElement(Title, {
      ic: IC.gross,
      right: /*#__PURE__*/React.createElement("span", {
        className: "nleg"
      }, /*#__PURE__*/React.createElement("i", null), "Actual", /*#__PURE__*/React.createElement("i", {
        className: "fc"
      }), "Forecast")
    }, "Sales by week, ", m), /*#__PURE__*/React.createElement(Trend, {
      series: series,
      next: nextWeek,
      key: m + scn + rev
    })))
  };
  const cur = NAV.find(n => n[0] === nav);
  const showMonth = ['overview', 'products', 'expenses', 'insights'].includes(nav);
  const go = id => {
    setNav(id);
    setQ('');
    window.scrollTo(0, 0);
  };
  return /*#__PURE__*/React.createElement("div", {
    className: "dash"
  }, /*#__PURE__*/React.createElement("div", {
    className: "nshell"
  }, /*#__PURE__*/React.createElement("nav", {
    className: "nside",
    "aria-label": "Main menu"
  }, /*#__PURE__*/React.createElement("div", {
    className: "nlogo"
  }, /*#__PURE__*/React.createElement("span", {
    className: "nin sm"
  }, /*#__PURE__*/React.createElement(Ico, {
    d: IC.gross,
    s: 18
  })), "Nexa"), /*#__PURE__*/React.createElement("span", {
    className: "ngrp"
  }, "Menu"), NAV.map(([id, label, ic], i) => /*#__PURE__*/React.createElement(React.Fragment, {
    key: id
  }, id === 'sales' && /*#__PURE__*/React.createElement("span", {
    className: "ngrp"
  }, "Libraries"), /*#__PURE__*/React.createElement("button", {
    className: "nnav",
    "aria-current": nav === id ? 'page' : undefined,
    onClick: () => go(id)
  }, /*#__PURE__*/React.createElement("span", {
    className: "nin"
  }, /*#__PURE__*/React.createElement(Ico, {
    d: ic,
    s: 17
  })), /*#__PURE__*/React.createElement("span", {
    className: "nlab"
  }, label))))), /*#__PURE__*/React.createElement("main", {
    className: "nmain"
  }, /*#__PURE__*/React.createElement("header", {
    className: "ntop"
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("h1", null, cur[1]), /*#__PURE__*/React.createElement("p", null, cur[3])), /*#__PURE__*/React.createElement("div", {
    className: "ntools"
  }, showMonth && /*#__PURE__*/React.createElement(Month, null), nav !== 'settings' && /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("button", {
    className: "btn iri nbtn",
    onClick: () => setForm('sale')
  }, "+ Sale"), /*#__PURE__*/React.createElement("button", {
    className: "btn glass nbtn",
    onClick: () => setForm('expense')
  }, "+ Expense")), isStaff && /*#__PURE__*/React.createElement("a", {
    className: "dpill",
    href: ADMIN_URL,
    target: "_blank",
    rel: "noopener"
  }, "Admin"), /*#__PURE__*/React.createElement("button", {
    className: "dpill",
    onClick: onExit
  }, "Sign out"))), /*#__PURE__*/React.createElement("div", {
    key: nav,
    className: "nview"
  }, views[nav]()))), form && /*#__PURE__*/React.createElement(RecordSheet, {
    type: form,
    onClose: () => setForm(null),
    onSave: save,
    products: prods
  }));
}
function App() {
  const [mode, setMode] = useState(null);
  const [view, setView] = useState('welcome');
  useEffect(() => {
    document.body.classList.toggle('inapp', view === 'app');
    document.body.classList.toggle('welcome', view === 'welcome');
    window.scrollTo(0, 0);
  }, [view]);
  const [dark, setDark] = useState(false);
  const setTheme = enabled => {
    setDark(enabled);
    document.documentElement.dataset.theme = enabled ? "dark" : "light";
  };
  useEffect(() => {
    const t = localStorage.getItem(TOKEN_KEY);
    if (!t) return;
    call("/me/", null, t).then(() => setView('app')).catch(e => {
      if (!/reach/.test(e.message)) localStorage.removeItem(TOKEN_KEY);
    });
  }, []);
  const signOut = () => {
    const t = localStorage.getItem(TOKEN_KEY);
    localStorage.removeItem(TOKEN_KEY);
    if (t) call("/auth/logout/", {}, t).catch(() => {});
    setTheme(false);
    setView('welcome');
  };
  if (view === 'app') return /*#__PURE__*/React.createElement(Dashboard, {
    dark: dark,
    setTheme: setTheme,
    onExit: signOut
  });
  return /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
    className: "landing-page"
  }, /*#__PURE__*/React.createElement("nav", null, /*#__PURE__*/React.createElement("div", {
    className: "logo"
  }, /*#__PURE__*/React.createElement("i", null), "Nexa"), /*#__PURE__*/React.createElement("button", {
    className: "btn glass",
    onClick: () => setMode("signin")
  }, "Sign in")), /*#__PURE__*/React.createElement("main", {
    className: "hero"
  }, /*#__PURE__*/React.createElement("span", {
    className: "tag"
  }, "Business intelligence, reimagined"), /*#__PURE__*/React.createElement("h1", null, "Run your business with ", /*#__PURE__*/React.createElement("em", null, "foresight")), /*#__PURE__*/React.createElement("p", {
    className: "sub"
  }, "Record every sale, purchase and expense in one place. Nexa shows what sells most, how each month is going, and what to do next."), /*#__PURE__*/React.createElement("div", {
    className: "cta"
  }, /*#__PURE__*/React.createElement("button", {
    className: "btn iri",
    onClick: () => setMode("signup")
  }, "Get started"), /*#__PURE__*/React.createElement("button", {
    className: "btn glass",
    onClick: () => setMode("signin")
  }, "I have an account")), /*#__PURE__*/React.createElement("div", {
    className: "pills"
  }, /*#__PURE__*/React.createElement("span", {
    className: "pill"
  }, "Sales and stock tracking"), /*#__PURE__*/React.createElement("span", {
    className: "pill"
  }, "Smart strategy ideas"), /*#__PURE__*/React.createElement("span", {
    className: "pill"
  }, "Monthly forecasts"))), /*#__PURE__*/React.createElement("aside", {
    className: "float f1",
    "aria-hidden": "true"
  }, /*#__PURE__*/React.createElement("span", null, "Slow stock flagged after"), /*#__PURE__*/React.createElement("b", null, "45 days")), /*#__PURE__*/React.createElement("aside", {
    className: "float f2",
    "aria-hidden": "true"
  }, /*#__PURE__*/React.createElement("span", null, "Next-month forecast"), /*#__PURE__*/React.createElement("b", null, "3 scenarios"))), mode && /*#__PURE__*/React.createElement(Sheet, {
    mode: mode,
    onClose: () => setMode(null),
    onEnter: () => {
      setMode(null);
      setView('app');
    },
    onSwitch: setMode
  }));
}
ReactDOM.createRoot(document.getElementById("root")).render(/*#__PURE__*/React.createElement(App, null));

/* Original orb: gentle pointer parallax, paused for reduced motion. */
const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
const video = document.getElementById("orb");
if (reduce) {
  video.removeAttribute("autoplay");
  video.pause();
} else {
  const p = video.play();
  if (p && p.catch) p.catch(() => {});
  addEventListener("pointermove", e => {
    const r = document.documentElement.style;
    r.setProperty("--px", (e.clientX / innerWidth - .5) * 28 + "px");
    r.setProperty("--py", (e.clientY / innerHeight - .5) * 20 + "px");
  });
}
