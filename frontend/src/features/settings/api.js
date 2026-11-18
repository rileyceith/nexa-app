import { API, call } from "../../api/client.js";

export const getSettings = (token) => call("/settings/", null, token);
export const updateSettings = (data, token) => call("/settings/", data, token, "PATCH");
export const getGoalSeries = (token) => call("/settings/series/", null, token);
export const verifySettingsEmail = (token) => call("/settings/verify-email/", {}, token);
export const requestAccountConfirmation = (action, token) => call("/account/confirm/", { action }, token);
export const deleteAccount = (token, confirmation) => call("/account/delete/", { token, confirmation });
export const updateAccountProfile = (data, token) => call("/account/profile/", data, token, "PATCH");
export const listAccountSessions = (token) => call("/account/sessions/", null, token);
export const requestSecurityCode = (data, token) => call("/account/security/request/", data, token);
export const confirmSecurityCode = (data, token) => call("/account/security/confirm/", data, token);
export const getTeam = (token) => call("/team/", null, token);
export const setTeamSharing = (enabled, token) => call("/team/sharing/", { team_sharing_enabled: enabled }, token, "PATCH");
export const inviteTeamMember = (data, token) => call("/team/invitations/", data, token);
export const updateTeamMember = (id, data, token) => call(`/team/members/${id}/`, data, token, "PATCH");
export const removeTeamMember = (id, token) => call(`/team/members/${id}/`, {}, token, "DELETE");
export const cancelTeamInvitation = (id, token) => call(`/team/invitations/${id}/`, {}, token, "DELETE");
export const previewTeamInvitation = (inviteToken) => call("/team/invitations/preview/", { token: inviteToken });
export const acceptTeamInvitation = (inviteToken, token) => call("/team/invitations/accept/", { token: inviteToken }, token);

export async function exportAccountData(token, confirmation) {
  if (!API) throw new Error("The mobile app's server address has not been configured.");
  let response;
  try {
    response = await fetch(API + "/account/export/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token, confirmation }),
    });
  } catch {
    throw new Error("Cannot reach the server. Try again.");
  }
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.error || "The export could not be created.");
  }
  return response.blob();
}
