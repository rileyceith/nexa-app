import { call } from "../../api/client.js";

export const getInsights = (token) => call("/insights/", null, token);
export const chat = (data, token) => call("/assistant/chat/", data, token);
export const analyze = (data, token) => call("/assistant/analyze/", data, token);
