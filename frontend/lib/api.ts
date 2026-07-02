// Thin client for the GEO Audit API.
//
// The API base URL is injected at build/run time via NEXT_PUBLIC_API_BASE_URL
// (defaults to the local dev API). Artifact URLs returned by the API are
// relative, so we resolve them against the same base.

// Trailing slash stripped so `${API_BASE_URL}/auth/login`-style calls never
// produce a double slash regardless of how the env var was entered.
export const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"
).replace(/\/+$/, "");

const TOKEN_KEY = "geo_audit_token";

// --- Token storage -------------------------------------------------------- //

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

function setToken(token: string): void {
  if (typeof window !== "undefined") window.localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  if (typeof window !== "undefined") window.localStorage.removeItem(TOKEN_KEY);
}

function authHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/** Raised when a request fails because the user is not (or no longer) authed. */
export class AuthError extends Error {}

export interface CurrentUser {
  id: string;
  email: string;
  role: string;
  is_active: boolean;
  created_at: string;
}

/** Log in via the OAuth2 password flow (form-encoded) and store the token. */
export async function login(email: string, password: string): Promise<void> {
  const body = new URLSearchParams({ username: email, password });
  const res = await fetch(`${API_BASE_URL}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  if (!res.ok) {
    throw new AuthError(
      res.status === 401 ? "E-posta veya parola hatalı." : `Giriş başarısız (HTTP ${res.status}).`,
    );
  }
  const data = await res.json();
  setToken(data.access_token);
}

export async function fetchCurrentUser(): Promise<CurrentUser> {
  const res = await fetch(`${API_BASE_URL}/auth/me`, { headers: authHeaders() });
  if (res.status === 401) {
    clearToken();
    throw new AuthError("Oturum süresi doldu.");
  }
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return (await res.json()) as CurrentUser;
}

export interface AuditFinding {
  severity: "ok" | "warn" | "fail";
  message: string;
  recommendation: string;
  // Set only when automated detection was inconclusive (a WAF/rate-limit
  // blocked verification) — the UI offers a manual-confirm checkbox for it.
  override_key: string | null;
}

export interface AuditCategory {
  key: string;
  name: string;
  score: number;
  max_score: number;
  ratio: number;
  findings: AuditFinding[];
}

export type AuditStatus = "queued" | "running" | "done" | "error";

export interface RenderDelta {
  key: string;
  name: string;
  raw: number;
  rendered: number;
  delta: number;
  max_score: number;
}

export interface RenderComparison {
  raw: { geo_score: number; grade: string };
  rendered: { geo_score: number; grade: string };
  delta_total: number;
  deltas: RenderDelta[];
  spa_suspected: boolean;
}

export interface AuditResult {
  audit_id: string;
  url: string;
  final_url: string | null;
  reachable: boolean | null;
  error: string | null;
  geo_score: number | null;
  max_score: number | null;
  grade: string | null;
  rendered_with: string | null;
  categories: AuditCategory[];
  spa_suspected: boolean;
  render_comparison: RenderComparison | null;
  // Manually confirmed corrections for ambiguous findings, keyed by
  // AuditFinding.override_key (e.g. { sitemap_exists: true }).
  overrides: Record<string, boolean>;
  html_url: string | null;
  pdf_url: string | null;
  status: AuditStatus;
}

export interface AuditInput {
  url: string;
  client?: string;
  render_js?: boolean;
  compare_render?: boolean;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const POLL_INTERVAL_MS = 1500;
const POLL_MAX_ATTEMPTS = 120; // ~3 minutes

/** Fetch a single audit's current state. */
export async function getAudit(auditId: string): Promise<AuditResult> {
  const res = await fetch(`${API_BASE_URL}/audits/${auditId}`, {
    headers: authHeaders(),
  });
  if (res.status === 401) {
    clearToken();
    throw new AuthError("Oturum süresi doldu. Lütfen tekrar giriş yapın.");
  }
  if (!res.ok) throw new Error(`Audit alınamadı (HTTP ${res.status}).`);
  return (await res.json()) as AuditResult;
}

/**
 * Confirm (or retract) a manual correction for an ambiguous finding — e.g.
 * `{ sitemap_exists: true }` after checking the URL by hand. Returns the
 * audit with the override applied (score/grade/findings already updated).
 */
export async function updateOverrides(
  auditId: string,
  overrides: Record<string, boolean>,
): Promise<AuditResult> {
  const res = await fetch(`${API_BASE_URL}/audits/${auditId}/overrides`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ overrides }),
  });
  if (res.status === 401) {
    clearToken();
    throw new AuthError("Oturum süresi doldu. Lütfen tekrar giriş yapın.");
  }
  if (!res.ok) throw new Error(`Düzeltme kaydedilemedi (HTTP ${res.status}).`);
  return (await res.json()) as AuditResult;
}

/**
 * Enqueue an audit and poll until it reaches a terminal status.
 *
 * `onStatus` (optional) reports queued/running transitions for the UI. With the
 * eager backend the POST already returns "done"; with a real worker we poll.
 */
export async function runAudit(
  input: AuditInput,
  onStatus?: (status: AuditStatus) => void,
): Promise<AuditResult> {
  const res = await fetch(`${API_BASE_URL}/audits`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(input),
  });

  if (res.status === 401) {
    clearToken();
    throw new AuthError("Oturum süresi doldu. Lütfen tekrar giriş yapın.");
  }
  if (!res.ok) {
    let detail = `İstek başarısız (HTTP ${res.status}).`;
    try {
      const body = await res.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      /* ignore parse errors */
    }
    throw new Error(detail);
  }

  let result = (await res.json()) as AuditResult;
  let attempts = 0;
  while (
    result.status !== "done" &&
    result.status !== "error" &&
    attempts < POLL_MAX_ATTEMPTS
  ) {
    onStatus?.(result.status);
    await sleep(POLL_INTERVAL_MS);
    result = await getAudit(result.audit_id);
    attempts += 1;
  }
  return result;
}

// Resolve a relative artifact path (e.g. /audits/<id>/report.pdf) to a full URL.
export function artifactUrl(path: string | null): string | null {
  if (!path) return null;
  return `${API_BASE_URL}${path}`;
}
