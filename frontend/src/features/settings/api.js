import { API, call } from "../../api/client.js";

export const getSettings = (token) => call("/settings/", null, token);
export const updateSettings = (data, token) => call("/settings/", data, token, "PATCH");
export const getGoalSeries = (token) => call("/settings/series/", null, token);
export const verifySettingsEmail = (token) => call("/settings/verify-email/", {}, token);
export const requestAccountConfirmation = (action, token) => call("/account/confirm/", { action }, token);
export const deleteAccount = (token, confirmation) => call("/account/delete/", { token, confirmation });

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
