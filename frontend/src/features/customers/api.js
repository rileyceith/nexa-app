import { call } from "../../api/client.js";

export const listCustomers = (token) => call("/customers/", null, token);
