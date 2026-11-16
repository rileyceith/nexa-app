import { call } from "../../api/client.js";

export const listProducts = (token) => call("/products/", null, token);
export const listSuppliers = (token) => call("/suppliers/", null, token);
export const getProduct = (id, token) => call(`/products/${id}/`, null, token);
export const saveProduct = (id, data, token) => call(`/products/${id}/`, data, token, "PATCH");
export const createProduct = (data, token) => call("/products/", data, token);
