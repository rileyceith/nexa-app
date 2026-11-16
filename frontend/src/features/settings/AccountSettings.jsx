import { useEffect, useState } from "react";
import { TOKEN_KEY } from "../../api/client.js";
import { currentUser } from "../auth/api.js";
import { confirmSecurityCode, listAccountSessions, requestSecurityCode, updateAccountProfile } from "./api.js";

const token = () => localStorage.getItem(TOKEN_KEY);

function deviceName(agent) {
  if (!agent || agent === "Unknown device") return "Unknown device";
  const platform = /Android/i.test(agent) ? "Android" : /iPhone|iPad/i.test(agent) ? "iPhone or iPad"
    : /Windows/i.test(agent) ? "Windows" : /Macintosh/i.test(agent) ? "Mac" : "Other device";
  const browser = /Edg/i.test(agent) ? "Edge" : /Firefox/i.test(agent) ? "Firefox"
    : /Chrome|CriOS/i.test(agent) ? "Chrome" : /Safari/i.test(agent) ? "Safari" : "Unknown browser";
  return `${platform} · ${browser}`;
}

export default function AccountSettings({ preferences, onEmailChange, onSignOut }) {
  const [profile, setProfile] = useState(null);
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [sessions, setSessions] = useState([]);
  const [action, setAction] = useState(null);
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [password2, setPassword2] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState({ text: "", error: false });
  const canSend = preferences.email_verified && preferences.email_delivery_configured;

  const refreshSessions = () => listAccountSessions(token()).then(setSessions);
  useEffect(() => {
    Promise.all([currentUser(token()), listAccountSessions(token())]).then(([user, items]) => {
      setProfile(user);
      setUsername(user.username);
      setSessions(items);
    }).catch((error) => setMessage({ text: error.message, error: true }));
  }, []);

  const saveUsername = async (event) => {
    event.preventDefault();
    setBusy(true);
    setMessage({ text: "", error: false });
    try {
      const saved = await updateAccountProfile({ username }, token());
      setProfile((current) => ({ ...current, username: saved.username }));
      setUsername(saved.username);
      setMessage({ text: "Username updated.", error: false });
    } catch (error) {
      setMessage({ text: error.message, error: true });
    } finally { setBusy(false); }
  };

  const sendCode = async (kind, target = "") => {
    setBusy(true);
    setMessage({ text: "", error: false });
    try {
      const result = await requestSecurityCode({ action: kind, target }, token());
      setAction({ kind, target, stage: "current" });
      setCode("");
      setPassword("");
      setPassword2("");
      setMessage({ text: result.detail, error: false });
    } catch (error) {
      setMessage({ text: error.message, error: true });
    } finally { setBusy(false); }
  };

  const confirm = async (event) => {
    event.preventDefault();
    setBusy(true);
    setMessage({ text: "", error: false });
    try {
      const result = await confirmSecurityCode({
        action: action.kind, code, password, password2,
      }, token());
      setCode("");
      if (result.status === "new_email") {
        setAction({ ...action, stage: "new" });
        setMessage({ text: "A new code was sent to your new email address.", error: false });
      } else if (result.status === "password_changed") {
        onSignOut();
      } else if (result.status === "email_changed" || result.status === "device_signed_out") {
        if (result.status === "email_changed") {
          setProfile((current) => ({ ...current, email: action.target }));
          onEmailChange(action.target);
          setEmail("");
        }
        setAction(null);
        setPassword("");
        setPassword2("");
        await refreshSessions();
        setMessage({ text: result.status === "email_changed" ? "Email updated. Other devices were signed out." : "Device signed out.", error: false });
      } else {
        throw new Error("The server returned an unexpected security confirmation.");
      }
    } catch (error) {
      setMessage({ text: error.message, error: true });
    } finally { setBusy(false); }
  };

  return (
    <div className='account-panel'>
      <section className='dc account-profile'>
        <div><span className='account-kicker'>YOUR ACCOUNT</span><h3>Profile &amp; security</h3>
          <p>Manage your sign-in details and devices in one place.</p></div>
        {profile && <div className='account-summary'><span>Signed in as</span><strong>{profile.username}</strong><span>{profile.email || "No account email"}</span></div>}
        <form className='nform' onSubmit={saveUsername}>
          <label>Username<input value={username} maxLength='30' required onChange={(event) => setUsername(event.target.value)} autoComplete='username' /></label>
          <button type='submit' className='btn glass' disabled={busy || !profile || username === profile.username}>Save username</button>
        </form>
        <form className='nform' onSubmit={(event) => { event.preventDefault(); sendCode("email", email.trim().toLowerCase()); }}>
          <label>New account email<input type='email' maxLength='254' required value={email} onChange={(event) => setEmail(event.target.value)} autoComplete='email' /></label>
          <button type='submit' className='btn glass' disabled={busy || !canSend}>Change email</button>
        </form>
        <p>We send a code to your current email, then another to the new address. Other devices will be signed out.</p>
        <div><button type='button' className='btn glass' disabled={busy || !canSend} onClick={() => sendCode("password")}>Change password</button></div>
        <p>Changing your password signs out all devices, including this one.</p>
        {!canSend && <p className='nerr'>Verify your current account email and configure secure email delivery to use security codes.</p>}
      </section>
      <section className='dc'>
        <div><span className='account-kicker'>ACTIVE SESSIONS</span><h3>Signed-in devices</h3>
          <p>Browser details are available for new sign-ins. Older sessions may show as unknown.</p></div>
        <ul className='account-sessions'>
          {sessions.map((session) => <li key={session.id}>
            <div><strong>{deviceName(session.device)}</strong>{session.current && <span className='account-badge'>This device</span>}
              <p>Signed in {new Date(session.created_at).toLocaleString()}</p></div>
            {!session.current && <button type='button' className='btn glass' disabled={busy || !canSend} onClick={() => sendCode("device", String(session.id))}>Sign out</button>}
          </li>)}
        </ul>
      </section>
      {action && <section className='dc account-verification'>
        <h3>Confirm {action.kind === "email" ? "email change" : action.kind === "password" ? "password change" : "device sign-out"}</h3>
        <p>Enter the six-digit code sent to {action.stage === "new" ? "your new email address" : "your current account email"}. Codes expire after 10 minutes.</p>
        <form className='nform' onSubmit={confirm}>
          <label>Security code<input inputMode='numeric' autoComplete='one-time-code' pattern='[0-9]{6}' maxLength='6' value={code} onChange={(event) => setCode(event.target.value)} required /></label>
          {action.kind === "password" && <>
            <label>New password<input type='password' autoComplete='new-password' value={password} onChange={(event) => setPassword(event.target.value)} required /></label>
            <label>Confirm new password<input type='password' autoComplete='new-password' value={password2} onChange={(event) => setPassword2(event.target.value)} required /></label>
          </>}
          <div className='goal-actions'><button type='submit' className='btn iri' disabled={busy}>Confirm</button>
            <button type='button' className='btn glass' disabled={busy} onClick={() => { setAction(null); setCode(""); setPassword(""); setPassword2(""); }}>Cancel</button></div>
        </form>
      </section>}
      {message.text && <p className={message.error ? 'nerr' : 'nok'} role={message.error ? 'alert' : 'status'}>{message.text}</p>}
    </div>
  );
}
