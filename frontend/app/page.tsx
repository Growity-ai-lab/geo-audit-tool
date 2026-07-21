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
  runBatch,
  runVisibility,
  updateOverrides,
  type AuditFinding,
  type AuditResult,
  type BatchAuditResult,
  type CurrentUser,
  type RenderComparison,
  type Targeting,
  type VisEngineResult,
  type VisibilityReport,
  type VisibilityResult,
} from "../lib/api";

const PAGE_TYPES: { value: string; label: string }[] = [
  { value: "generic", label: "Genel" },
  { value: "homepage", label: "Ana Sayfa" },
  { value: "category", label: "Kategori" },
  { value: "product", label: "Ürün" },
  { value: "blog", label: "Blog / Makale" },
];

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

type Mode = "single" | "list" | "visibility";

function AuditTool({ user, onLogout }: { user: CurrentUser; onLogout: () => void }) {
  const [mode, setMode] = useState<Mode>("single");
  const [url, setUrl] = useState("");
  const [urlsText, setUrlsText] = useState("");
  const [client, setClient] = useState("");
  const [renderJs, setRenderJs] = useState(false);
  const [compareRender, setCompareRender] = useState(false);
  const [pageType, setPageType] = useState("generic");
  const [targetKeyword, setTargetKeyword] = useState("");
  // AI Visibility inputs.
  const [brand, setBrand] = useState("");
  const [domain, setDomain] = useState("");
  const [topic, setTopic] = useState("");
  const [manualPromptsText, setManualPromptsText] = useState("");
  const [loading, setLoading] = useState(false);
  const [statusText, setStatusText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AuditResult | null>(null);
  const [batchResult, setBatchResult] = useState<BatchAuditResult | null>(null);
  const [visResult, setVisResult] = useState<VisibilityResult | null>(null);

  function reset() {
    setResult(null);
    setBatchResult(null);
    setVisResult(null);
    setError(null);
  }

  async function onSubmitVisibility(e: React.FormEvent) {
    e.preventDefault();
    if (!brand.trim() || !domain.trim()) return;
    setLoading(true);
    setStatusText(null);
    reset();
    try {
      const res = await runVisibility(
        {
          brand: brand.trim(),
          domain: domain.trim(),
          topic: topic.trim() || undefined,
          manual_prompts: manualPromptsText
            .split("\n")
            .map((p) => p.trim())
            .filter(Boolean),
        },
        (s) => setStatusText(s === "queued" ? "Kuyrukta…" : "AI motorları sorgulanıyor…"),
      );
      if (res.status === "error") setError(res.error || "Görünürlük analizi başarısız oldu.");
      else setVisResult(res);
    } catch (err) {
      if (err instanceof AuthError) return onLogout();
      setError(err instanceof Error ? err.message : "Bilinmeyen hata.");
    } finally {
      setLoading(false);
      setStatusText(null);
    }
  }

  async function onSubmitSingle(e: React.FormEvent) {
    e.preventDefault();
    if (!url.trim()) return;
    setLoading(true);
    setStatusText(null);
    reset();
    try {
      const res = await runAudit(
        {
          url: url.trim(),
          client: client.trim() || undefined,
          render_js: renderJs || compareRender,
          compare_render: compareRender,
          page_type: pageType,
          target_keyword: targetKeyword.trim() || undefined,
        },
        (s) => setStatusText(s === "queued" ? "Kuyrukta…" : "Çalışıyor…"),
      );
      if (res.status === "error") setError(res.error || "Denetim başarısız oldu.");
      else setResult(res);
    } catch (err) {
      if (err instanceof AuthError) return onLogout();
      setError(err instanceof Error ? err.message : "Bilinmeyen hata.");
    } finally {
      setLoading(false);
      setStatusText(null);
    }
  }

  async function onSubmitList(e: React.FormEvent) {
    e.preventDefault();
    const urls = urlsText
      .split("\n")
      .map((u) => u.trim())
      .filter(Boolean);
    if (urls.length === 0) return;
    setLoading(true);
    setStatusText(null);
    reset();
    try {
      const res = await runBatch(
        { urls, client: client.trim() || undefined, render_js: renderJs },
        (s) => setStatusText(s === "queued" ? "Kuyrukta…" : "Sayfalar denetleniyor…"),
      );
      if (res.status === "error") setError("Liste denetimi başarısız oldu.");
      else setBatchResult(res);
    } catch (err) {
      if (err instanceof AuthError) return onLogout();
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
        Tek bir URL ya da bir URL listesi girin; AI arama motorları için GEO/AIO
        hazırlık skorunu ve markalı raporu alın.
      </p>

      {/* Mode toggle */}
      <div style={{ display: "flex", gap: 8, marginTop: 20 }}>
        <button type="button" onClick={() => { setMode("single"); reset(); }} style={tabStyle(mode === "single")}>
          Tek URL
        </button>
        <button type="button" onClick={() => { setMode("list"); reset(); }} style={tabStyle(mode === "list")}>
          URL Listesi
        </button>
        <button type="button" onClick={() => { setMode("visibility"); reset(); }} style={tabStyle(mode === "visibility")}>
          AI Görünürlük
        </button>
      </div>

      <form
        onSubmit={
          mode === "single" ? onSubmitSingle : mode === "list" ? onSubmitList : onSubmitVisibility
        }
        style={{
          display: "grid",
          gap: 12,
          background: "#111a2e",
          border: "1px solid #1f2c47",
          borderRadius: 12,
          borderTopLeftRadius: 0,
          padding: 20,
          marginTop: 0,
        }}
      >
        {mode === "single" && (
          <label style={{ display: "grid", gap: 6 }}>
            <span>Denetlenecek URL</span>
            <input
              type="text" value={url} onChange={(e) => setUrl(e.target.value)}
              placeholder="dardanel.com.tr" required style={inputStyle}
            />
          </label>
        )}
        {mode === "list" && (
          <label style={{ display: "grid", gap: 6 }}>
            <span>URL listesi (her satıra bir URL — SEO/GEO hedefli sayfalar)</span>
            <textarea
              value={urlsText} onChange={(e) => setUrlsText(e.target.value)}
              placeholder={"dardanel.com.tr\ndardanel.com.tr/urunler\ndardanel.com.tr/blog"}
              rows={6} required style={{ ...inputStyle, resize: "vertical", fontFamily: "inherit" }}
            />
          </label>
        )}
        {mode === "visibility" && (
          <>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
              <label style={{ display: "grid", gap: 6 }}>
                <span>Marka adı</span>
                <input
                  type="text" value={brand} onChange={(e) => setBrand(e.target.value)}
                  placeholder="Tara Robotik" required style={inputStyle}
                />
              </label>
              <label style={{ display: "grid", gap: 6 }}>
                <span>Domain</span>
                <input
                  type="text" value={domain} onChange={(e) => setDomain(e.target.value)}
                  placeholder="tararobotik.com" required style={inputStyle}
                />
              </label>
            </div>
            <label style={{ display: "grid", gap: 6 }}>
              <span>Sektör / konu (opsiyonel — otomatik prompt üretimi için)</span>
              <input
                type="text" value={topic} onChange={(e) => setTopic(e.target.value)}
                placeholder="ör. robotik paletleme" style={inputStyle}
              />
            </label>
            <label style={{ display: "grid", gap: 6 }}>
              <span>Ek prompt&apos;lar (opsiyonel — her satıra bir soru; otomatik üretilenlere eklenir)</span>
              <textarea
                value={manualPromptsText} onChange={(e) => setManualPromptsText(e.target.value)}
                placeholder={"Endüstriyel makine besleme için en iyi robotik çözümler?"}
                rows={4} style={{ ...inputStyle, resize: "vertical", fontFamily: "inherit" }}
              />
            </label>
          </>
        )}

        {mode !== "visibility" && (
          <label style={{ display: "grid", gap: 6 }}>
            <span>Müşteri adı (opsiyonel — rapor kapağında görünür)</span>
            <input
              type="text" value={client} onChange={(e) => setClient(e.target.value)}
              placeholder="Dardanel" style={inputStyle}
            />
          </label>
        )}

        {mode === "single" && (
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <label style={{ display: "grid", gap: 6 }}>
              <span>Sayfa türü</span>
              <select value={pageType} onChange={(e) => setPageType(e.target.value)} style={inputStyle}>
                {PAGE_TYPES.map((pt) => (
                  <option key={pt.value} value={pt.value}>{pt.label}</option>
                ))}
              </select>
            </label>
            <label style={{ display: "grid", gap: 6 }}>
              <span>Hedef anahtar kelime (opsiyonel)</span>
              <input
                type="text" value={targetKeyword} onChange={(e) => setTargetKeyword(e.target.value)}
                placeholder="ör. ton balığı konservesi" style={inputStyle}
              />
            </label>
          </div>
        )}

        {mode !== "visibility" && (
          <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <input
              type="checkbox" checked={renderJs} disabled={mode === "single" && compareRender}
              onChange={(e) => setRenderJs(e.target.checked)}
            />
            <span>JavaScript ile render et (SPA siteleri için)</span>
          </label>
        )}

        {mode === "single" && (
          <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <input type="checkbox" checked={compareRender} onChange={(e) => setCompareRender(e.target.checked)} />
            <span>AI vs kullanıcı karşılaştır (ham HTML ↔ JS render farkı)</span>
          </label>
        )}

        {mode === "visibility" && (
          <div style={{ fontSize: 12.5, color: "#647892" }}>
            Prompt&apos;lar OpenAI, Perplexity ve Gemini&apos;de çalıştırılır; markanın
            cevaplarda anılıp anılmadığı ve kaynak gösterilip gösterilmediği ölçülür.
            Bu skor GEO skorundan ayrıdır.
          </div>
        )}

        <button type="submit" disabled={loading} style={buttonStyle(loading)}>
          {loading
            ? statusText ?? "Çalışıyor…"
            : mode === "single"
              ? "Denetle"
              : mode === "list"
                ? "Listeyi Denetle"
                : "Görünürlüğü Analiz Et"}
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
          onUpdate={setResult}
        />
      )}

      {batchResult && <BatchResultView result={batchResult} />}

      {visResult?.report && (
        <VisibilityResultView
          report={visResult.report}
          pdfUrl={artifactUrl(visResult.pdf_url)}
          htmlUrl={artifactUrl(visResult.html_url)}
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
  onUpdate,
}: {
  result: AuditResult;
  pdfUrl: string | null;
  htmlUrl: string | null;
  requestedJs: boolean;
  onUpdate: (r: AuditResult) => void;
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

      {result.render_comparison ? (
        <RenderComparisonView comparison={result.render_comparison} />
      ) : (
        result.spa_suspected && <SpaWarning />
      )}

      <OverridesPanel result={result} onUpdate={onUpdate} />

      {result.targeting && <TargetingView targeting={result.targeting} />}

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

/**
 * Findings the crawler could only mark "ambiguous" (a WAF/rate-limit blocked
 * verification, e.g. sitemap check hitting a Cloudflare block) carry an
 * override_key. This panel lets a team member confirm what they found by
 * checking the URL by hand, updating the score immediately.
 */
function OverridesPanel({
  result,
  onUpdate,
}: {
  result: AuditResult;
  onUpdate: (r: AuditResult) => void;
}) {
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const overridable = result.categories.flatMap((cat) =>
    cat.findings
      .filter((f): f is AuditFinding & { override_key: string } => !!f.override_key)
      .map((f) => ({ category: cat.name, finding: f })),
  );

  if (overridable.length === 0) return null;

  async function onToggle(key: string, checked: boolean) {
    setPending(key);
    setError(null);
    try {
      const updated = await updateOverrides(result.audit_id, { [key]: checked });
      onUpdate(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Düzeltme kaydedilemedi.");
    } finally {
      setPending(null);
    }
  }

  return (
    <div style={{ ...cardStyle, borderColor: "#b45309" }}>
      <h2 style={{ marginTop: 0, fontSize: 18 }}>Belirsiz Bulgular — Manuel Onay</h2>
      <p style={{ fontSize: 13, color: "#9fb0c7", marginTop: 0 }}>
        Bu kontroller otomatik olarak doğrulanamadı (istek engellenmiş/kısıtlanmış
        olabilir). URL&apos;yi kendiniz kontrol ettiyseniz işaretleyin; skor buna
        göre güncellenir.
      </p>
      <div style={{ display: "grid", gap: 10 }}>
        {overridable.map(({ category, finding }) => {
          const key = finding.override_key;
          const checked = result.overrides[key] === true;
          return (
            <label
              key={key}
              style={{
                display: "flex",
                alignItems: "flex-start",
                gap: 10,
                padding: "8px 0",
                borderTop: "1px solid #1f2c47",
                cursor: pending ? "default" : "pointer",
                opacity: pending && pending !== key ? 0.6 : 1,
              }}
            >
              <input
                type="checkbox"
                checked={checked}
                disabled={pending !== null}
                onChange={(e) => onToggle(key, e.target.checked)}
                style={{ marginTop: 3 }}
              />
              <div>
                <div style={{ fontSize: 13, color: "#9fb0c7" }}>{category}</div>
                <div style={{ fontSize: 14 }}>{finding.message}</div>
              </div>
            </label>
          );
        })}
      </div>
      {error && (
        <div style={{ color: "#fecaca", fontSize: 13, marginTop: 10 }}>{error}</div>
      )}
    </div>
  );
}

function BatchResultView({ result }: { result: BatchAuditResult }) {
  const gradeColor = GRADE_COLORS[result.grade ?? ""] ?? "#9fb0c7";
  const avg = Math.round(result.avg_score ?? 0);
  const reportHtml = artifactUrl(result.html_url);
  const reportPdf = artifactUrl(result.pdf_url);

  return (
    <div style={{ marginTop: 24, display: "grid", gap: 16 }}>
      <div style={{ ...cardStyle, display: "flex", alignItems: "center", gap: 20 }}>
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
          <span style={{ fontSize: 30, fontWeight: 700 }}>{avg}</span>
        </div>
        <div>
          <div style={{ fontSize: 20, fontWeight: 700 }}>
            Ortalama: {avg}/100 <span style={{ color: gradeColor }}>({result.grade})</span>
          </div>
          <div style={{ color: "#9fb0c7", marginTop: 4 }}>
            {result.url_count} sayfa · {result.reachable_count} erişilebilir
          </div>
        </div>
      </div>

      <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
        {reportPdf && (
          <a href={reportPdf} target="_blank" rel="noreferrer" style={linkButton("#2563eb")}>
            Strateji raporu (PDF)
          </a>
        )}
        {reportHtml && (
          <a href={reportHtml} target="_blank" rel="noreferrer" style={linkButton("#334155")}>
            Strateji raporu (HTML)
          </a>
        )}
      </div>

      {/* Per-page scores */}
      <div style={cardStyle}>
        <h2 style={{ marginTop: 0, fontSize: 18 }}>Sayfa Bazlı Skorlar</h2>
        <div style={{ display: "grid", gap: 4 }}>
          {result.pages.map((p) => {
            const pageHtml = artifactUrl(p.html_url);
            const c = GRADE_COLORS[p.grade ?? ""] ?? "#9fb0c7";
            return (
              <div
                key={p.audit_id}
                style={{
                  display: "grid",
                  gridTemplateColumns: "1fr auto auto",
                  gap: 12,
                  alignItems: "center",
                  fontSize: 14,
                  padding: "8px 0",
                  borderTop: "1px solid #1f2c47",
                }}
              >
                <span style={{ wordBreak: "break-all" }}>
                  {pageHtml ? (
                    <a href={pageHtml} target="_blank" rel="noreferrer" style={{ color: "#93c5fd" }}>
                      {p.final_url || p.url}
                    </a>
                  ) : (
                    p.final_url || p.url
                  )}
                </span>
                {p.reachable ? (
                  <>
                    <span style={{ color: "#9fb0c7" }}>{Math.round(p.geo_score ?? 0)}</span>
                    <span style={{ color: c, fontWeight: 700, minWidth: 20, textAlign: "right" }}>
                      {p.grade}
                    </span>
                  </>
                ) : (
                  <span style={{ gridColumn: "2 / 4", color: "#ef4444", textAlign: "right" }}>
                    erişilemedi
                  </span>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Category averages */}
      <div style={cardStyle}>
        <h2 style={{ marginTop: 0, fontSize: 18 }}>Kategori Ortalamaları</h2>
        <div style={{ display: "grid", gap: 10 }}>
          {result.category_averages.map((c) => (
            <div key={c.key}>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  fontSize: 14,
                  marginBottom: 4,
                }}
              >
                <span>{c.name}</span>
                <span style={{ color: "#9fb0c7" }}>
                  {c.avg_score.toFixed(1)} / {c.max_score}
                </span>
              </div>
              <div style={{ height: 8, borderRadius: 4, background: "#1f2c47", overflow: "hidden" }}>
                <div
                  style={{
                    width: `${Math.round(c.avg_ratio * 100)}%`,
                    height: "100%",
                    background: ratioColor(c.avg_ratio),
                  }}
                />
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Shared gaps / strategy */}
      {result.top_gaps.length > 0 && (
        <div style={cardStyle}>
          <h2 style={{ marginTop: 0, fontSize: 18 }}>Ortak Eksikler — Öncelikli Strateji</h2>
          <p style={{ fontSize: 13, color: "#9fb0c7", marginTop: 0 }}>
            Birden çok sayfada tekrarlayan eksikler; tek düzeltme tüm listeyi
            iyileştirir.
          </p>
          <div style={{ display: "grid", gap: 4 }}>
            {result.top_gaps.map((g, i) => (
              <div
                key={i}
                style={{
                  display: "flex",
                  gap: 12,
                  alignItems: "flex-start",
                  padding: "8px 0",
                  borderTop: "1px solid #1f2c47",
                }}
              >
                <span
                  style={{
                    flexShrink: 0,
                    fontSize: 11,
                    fontWeight: 800,
                    padding: "3px 9px",
                    borderRadius: 7,
                    background: g.severity === "fail" ? "#3a1620" : "#3a2e10",
                    color: g.severity === "fail" ? "#fecaca" : "#fcd34d",
                  }}
                >
                  {g.page_count} sayfa
                </span>
                <div>
                  <span style={{ fontWeight: 700 }}>{g.category}</span>
                  <span style={{ display: "block", color: "#9fb0c7", fontSize: 13, marginTop: 2 }}>
                    {g.recommendation || g.message}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function TargetingView({ targeting: t }: { targeting: Targeting }) {
  const findingColor = (sev: string) =>
    sev === "fail" ? "#ef4444" : sev === "warn" ? "#f59e0b" : "#22c55e";
  const findingBg = (sev: string) =>
    sev === "fail" ? "#3a1620" : sev === "warn" ? "#3a2e10" : "#12261a";

  return (
    <div style={{ ...cardStyle, borderColor: "#6d28d9" }}>
      <h2 style={{ marginTop: 0, fontSize: 18 }}>🎯 Hedefleme — {t.page_type_label}</h2>
      <p style={{ fontSize: 13, color: "#9fb0c7", marginTop: 0 }}>
        Sayfa türüne ve hedef anahtar kelimeye özel değerlendirme; GEO skorunu
        etkilemez.
      </p>

      {t.keyword_score !== null && (
        <div
          style={{
            background: "#0b1220",
            border: "1px solid #1f2c47",
            borderRadius: 10,
            padding: 14,
            marginBottom: 14,
          }}
        >
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              fontSize: 14,
              marginBottom: 8,
            }}
          >
            <span>
              Hedef kelime: <b>{t.target_keyword}</b>
            </span>
            <span style={{ color: ratioColor((t.keyword_score ?? 0) / 100), fontWeight: 700 }}>
              {Math.round(t.keyword_score ?? 0)}/100
            </span>
          </div>
          <div style={{ height: 8, borderRadius: 4, background: "#1f2c47", overflow: "hidden" }}>
            <div
              style={{
                width: `${Math.round(t.keyword_score ?? 0)}%`,
                height: "100%",
                background: ratioColor((t.keyword_score ?? 0) / 100),
              }}
            />
          </div>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              gap: "6px 18px",
              marginTop: 12,
            }}
          >
            {t.keyword_checks.map((c) => (
              <div key={c.key} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13 }}>
                <span style={{ color: c.present ? "#22c55e" : "#ef4444", fontWeight: 800 }}>
                  {c.present ? "✓" : "✗"}
                </span>
                <span>{c.label}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {t.schema_expectations.length > 0 && (
        <div style={{ marginBottom: 14 }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: "#9fb0c7", textTransform: "uppercase", marginBottom: 8 }}>
            Bu sayfa türü için beklenen şemalar
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {t.schema_expectations.map((e) => (
              <span
                key={e.type}
                style={{
                  fontSize: 12.5,
                  fontWeight: 600,
                  padding: "4px 10px",
                  borderRadius: 999,
                  background: e.present ? "#12261a" : "#3a2e10",
                  color: e.present ? "#22c55e" : "#f59e0b",
                  border: `1px solid ${e.present ? "#1f4a30" : "#5a4410"}`,
                }}
              >
                {e.present ? "✓" : "✗"} {e.label}
              </span>
            ))}
          </div>
        </div>
      )}

      <div style={{ display: "grid", gap: 4 }}>
        {t.findings.map((f, i) => (
          <div
            key={i}
            style={{
              display: "flex",
              gap: 10,
              alignItems: "flex-start",
              padding: "8px 0",
              borderTop: i === 0 ? "none" : "1px solid #1f2c47",
            }}
          >
            <span
              style={{
                flexShrink: 0,
                width: 20,
                height: 20,
                borderRadius: "50%",
                background: findingBg(f.severity),
                color: findingColor(f.severity),
                textAlign: "center",
                lineHeight: "20px",
                fontWeight: 800,
                fontSize: 12,
              }}
            >
              {f.severity === "ok" ? "✓" : f.severity === "fail" ? "✗" : "!"}
            </span>
            <div>
              <div style={{ fontSize: 14 }}>{f.message}</div>
              {f.recommendation && (
                <div style={{ fontSize: 13, color: "#9fb0c7", marginTop: 2 }}>{f.recommendation}</div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function VisibilityResultView({
  report: r,
  pdfUrl,
  htmlUrl,
}: {
  report: VisibilityReport;
  pdfUrl: string | null;
  htmlUrl: string | null;
}) {
  const gradeColor = ratioColor((r.score ?? 0) / 100);
  const score = Math.round(r.score ?? 0);
  const label =
    score >= 70 ? "Güçlü" : score >= 45 ? "Orta" : score >= 20 ? "Düşük" : "Çok Düşük";
  const maxMention = Math.max(...r.engine_stats.map((e) => e.mention_count), 1);
  const maxComp = Math.max(...r.competitor_ranking.map((c) => c.count), 1);
  const statusPill = (er: VisEngineResult) => {
    if (er.status === "error")
      return { bg: "#2e2410", fg: "#fbbf24", txt: `! ${er.engine} · ${er.error || "hata"}` };
    if (er.status === "cited")
      return { bg: "#12261a", fg: "#22c55e", txt: `✓ ${er.engine} · ${er.citation_count}/${er.samples} kaynak` };
    if (er.status === "mentioned")
      return { bg: "#1e2149", fg: "#818cf8", txt: `● ${er.engine} · ${er.mention_count}/${er.samples} anıldı` };
    return { bg: "#3a1620", fg: "#f87171", txt: `✗ ${er.engine} · anılmadı` };
  };
  const erroredEngines = r.engine_stats.filter((e) => (e.errored ?? 0) > 0);

  return (
    <div style={{ marginTop: 24, display: "grid", gap: 16 }}>
      <div style={{ ...cardStyle, display: "flex", alignItems: "center", gap: 20 }}>
        <div
          style={{
            width: 96, height: 96, borderRadius: "50%", display: "grid",
            placeItems: "center", border: `6px solid ${gradeColor}`, flexShrink: 0,
          }}
        >
          <span style={{ fontSize: 30, fontWeight: 700 }}>{score}</span>
        </div>
        <div>
          <div style={{ fontSize: 20, fontWeight: 700 }}>
            AI Görünürlük: {score}/100 <span style={{ color: gradeColor }}>({label})</span>
          </div>
          <div style={{ color: "#9fb0c7", marginTop: 4 }}>
            {r.brand} · {r.domain}
          </div>
          <div style={{ color: "#647892", fontSize: 13, marginTop: 2 }}>
            {r.prompt_count} prompt · {r.engines_used.length} motor · {r.api_calls} API çağrısı
          </div>
        </div>
      </div>

      {/* stat strip */}
      <div style={{ display: "flex", gap: 12 }}>
        <div style={cardStyle}>
          <b style={{ fontSize: 24 }}>{r.mention_total}</b>
          <span style={{ color: "#9fb0c7", fontSize: 12, display: "block" }}>
            anılma ({r.slot_total} sonuçtan)
          </span>
        </div>
        <div style={cardStyle}>
          <b style={{ fontSize: 24 }}>{r.citation_total}</b>
          <span style={{ color: "#9fb0c7", fontSize: 12, display: "block" }}>kaynak gösterme</span>
        </div>
        <div style={cardStyle}>
          <b style={{ fontSize: 24 }}>{r.competitor_ranking.length}</b>
          <span style={{ color: "#9fb0c7", fontSize: 12, display: "block" }}>farklı rakip</span>
        </div>
      </div>

      <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
        {pdfUrl && (
          <a href={pdfUrl} target="_blank" rel="noreferrer" style={linkButton("#2563eb")}>
            Rapor (PDF)
          </a>
        )}
        {htmlUrl && (
          <a href={htmlUrl} target="_blank" rel="noreferrer" style={linkButton("#334155")}>
            Rapor (HTML)
          </a>
        )}
      </div>

      {/* engine-failure banner */}
      {erroredEngines.length > 0 && (
        <div style={{ ...cardStyle, borderColor: "#a16207", background: "#2a2410" }}>
          <h2 style={{ marginTop: 0, fontSize: 16, color: "#fbbf24" }}>
            ⚠ Bazı motorlar yanıt veremedi
          </h2>
          <p style={{ margin: "0 0 8px", fontSize: 13.5, color: "#e5d3a1" }}>
            Aşağıdaki motor(lar) çağrıları başarısız olduğu için skora dahil edilmedi.
            Skor yalnızca yanıt veren motor/örnekler üzerinden hesaplandı.
          </p>
          <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13, color: "#e5d3a1" }}>
            {erroredEngines.map((e) => (
              <li key={e.engine} style={{ margin: "3px 0" }}>
                <b>{e.engine}</b> — {e.error || "hata"} ({e.errored} prompt başarısız)
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* engine distribution */}
      <div style={cardStyle}>
        <h2 style={{ marginTop: 0, fontSize: 18 }}>Motor Dağılımı</h2>
        <div style={{ display: "grid", gap: 10 }}>
          {r.engine_stats.map((e) => (
            <div key={e.engine}>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 14, marginBottom: 4 }}>
                <span>{e.engine}</span>
                <span style={{ color: "#9fb0c7" }}>
                  {e.mention_count} anılma · {e.citation_count} kaynak
                </span>
              </div>
              <div style={{ height: 8, borderRadius: 4, background: "#1f2c47", overflow: "hidden" }}>
                <div style={{ width: `${Math.round((e.mention_count / maxMention) * 100)}%`, height: "100%", background: "#7c3aed" }} />
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* competitor + source rankings */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <div style={cardStyle}>
          <h2 style={{ marginTop: 0, fontSize: 18 }}>Rakip Markalar</h2>
          {r.competitor_ranking.length === 0 && (
            <span style={{ color: "#647892", fontSize: 13 }}>Rakip tespit edilmedi.</span>
          )}
          {r.competitor_ranking.map((c) => (
            <div key={c.name} style={{ display: "flex", alignItems: "center", gap: 10, padding: "7px 0", fontSize: 13.5 }}>
              <span style={{ flex: 1, fontWeight: 600 }}>{c.name}</span>
              <span style={{ width: 90, height: 7, background: "#1f2c47", borderRadius: 999, overflow: "hidden" }}>
                <span style={{ display: "block", width: `${Math.round((c.count / maxComp) * 100)}%`, height: "100%", background: "#a78bfa" }} />
              </span>
              <span style={{ color: "#9fb0c7", fontSize: 12 }}>{c.count} yanıt</span>
            </div>
          ))}
        </div>
        <div style={cardStyle}>
          <h2 style={{ marginTop: 0, fontSize: 18 }}>Öne Çıkan Kaynaklar</h2>
          {r.source_ranking.length === 0 && (
            <span style={{ color: "#647892", fontSize: 13 }}>Kaynak gösterilmedi.</span>
          )}
          {r.source_ranking.map((s) => (
            <div key={s.domain} style={{ display: "flex", alignItems: "center", gap: 10, padding: "7px 0", fontSize: 13.5 }}>
              <span style={{ flex: 1, fontWeight: 600 }}>
                {s.domain}
                {s.is_ours && (
                  <span style={{ marginLeft: 8, fontSize: 10, fontWeight: 800, color: "#a78bfa", background: "#2a1f4a", borderRadius: 5, padding: "1px 6px" }}>
                    SİZ
                  </span>
                )}
              </span>
              <span style={{ color: "#9fb0c7", fontSize: 12 }}>{s.count} kez</span>
            </div>
          ))}
        </div>
      </div>

      {/* detailed prompt cards */}
      <div style={cardStyle}>
        <h2 style={{ marginTop: 0, fontSize: 18 }}>Prompt Bazlı Sonuçlar</h2>
        <div style={{ display: "grid", gap: 14 }}>
          {r.prompts.map((pr, i) => {
            const rank: Record<string, number> = { cited: 0, mentioned: 1, absent: 2 };
            const best = [...pr.engines].sort((a, b) => (rank[a.status] ?? 3) - (rank[b.status] ?? 3))[0];
            const comps = Array.from(new Set(pr.engines.flatMap((e) => e.competitors)));
            const srcs = Array.from(new Set(pr.engines.flatMap((e) => e.sources))).slice(0, 6);
            return (
              <div key={i} style={{ border: "1px solid #1f2c47", borderRadius: 12, padding: 16 }}>
                <div style={{ fontWeight: 700, fontSize: 14.5, marginBottom: 3 }}>{pr.prompt}</div>
                <div style={{ fontSize: 12, color: "#647892", marginBottom: 10 }}>
                  Kaynak: {pr.source === "manual" ? "manuel girildi" : "otomatik üretildi"}
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 10 }}>
                  {pr.engines.map((er, j) => {
                    const p = statusPill(er);
                    return (
                      <span key={j} style={{ fontSize: 12.5, fontWeight: 600, color: p.fg, background: p.bg, border: "1px solid #1f2c47", borderRadius: 999, padding: "4px 11px" }}>
                        {p.txt}
                      </span>
                    );
                  })}
                </div>
                {best?.response_excerpt && (
                  <div style={{ background: "#0b1220", borderLeft: "3px solid #7c3aed", borderRadius: "0 8px 8px 0", padding: "10px 12px", fontSize: 13, color: "#c5cfdd", marginBottom: 10 }}>
                    <b style={{ color: "#e6edf6" }}>{best.engine} yanıtı:</b> {best.response_excerpt}…
                  </div>
                )}
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
                  <div>
                    <div style={{ fontSize: 11, fontWeight: 800, letterSpacing: ".06em", textTransform: "uppercase", color: "#647892", marginBottom: 6 }}>
                      Yanıtta geçen rakipler
                    </div>
                    {comps.length === 0 ? (
                      <span style={{ color: "#647892", fontSize: 12.5 }}>—</span>
                    ) : (
                      comps.map((c) => (
                        <span key={c} style={{ display: "inline-block", fontSize: 12.5, fontWeight: 600, padding: "3px 9px", borderRadius: 999, background: "#1f2c47", color: "#c5cfdd", margin: "0 6px 6px 0" }}>
                          {c}
                        </span>
                      ))
                    )}
                  </div>
                  <div>
                    <div style={{ fontSize: 11, fontWeight: 800, letterSpacing: ".06em", textTransform: "uppercase", color: "#647892", marginBottom: 6 }}>
                      Gösterilen kaynaklar
                    </div>
                    {srcs.length === 0 ? (
                      <span style={{ color: "#647892", fontSize: 12.5 }}>—</span>
                    ) : (
                      srcs.map((s) => (
                        <div key={s} style={{ fontSize: 12.5, color: "#93c5fd", padding: "2px 0", wordBreak: "break-all" }}>{s}</div>
                      ))
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function SpaWarning() {
  return (
    <div
      style={{
        ...cardStyle,
        background: "#3a2e10",
        border: "1px solid #b45309",
      }}
    >
      <div style={{ fontWeight: 700, color: "#fcd34d", marginBottom: 6 }}>
        ⚠️ Olası SPA — içerik JavaScript ile üretiliyor olabilir
      </div>
      <div style={{ fontSize: 14, color: "#e6edf6" }}>
        Sunucudan dönen HTML&apos;de başlık, meta ve içerik sinyalleri neredeyse
        yok. İçerik büyük olasılıkla tarayıcıda JS ile yükleniyor ve{" "}
        <b>AI tarayıcıları bunu çoğunlukla göremez</b>. &quot;AI vs kullanıcı
        karşılaştır&quot; ile farkı görün; kalıcı çözüm için içeriği sunucu
        tarafında üretin (SSR/prerender).
      </div>
    </div>
  );
}

function RenderComparisonView({ comparison }: { comparison: RenderComparison }) {
  const { raw, rendered, delta_total, deltas } = comparison;
  return (
    <div style={cardStyle}>
      <div style={{ fontWeight: 700, marginBottom: 4 }}>
        AI&apos;ın gördüğü vs kullanıcının gördüğü
      </div>
      <div style={{ fontSize: 13, color: "#9fb0c7", marginBottom: 14 }}>
        AI tarayıcıları çoğunlukla JavaScript çalıştırmaz — &quot;Ham HTML&quot;
        sütunu motorların pratikte gördüğü puandır.
      </div>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          gap: 18,
          marginBottom: 16,
        }}
      >
        <ScorePill label="Ham HTML — AI" score={raw.geo_score} grade={raw.grade} />
        <span style={{ fontWeight: 800, color: "#22c55e" }}>
          +{Math.round(delta_total)}
        </span>
        <ScorePill
          label="JS sonrası — kullanıcı"
          score={rendered.geo_score}
          grade={rendered.grade}
        />
      </div>
      <div style={{ display: "grid", gap: 6 }}>
        {deltas
          .filter((d) => Math.abs(d.delta) >= 0.05)
          .map((d) => (
            <div
              key={d.key}
              style={{
                display: "grid",
                gridTemplateColumns: "1fr auto auto auto",
                gap: 10,
                fontSize: 13,
                padding: "5px 0",
                borderTop: "1px solid #1f2c47",
              }}
            >
              <span>{d.name}</span>
              <span style={{ color: "#9fb0c7" }}>{d.raw.toFixed(1)}</span>
              <span style={{ color: "#9fb0c7" }}>→ {d.rendered.toFixed(1)}</span>
              <span
                style={{
                  fontWeight: 700,
                  color: d.delta > 0 ? "#22c55e" : "#ef4444",
                }}
              >
                {d.delta > 0 ? "▲" : "▼"} {Math.abs(d.delta).toFixed(1)}
              </span>
            </div>
          ))}
      </div>
    </div>
  );
}

function ScorePill({
  label,
  score,
  grade,
}: {
  label: string;
  score: number;
  grade: string;
}) {
  return (
    <div
      style={{
        background: "#0b1220",
        border: "1px solid #1f2c47",
        borderRadius: 12,
        padding: "10px 18px",
        textAlign: "center",
        minWidth: 150,
      }}
    >
      <div style={{ fontSize: 11, color: "#9fb0c7", marginBottom: 3 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 800 }}>
        {Math.round(score)} <span style={{ fontSize: 14, color: "#9fb0c7" }}>{grade}</span>
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

function tabStyle(active: boolean): React.CSSProperties {
  return {
    padding: "9px 18px",
    borderTopLeftRadius: 10,
    borderTopRightRadius: 10,
    border: "1px solid #1f2c47",
    borderBottom: active ? "1px solid #111a2e" : "1px solid #1f2c47",
    marginBottom: -1,
    background: active ? "#111a2e" : "#0b1220",
    color: active ? "#e6edf6" : "#9fb0c7",
    fontSize: 14,
    fontWeight: 600,
    cursor: "pointer",
  };
}
