import { useEffect, useState } from "react";
import { TOKEN_KEY } from "../../api/client.js";
import {
  cancelTeamInvitation, getTeam, inviteTeamMember, removeTeamMember,
  setTeamSharing, updateTeamMember,
} from "./api.js";

const SCOPES = [
  ["dashboard", "Overview"],
  ["sales", "Sales"],
  ["inventory", "Inventory"],
  ["customers", "Customers"],
  ["expenses", "Expenses"],
  ["reports", "Reports"],
  ["insights", "Insights"],
  ["settings", "Business settings"],
];
const token = () => localStorage.getItem(TOKEN_KEY);
const emptyPermissions = () => Object.fromEntries(
  SCOPES.map(([scope]) => [scope, { view: false, edit: false }]),
);

function PermissionFields({ value, onChange, disabled = false }) {
  const update = (scope, action, checked) => {
    const actions = { ...value[scope], [action]: checked };
    if (action === "view" && !checked) actions.edit = false;
    if (action === "edit" && checked) actions.view = true;
    onChange({ ...value, [scope]: actions });
  };
  return <div className='team-permissions'>
    {SCOPES.map(([scope, label]) => <fieldset key={scope} disabled={disabled}>
      <legend>{label}</legend>
      <label><input type='checkbox' checked={!!value[scope]?.view} onChange={(event) => update(scope, "view", event.target.checked)} /> View</label>
      <label><input type='checkbox' checked={!!value[scope]?.edit} onChange={(event) => update(scope, "edit", event.target.checked)} /> Edit</label>
    </fieldset>)}
  </div>;
}

function Member({ member, owner, onSave, onRemove, busy }) {
  const [permissions, setPermissions] = useState(member.permissions);
  const [canManage, setCanManage] = useState(member.can_manage_members);
  const canEdit = owner || (!member.can_manage_members && !member.is_current_user);
  return <li className='team-member'>
    <div><strong>{member.username}</strong><span>{member.email}</span>
      <small>Joined {new Date(member.created_at).toLocaleDateString()}</small>
    </div>
    <PermissionFields value={permissions} onChange={setPermissions} disabled={!canEdit || busy} />
    {owner && <label className='team-admin'><input type='checkbox' checked={canManage} disabled={busy} onChange={(event) => setCanManage(event.target.checked)} /> Can manage team</label>}
    <div className='goal-actions'>
      <button type='button' className='btn glass' disabled={busy || !canEdit} onClick={() => onSave(member.id, permissions, canManage)}>Save access</button>
      <button type='button' className='btn glass' disabled={busy || (!owner && (!canEdit || member.can_manage_members))} onClick={() => onRemove(member.id)}>Remove</button>
    </div>
  </li>;
}

export default function TeamSettings({ workspace }) {
  const [team, setTeam] = useState(null);
  const [email, setEmail] = useState("");
  const [permissions, setPermissions] = useState(emptyPermissions);
  const [canManage, setCanManage] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState({ text: "", error: false });
  const owner = workspace?.role === "owner";

  const refresh = () => getTeam(token()).then(setTeam);
  useEffect(() => {
    refresh().catch((error) => setMessage({ text: error.message, error: true }));
  }, [workspace?.id]);

  const run = async (operation, success) => {
    setBusy(true);
    setMessage({ text: "", error: false });
    try {
      await operation();
      await refresh();
      setMessage({ text: success, error: false });
    } catch (error) {
      setMessage({ text: error.message, error: true });
    } finally { setBusy(false); }
  };

  const toggleSharing = () => {
    if (team.enabled && !window.confirm(
      "Disable team sharing? This revokes all member access and cancels pending invitations, but keeps everyone's separate account data.",
    )) return;
    run(
      () => setTeamSharing(!team.enabled, token()),
      team.enabled ? "Team sharing disabled. Member access was revoked." : "Team sharing enabled.",
    );
  };
  const invite = (event) => {
    event.preventDefault();
    run(async () => {
      await inviteTeamMember({ email: email.trim(), permissions, can_manage_members: canManage }, token());
      setEmail("");
      setPermissions(emptyPermissions());
      setCanManage(false);
    }, "Invitation sent. It expires in seven days.");
  };

  if (!team) return <section className='dc'><p>Loading team settings…</p>
    {message.text && <p className='nerr' role='alert'>{message.text}</p>}</section>;

  return <div className='dgrid team-settings'>
    <section className='dc span3'>
      <span className='account-kicker'>BUSINESS WORKSPACE</span>
      <h2>{team.business_name} team</h2>
      <p>Each person signs in to their own Nexa account. Their personal business stays separate from this workspace.</p>
      {owner
        ? <label className='team-admin'><input type='checkbox' checked={team.enabled} disabled={busy} onChange={toggleSharing} /> Enable team sharing</label>
        : <p>Team sharing is managed by this business's owner.</p>}
    </section>
    {team.enabled && <>
      <section className='dc span3'>
        <h3>Invite a member</h3>
        <p>Invitations are sent by email and expire after seven days. The invited person must sign in with that email address.</p>
        <form className='nform' onSubmit={invite}>
          <label>Email address<input type='email' required maxLength='254' value={email} onChange={(event) => setEmail(event.target.value)} /></label>
          <PermissionFields value={permissions} onChange={setPermissions} disabled={busy} prefix='invite' />
          {owner && <label className='team-admin'><input type='checkbox' checked={canManage} disabled={busy} onChange={(event) => setCanManage(event.target.checked)} /> Allow this member to manage the team</label>}
          <button type='submit' className='btn iri' disabled={busy}>Send invitation</button>
        </form>
      </section>
      <section className='dc span3'>
        <h3>Members</h3>
        {team.members.length === 0 ? <p>No members yet.</p> : <ul className='team-list'>
          {team.members.map((member) => <Member key={member.id} member={member} owner={owner} busy={busy}
            onSave={(id, grants, can_manage_members) => run(
              () => updateTeamMember(id, { permissions: grants, can_manage_members }, token()),
              "Member access updated.",
            )}
            onRemove={(id) => {
              if (window.confirm(`Remove ${member.username} from this business?`)) {
                run(() => removeTeamMember(id, token()), "Member removed.");
              }
            }} />)}
        </ul>}
      </section>
      <section className='dc span3'>
        <h3>Pending invitations</h3>
        {team.invitations.length === 0 ? <p>No pending invitations.</p> : <ul className='team-list'>
          {team.invitations.map((invitation) => <li key={invitation.id} className='team-invitation'>
            <div><strong>{invitation.email}</strong><small>Expires {new Date(invitation.expires_at).toLocaleString()}</small></div>
            <button type='button' className='btn glass' disabled={busy} onClick={() =>
              run(() => cancelTeamInvitation(invitation.id, token()), "Invitation canceled.")
            }>Cancel invitation</button>
          </li>)}
        </ul>}
      </section>
    </>}
    {message.text && <p className={message.error ? 'nerr' : 'nok'} role={message.error ? 'alert' : 'status'}>{message.text}</p>}
  </div>;
}
