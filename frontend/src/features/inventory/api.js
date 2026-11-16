import { call } from "../../api/client.js";

export const listStock = (token) => call("/stock/", null, token);
export const listBatches = (token) => call("/batches/", null, token);
export const listPurchases = (token) => call("/purchases/", null, token);
export const createPurchase = (data, token) => call("/purchases/", data, token);
export const receivePurchase = (id, token) => call(`/purchases/${id}/receive/`, {}, token);
export const receiveStock = (data, token) => call("/receive/", data, token);
