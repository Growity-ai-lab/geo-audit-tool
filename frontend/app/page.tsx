"use client";

import { useEffect, useState } from "react";
import {
  artifactUrl,
  AuthError,
  clearToken,
  fetchCurrentUser,
  getToken,
  login,
  runAudit,
  type AuditResult,
  type CurrentUser,
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
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [checking, setChecking] = useState(true);

  // On mount, validate any stored token.
  useEffect(() => {
    if (!getToken()) {
      setChecking(false);
      return;
    }
    fetchCurrentUser()
      .then(setUser)
      .catch(() => clearToken())
      .finally(() => setChecking(false));
  }, []);

  function onLoggedOut() {
    clearToken();
    setUser(null);
  }

  if (checking) {
    return (
      <main style={{ maxWidth: 820, margin: "0 auto", padding: "48px 20px" }}>
        <p style={{ color: "#9fb0c7" }}>Yükleniyor…</p>
      </main>
    );
  }

  if (!user) {
    return <LoginForm onSuccess={setUser} />;
  }

  return <AuditTool user={user} onLogout={onLoggedOut} />;
}

function LoginForm({ onSuccess }: { onSuccess: (u: CurrentUser) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await login(email.trim(), password);
      const me = await fetchCurrentUser();
      onSuccess(me);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Giriş başarısız.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main style={{ maxWidth: 420, margin: "0 auto", padding: "72px 20px" }}>
      <h1 style={{ fontSize: 24, marginBottom: 4 }}>GEO Audit — Giriş</h1>
      <p style={{ color: "#9fb0c7", marginTop: 0 }}>Devam etmek için giriş yapın.</p>
      <form onSubmit={onSubmit} style={{ ...cardStyle, display: "grid", gap: 12, marginTop: 20 }}>
        <label style={{ display: "grid", gap: 6 }}>
          <span>E-posta</span>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            style={inputStyle}
          />
        </label>
        <label style={{ display: "grid", gap: 6 }}>
          <span>Parola</span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            style={inputStyle}
          />
        </label>
        <button type="submit" disabled={loading} style={buttonStyle(loading)}>
          {loading ? "Giriş yapılıyor…" : "Giriş yap"}
        </button>
        {error && <div style={{ color: "#fecaca" }}>{error}</div>}
      </form>
    </main>
  );
}

function AuditTool({ user, onLogout }: { user: CurrentUser; onLogout: () => void }) {
  const [url, setUrl] = useState("");
  const [client, setClient] = useState("");
  const [renderJs, setRenderJs] = useState(false);
  const [loading, setLoading] = useState(false);
  const [statusText, setStatusText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AuditResult | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!url.trim()) return;
    setLoading(true);
    setStatusText(null);
    setError(null);
    setResult(null);
    try {
      const res = await runAudit(
        {
          url: url.trim(),
          client: client.trim() || undefined,
          render_js: renderJs,
        },
        (s) => setStatusText(s === "queued" ? "Kuyrukta…" : "Çalışıyor…"),
      );
      if (res.status === "error") {
        setError(res.error || "Denetim başarısız oldu.");
      } else {
        setResult(res);
      }
    } catch (err) {
      if (err instanceof AuthError) {
        onLogout();
        return;
      }
      setError(err instanceof Error ? err.message : "Bilinmeyen hata.");
    } finally {
      setLoading(false);
      setStatusText(null);
    }
  }

  const pdfUrl = artifactUrl(result?.pdf_url ?? null);
  const htmlUrl = artifactUrl(result?.html_url ?? null);

  return (
    <main style={{ maxWidth: 820, margin: "0 auto", padding: "48px 20px" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 8,
        }}
      >
        <span style={{ color: "#9fb0c7", fontSize: 14 }}>{user.email}</span>
        <button onClick={onLogout} style={{ ...linkButton("#334155"), border: "none", cursor: "pointer" }}>
          Çıkış
        </button>
      </div>
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
          {loading ? statusText ?? "Denetleniyor…" : "Denetle"}
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

      {result && (
        <ResultView
          result={result}
          pdfUrl={pdfUrl}
          htmlUrl={htmlUrl}
          requestedJs={renderJs}
        />
      )}
    </main>
  );
}

function ResultView({
  result,
  pdfUrl,
  htmlUrl,
  requestedJs,
}: {
  result: AuditResult;
  pdfUrl: string | null;
  htmlUrl: string | null;
  requestedJs: boolean;
}) {
  if (!result.reachable) {
    return (
      <div style={{ ...cardStyle, marginTop: 24 }}>
        <h2 style={{ marginTop: 0 }}>Sayfaya erişilemedi</h2>
        <p style={{ color: "#9fb0c7" }}>{result.error ?? "Bilinmeyen hata."}</p>
      </div>
    );
  }

  const gradeColor = GRADE_COLORS[result.grade ?? ""] ?? "#9fb0c7";
  const score = Math.round(result.geo_score ?? 0);

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
          <span style={{ fontSize: 30, fontWeight: 700 }}>{score}</span>
        </div>
        <div>
          <div style={{ fontSize: 20, fontWeight: 700 }}>
            GEO Score: {score}/100{" "}
            <span style={{ color: gradeColor }}>({result.grade})</span>
          </div>
          <div style={{ color: "#9fb0c7", marginTop: 4 }}>{result.final_url}</div>
          <div style={{ color: "#647892", fontSize: 13, marginTop: 2 }}>
            Render: {result.rendered_with}
            {requestedJs && result.rendered_with !== "playwright" && (
              <span style={{ color: "#f59e0b" }}>
                {" "}— JS render kullanılamadı, ham HTML'e düşüldü
              </span>
            )}
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
