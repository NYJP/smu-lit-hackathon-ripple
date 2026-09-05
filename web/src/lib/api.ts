/**
 * The one fetch wrapper (PRD section 9 preamble). Every call to the Ripple
 * API MUST go through this module, because it is the one place
 * `credentials: "include"` is set.
 *
 * Section 9: "the API binds to 127.0.0.1 only" and the web app runs on a
 * different port (:3000 vs :8000) — different origins, same site. CORS
 * (api/main.py) allows the web origin with `allow_credentials=True`, and
 * the session cookie only ever reaches the API if the browser is told to
 * send it. Omitting `credentials: "include"` here is, per the PRD, "the
 * single most likely defect in the web build" — every authenticated call
 * would silently return 401 and look like a broken session rather than a
 * missing fetch option. It is set exactly once, in `request()` below, and
 * every helper in this file — and everywhere else in the app — must go
 * through `request()` rather than calling `fetch` directly.
 */

import type { ApiErrorBody } from "./types";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

/** Thrown for every non-2xx response, carrying the section 9 error envelope. */
export class ApiRequestError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: unknown;

  constructor(status: number, code: string, message: string, details: unknown) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
    this.code = code;
    this.details = details;
  }

  get isUnauthenticated(): boolean {
    return this.status === 401;
  }

  get isNotImplemented(): boolean {
    return this.status === 501;
  }
}

interface RequestOptions extends Omit<RequestInit, "credentials" | "body"> {
  /** Parsed and JSON-serialised for you, with the right Content-Type. */
  json?: unknown;
  /** Already-serialised body (e.g. FormData) — bypasses `json`. */
  body?: BodyInit;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { json, body, headers, ...rest } = options;

  const finalHeaders = new Headers(headers);
  let finalBody: BodyInit | undefined = body;
  if (json !== undefined) {
    finalHeaders.set("Content-Type", "application/json");
    finalBody = JSON.stringify(json);
  }

  const res = await fetch(`${API_BASE}${path}`, {
    ...rest,
    headers: finalHeaders,
    body: finalBody,
    // Section 9 preamble: set once, here, and never overridable by a caller
    // (deliberately not spread from `options` above).
    credentials: "include",
  });

  if (res.status === 204) {
    return undefined as T;
  }

  const text = await res.text();
  const data = text ? JSON.parse(text) : undefined;

  if (!res.ok) {
    const envelope = data as ApiErrorBody | undefined;
    throw new ApiRequestError(
      res.status,
      envelope?.error?.code ?? "error",
      envelope?.error?.message ?? "Request failed.",
      envelope?.error?.details ?? null
    );
  }

  return data as T;
}

export const api = {
  get: <T>(path: string, options?: RequestOptions) =>
    request<T>(path, { ...options, method: "GET" }),
  post: <T>(path: string, json?: unknown, options?: RequestOptions) =>
    request<T>(path, { ...options, method: "POST", json }),
  patch: <T>(path: string, json?: unknown, options?: RequestOptions) =>
    request<T>(path, { ...options, method: "PATCH", json }),
  delete: <T>(path: string, options?: RequestOptions) =>
    request<T>(path, { ...options, method: "DELETE" }),
};
