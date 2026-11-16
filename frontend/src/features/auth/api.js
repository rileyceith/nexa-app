import { call } from "../../api/client.js";

export const register = (data) => call("/auth/register/", data);
export const login = (data) => call("/auth/login/", data);
export const requestPasswordReset = (data) => call("/auth/password-reset/", data);
export const resetPassword = (data) => call("/auth/password-reset/confirm/", data);
export const verifyMagicLink = (token) => call("/auth/verify/", { token });
export const currentUser = (token) => call("/me/", null, token);
export const logout = (token) => call("/auth/logout/", {}, token);
