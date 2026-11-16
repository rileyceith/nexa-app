import { call } from "../../api/client.js";

export const listSales = (token) => call("/sales/", null, token);
export const createSale = (data, token) => call("/sales/", data, token);
export const updateSale = (id, data, token) => call(`/sales/${id}/`, data, token, "PATCH");
export const listExpenses = (month, token) => call(`/expenses/?month=${month}`, null, token);
export const createExpense = (data, token) => call("/expenses/", data, token);
