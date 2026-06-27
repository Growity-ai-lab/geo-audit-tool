"use client";

import { useState } from "react";
import {
  artifactUrl,
  runAudit,
  type AuditResult,
} from "../lib/api";

const GRADE_COLORS: Record<string, string> = {
  A: "#22c55e",
  B: "#84cc16",
  C: "#eab308",
  D: "#f59e0b",
  E: "#f97316",
  F: "#ef4444",
};

function ratioColor(ratio: number): string {
  if (ratio >= 0.8) return "#22c55e";
  if (ratio >= 0.5) return "#eab308";
  return "#ef4444";
}

export default function Home() {
  const [url, setUrl] = useState("");
  const [client, setClient] = useState("");
  const [renderJs, setRenderJs] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AuditResult | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!url.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await runAudit({
        url: url.trim(),
        client: client.trim() || undefined,
        render_js: renderJs,
      });
      setResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Bilinmeyen hata.");
    } finally {
      setLoading(false);
    }
  }

  const pdfUrl = artifactUrl(result?.pdf_url ?? null);
  const htmlUrl = artifactUrl(result?.html_url ?? null);

  return (
    <main style={{ maxWidth: 820, margin: "0 auto", padding: "48px 20px" }}>
      <h1 style={{ fontSize: 28, marginBottom: 4 }}>GEO Audit</h1>
      <p style={{ color: "#9fb0c7", marginTop: 0 }}>
        Bir URL girin; AI arama motorları için GEO/AIO hazırlık skorunu ve markalı
        raporu alın.
      </p>

      <form
        onSubmit={onSubmit}
        style={{
          display: "grid",
          gap: 12,
          background: "#111a2e",
          border: "1px solid #1f2c47",
          borderRadius: 12,
          padding: 20,
          marginTop: 20,
        }}
      >
        <label style={{ display: "grid", gap: 6 }}>
          <span>Denetlenecek URL</span>
          <input
            type="text"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="dardanel.com.tr"
            required
            style={inputStyle}
          />
        </label>

        <label style={{ display: "grid", gap: 6 }}>
          <span>Müşteri adı (opsiyonel — rapor kapağında görünür)</span>
          <input
            type="text"
            value={client}
            onChange={(e) => setClient(e.target.value)}
            placeholder="Dardanel"
            style={inputStyle}
          />
        </label>

        <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <input
            type="checkbox"
            checked={renderJs}
            onChange={(e) => setRenderJs(e.target.checked)}
          />
          <span>JavaScript ile render et (SPA siteleri için)</span>
        </label>

        <button type="submit" disabled={loading} style={buttonStyle(loading)}>
          {loading ? "Denetleniyor…" : "Denetle"}
        </button>
      </form>

      {error && (
        <div
          style={{
            marginTop: 20,
            padding: 16,
            borderRadius: 10,
            background: "#3a1620",
            border: "1px solid #7f1d1d",
            color: "#fecaca",
          }}
        >
          {error}
        </div>
      )}

      {result && <ResultView result={result} pdfUrl={pdfUrl} htmlUrl={htmlUrl} />}
    </main>
  );
}

function ResultView({
  result,
  pdfUrl,
  htmlUrl,
}: {
  result: AuditResult;
  pdfUrl: string | null;
  htmlUrl: string | null;
}) {
  if (!result.reachable) {
    return (
      <div style={{ ...cardStyle, marginTop: 24 }}>
        <h2 style={{ marginTop: 0 }}>Sayfaya erişilemedi</h2>
        <p style={{ color: "#9fb0c7" }}>{result.error ?? "Bilinmeyen hata."}</p>
      </div>
    );
  }

  const gradeColor = GRADE_COLORS[result.grade] ?? "#9fb0c7";

  return (
    <div style={{ marginTop: 24, display: "grid", gap: 16 }}>
      <div
        style={{
          ...cardStyle,
          display: "flex",
          alignItems: "center",
          gap: 20,
        }}
      >
        <div
          style={{
            width: 96,
            height: 96,
            borderRadius: "50%",
            display: "grid",
            placeItems: "center",
            border: `6px solid ${gradeColor}`,
            flexShrink: 0,
          }}
        >
          <span style={{ fontSize: 30, fontWeight: 700 }}>
            {Math.round(result.geo_score)}
          </span>
        </div>
        <div>
          <div style={{ fontSize: 20, fontWeight: 700 }}>
            GEO Score: {Math.round(result.geo_score)}/100{" "}
            <span style={{ color: gradeColor }}>({result.grade})</span>
          </div>
          <div style={{ color: "#9fb0c7", marginTop: 4 }}>{result.final_url}</div>
          <div style={{ color: "#647892", fontSize: 13, marginTop: 2 }}>
            Render: {result.rendered_with}
          </div>
        </div>
      </div>

      <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
        {pdfUrl && (
          <a href={pdfUrl} target="_blank" rel="noreferrer" style={linkButton("#2563eb")}>
            PDF raporu indir
          </a>
        )}
        {htmlUrl && (
          <a href={htmlUrl} target="_blank" rel="noreferrer" style={linkButton("#334155")}>
            HTML raporu aç
          </a>
        )}
      </div>

      <div style={{ ...cardStyle }}>
        <h2 style={{ marginTop: 0, fontSize: 18 }}>Kategoriler</h2>
        <div style={{ display: "grid", gap: 10 }}>
          {result.categories.map((cat) => {
            const pct = cat.max_score ? cat.ratio : 0;
            return (
              <div key={cat.key}>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    fontSize: 14,
                    marginBottom: 4,
                  }}
                >
                  <span>{cat.name}</span>
                  <span style={{ color: "#9fb0c7" }}>
                    {cat.score.toFixed(1)} / {cat.max_score}
                  </span>
                </div>
                <div
                  style={{
                    height: 8,
                    borderRadius: 4,
                    background: "#1f2c47",
                    overflow: "hidden",
                  }}
                >
                  <div
                    style={{
                      width: `${Math.round(pct * 100)}%`,
                      height: "100%",
                      background: ratioColor(pct),
                    }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  padding: "10px 12px",
  borderRadius: 8,
  border: "1px solid #2a3a5c",
  background: "#0b1220",
  color: "#e6edf6",
  fontSize: 15,
};

const cardStyle: React.CSSProperties = {
  background: "#111a2e",
  border: "1px solid #1f2c47",
  borderRadius: 12,
  padding: 20,
};

function buttonStyle(loading: boolean): React.CSSProperties {
  return {
    padding: "11px 16px",
    borderRadius: 8,
    border: "none",
    background: loading ? "#1e3a8a" : "#2563eb",
    color: "white",
    fontSize: 15,
    fontWeight: 600,
    cursor: loading ? "default" : "pointer",
  };
}

function linkButton(bg: string): React.CSSProperties {
  return {
    padding: "10px 16px",
    borderRadius: 8,
    background: bg,
    color: "white",
    textDecoration: "none",
    fontWeight: 600,
    fontSize: 14,
  };
}
