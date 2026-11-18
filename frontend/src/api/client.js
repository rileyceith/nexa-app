const LOCAL_DEV = location.protocol === "file:" || ["localhost", "127.0.0.1"].includes(location.hostname);
const LOCAL_API_HOST = location.protocol === "file:" ? "localhost" : location.hostname;

export const API = window.NEXA_MOBILE
  ? window.NEXA_API
  : (window.NEXA_API || (LOCAL_DEV ? `http://${LOCAL_API_HOST}:8000/api` : "https://api.Nexa-app.com/api"));
export const ADMIN_URL = API ? API.replace(/\/api\/?$/, "") + "/admin/" : "";
export const TOKEN_KEY = "nexa_token";
export const WORKSPACE_KEY = "nexa_workspace";

export function selectedWorkspace() {
  return localStorage.getItem(WORKSPACE_KEY);
}

export function selectWorkspace(id) {
  if (id == null) localStorage.removeItem(WORKSPACE_KEY);
  else localStorage.setItem(WORKSPACE_KEY, String(id));
}

export async function call(path, body, token, method) {
  if (!API) throw new Error("The mobile app's server address has not been configured.");
  let response;
  try {
    response = await fetch(API + path, {
      method: method || (body ? "POST" : "GET"),
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: "Bearer " + token } : {}),
        ...(token && selectedWorkspace() ? { "X-Nexa-Workspace": selectedWorkspace() } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new Error("Cannot reach the server. Start the backend and try again.");
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.error || (
      response.status === 404 && path.startsWith("/assistant/")
        ? "Assistant endpoints are unavailable. Restart Django and reload the app."
        : "Something went wrong."
    ));
    error.status = response.status;
    throw error;
  }
  return data;
}
