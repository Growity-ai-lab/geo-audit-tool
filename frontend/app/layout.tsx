import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "GEO Audit — Growity",
  description: "AI arama motorları için GEO/AIO hazırlık denetimi.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="tr">
      <body
        style={{
          margin: 0,
          fontFamily:
            "system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif",
          background: "#0b1220",
          color: "#e6edf6",
        }}
      >
        {children}
      </body>
    </html>
  );
}
