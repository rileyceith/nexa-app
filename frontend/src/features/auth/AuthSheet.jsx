import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { TOKEN_KEY } from "../../api/client.js";
import { login, register, requestPasswordReset } from "./api.js";

export default function AuthSheet({ mode, onClose, onEnter, onSwitch }) {
  const [f, setF] = useState({ username: "", email: "", password: "", password2: "", terms: false, teamSharing: false });
  const [err, setErr] = useState("");
  const [notice, setNotice] = useState("");
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
  }, [mode]);
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
  const forgot = mode === "forgot";
  const set = (k) => (e) => setF({ ...f, [k]: ["terms", "teamSharing"].includes(k) ? e.target.checked : e.target.value });
  const submit = async (e) => {
    e.preventDefault();
    if (leavingRef.current || submittingRef.current) return;
    setErr("");
    setNotice("");
    if (signup) {
      if (f.password !== f.password2) return setErr("The passwords do not match.");
      if (!f.terms) return setErr("You must accept the terms and conditions.");
    }
    submittingRef.current = true;
    setBusy(true);
    try {
      if (forgot) {
        await requestPasswordReset({ email: f.email });
        setNotice("If an account exists for that email, password reset instructions will be sent.");
        return;
      }
      const res = signup
        ? await register({
          username: f.username, email: f.email, password: f.password, password2: f.password2,
          accepted_terms: f.terms, team_sharing_enabled: f.teamSharing,
        })
        : await login({ username: f.username, password: f.password });
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
          <h2 id="st">{signup ? "Create your Nexa account" : forgot ? "Reset your password" : "Welcome back"}</h2>
          <p>{signup ? "Choose an email, username and password." : forgot ? "Enter the email address on your account." : "Sign in with your username and password."}</p>
        </div>
        {forgot ? <label>Email
          <input ref={ref} type="email" required autoComplete="email" value={f.email} onChange={set("email")} />
        </label> : <>
          <label>Username
            <input ref={ref} type="text" required autoComplete="username" value={f.username} onChange={set("username")} />
          </label>
          {signup && <label>Email
            <input type="email" required autoComplete="email" value={f.email} onChange={set("email")} />
          </label>}
          <label>Password
            <input type="password" required autoComplete={signup ? "new-password" : "current-password"} value={f.password} onChange={set("password")} />
          </label>
          {signup && <label>Re-enter password
            <input type="password" required autoComplete="new-password" value={f.password2} onChange={set("password2")} />
          </label>}
        </>}
        {signup && <>
          <label className="agree">
            <input type="checkbox" checked={f.terms} onChange={set("terms")} />
            <span>I accept the <button type="button" className="linkbtn" onClick={() => setShowTerms(!showTerms)}>terms and conditions</button></span>
          </label>
          <label className="agree">
            <input type="checkbox" checked={f.teamSharing} onChange={set("teamSharing")} />
            <span>Enable team sharing for my business. I can invite people and set their permissions later.</span>
          </label>
          {showTerms && <div className="terms">
            <p>1. Nexa helps you record and review your business activity. You are responsible for the accuracy of what you enter.</p>
            <p>2. Keep your password private. You are responsible for activity on your account.</p>
            <p>3. We store your account and business records to run the service and do not sell them.</p>
            <p>4. Forecasts and ideas are estimates, not financial advice.</p>
          </div>}
        </>}
        {err && <p className="err" role="alert">{err}</p>}
        {notice && <p className="nok" role="status">{notice}</p>}
        <div className="row">
          <button type="button" className="btn glass" onClick={() => leave(onClose)}>Cancel</button>
          <button type="submit" className={busy ? "btn iri busy" : "btn iri"} disabled={busy}>{busy ? "Please wait…" : signup ? "Create account" : forgot ? "Send reset link" : "Sign in"}</button>
        </div>
        <p className="switch">
          {signup ? "Already have an account? " : forgot ? "Remember your password? " : "New to Nexa? "}
          <button type="button" className="linkbtn" onClick={() => onSwitch(signup || forgot ? "signin" : "signup")}>{signup || forgot ? "Sign in" : "Create one"}</button>
        </p>
        {mode === "signin" && <p className="switch"><button type="button" className="linkbtn" onClick={() => onSwitch("forgot")}>Forgot password?</button></p>}
      </form>
    </div>
  );
}
