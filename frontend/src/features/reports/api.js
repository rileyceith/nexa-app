import { call } from "../../api/client.js";

export const getDashboard = (month, token) => call(`/dashboard/?month=${month}`, null, token);
export const getReports = (token) => call("/reports/", null, token);
