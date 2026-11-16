import { useEffect, useRef, useState } from "react";

export default function RecordSheet({ type, onClose, onSave, products = [], currency = "USD" }) {
  const [who, setWho] = useState("");
  const [amt, setAmt] = useState("");
  const [st, setSt] = useState("Paid");
  const [productId, setProductId] = useState("");
  const [qty, setQty] = useState("1");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const savingRef = useRef(false);
  const ref = useRef(null);
  useEffect(() => {
    ref.current && ref.current.focus();
    const esc = (e) => e.key === "Escape" && !savingRef.current && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, []);
  const sale = type === "sale";
  const product = sale ? products.find((p) => String(p[8]) === productId) || null : null;
  const qtyNum = Number(qty);
  const pickProduct = (id) => {
    const item = products.find((p) => String(p[8]) === id);
    setProductId(id);
    setQty("1");
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
        setError("Quantity must be a whole number of at least 1.");
        return;
      }
      if (qtyNum > product[4]) {
        setError(`Only ${product[4]} ${product[0]} in stock.`);
        return;
      }
    }
    savingRef.current = true;
    setSaving(true);
    setError("");
    try {
      await onSave({ who: who.trim() || (sale ? "Walk-in" : "General"), a: amount, st, product, qty: qtyNum });
    } catch (saveError) {
      savingRef.current = false;
      setSaving(false);
      setError(saveError.message);
    }
  };
  return (
    <div className="scrim" onClick={() => !saving && onClose()}>
      <form className="sheet" role="dialog" aria-modal="true" aria-labelledby="rt" onClick={(e) => e.stopPropagation()} onSubmit={submit}>
        <h2 id="rt">{sale ? "Record a sale" : "Record an expense"}</h2>
        <p>{sale ? "It is added to this month and updates your totals." : "It is added to this month and comes off your profit."}</p>
        <label>{sale ? "Customer" : "Category"}<input ref={ref} type="text" value={who} onChange={(e) => setWho(e.target.value)} placeholder={sale ? "Walk-in" : "Utilities"} disabled={saving} /></label>
        {sale && <label>Product
          <select value={productId} onChange={(e) => pickProduct(e.target.value)} disabled={saving}>
            <option value="">No product</option>
            {products.map((p) => <option key={p[8]} value={String(p[8])} disabled={p[4] <= 0}>
              {p[4] > 0 ? `${p[0]} · ${p[4]} in stock` : `${p[0]} · out of stock`}
            </option>)}
          </select>
        </label>}
        {product && <label>{`Quantity · ${product[4]} in stock`}
          <input type="number" min="1" max={product[4]} step="1" required value={qty} onChange={(e) => changeQty(e.target.value)} disabled={saving} />
        </label>}
        <label>Amount ({currency})<input type="number" min="0" step="0.01" required value={amt} onChange={(e) => setAmt(e.target.value)} disabled={saving} /></label>
        {sale && <div className="nseg" role="group" aria-label="Payment status" style={{ marginBottom: 12 }}>
          {["Paid", "Pending"].map((s) => <button type="button" key={s} aria-pressed={st === s} onClick={() => setSt(s)} disabled={saving}>{s}</button>)}
        </div>}
        {error && <p className="err" role="alert">{error}</p>}
        <div className="row">
          <button type="button" className="btn glass" onClick={onClose} disabled={saving}>Cancel</button>
          <button type="submit" className="btn iri" disabled={saving}>{saving ? "Saving…" : "Save"}</button>
        </div>
      </form>
    </div>
  );
}
