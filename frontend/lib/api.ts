// Thin client for the GEO Audit API.
//
// The API base URL is injected at build/run time via NEXT_PUBLIC_API_BASE_URL
// (defaults to the local dev API). Artifact URLs returned by the API are
// relative, so we resolve them against the same base.

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export interface AuditFinding {
  severity: "ok" | "warn" | "fail";
  message: string;
  recommendation: string;
}

export interface AuditCategory {
  key: string;
  name: string;
  score: number;
  max_score: number;
  ratio: number;
  findings: AuditFinding[];
}

export interface AuditResult {
  audit_id: string;
  url: string;
  final_url: string;
  reachable: boolean;
  error: string | null;
  geo_score: number;
  max_score: number;
  grade: string;
  rendered_with: string;
  categories: AuditCategory[];
  html_url: string | null;
  pdf_url: string | null;
}

export interface AuditInput {
  url: string;
  client?: string;
  render_js?: boolean;
}

export async function runAudit(input: AuditInput): Promise<AuditResult> {
  const res = await fetch(`${API_BASE_URL}/audits`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });

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

  return (await res.json()) as AuditResult;
}

// Resolve a relative artifact path (e.g. /audits/<id>/report.pdf) to a full URL.
export function artifactUrl(path: string | null): string | null {
  if (!path) return null;
  return `${API_BASE_URL}${path}`;
}
