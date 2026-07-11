# P0 — Branding (favicon assets + Arteamis color palette) — Design Spec
Date: 2026-07-11 · Branch: feat/auth-multitenancy · Status: Draft

## Goal
Rebrand the Arteamis-fe frontend from Open Notebook defaults to the Arteamis identity, without touching any
application logic. Two changes only: (1) install the Arteamis favicon / PWA-icon set into `frontend/public/`
and wire it into Next.js metadata + web manifest, and (2) replace the **values** of the existing oklch shadcn
design tokens in `frontend/src/app/globals.css` with the Arteamis brand palette (Claude coral `#d97757` primary,
warm-paper `#fafaf9` background, ink `#262626` foreground, plus dark-theme equivalents). Token **names** and the
file structure are preserved so Tailwind v4 + every existing component keeps working unchanged.

## Depends on / Provides
- **Depends on:** nothing. P0 is fully independent (per Architecture Brief phase map). No API, no schema, no auth.
- **Provides:** the Arteamis visual foundation (brand colors + favicon/PWA metadata) that all later phases
  (P1 login/signup UI, P2 onboarding wizard, etc.) render against. No code contract is exported; consumers just
  inherit the new CSS-variable values and the new `metadata`/`viewport` in `layout.tsx`.

## Scope (in)
- Copy the 7 brand assets from `arteamis-system/landing/favicon/` into `frontend/public/`.
- Wire `favicon.ico`, PNG icons, apple-touch-icon, and `site.webmanifest` into `frontend/src/app/layout.tsx`
  via Next.js `metadata.icons`, `metadata.manifest`, and a `viewport.themeColor` export.
- Update `metadata.title` / `metadata.description` from "Open Notebook" to Arteamis branding.
- Overwrite the **values** of all `--*` color tokens under `:root` and `.dark` in
  `frontend/src/app/globals.css` with the Arteamis palette (mapping table below).

## Scope (out)
- Renaming, adding, or removing any token (Tailwind v4 keys in the `@theme inline` block stay verbatim).
- Restructuring `globals.css` — the `@import`, `@variant`, `@theme inline`, and `@layer base` blocks are untouched;
  only the literal `oklch(...)` values inside `:root {}` and `.dark {}` change. `--radius` (0.65rem) is unchanged.
- Fonts. `layout.tsx` uses `next/font/google` `Inter`; the Arteamis system uses Hanken Grotesk + Newsreader.
  A font swap is deliberately deferred (it is not a color/favicon change and would touch `--font-sans`/typography).
  Noted as a follow-up in Open questions.
- Any backend, migration, i18n, or component file. This phase edits exactly two files and copies asset files.

## Data model changes
None. P0 has no SurrealDB migration.

## Backend: endpoints, services, domain models
None. P0 touches no `api/`, `open_notebook/`, or migration files.

## Frontend: files to change

### 1. Asset copy (source → destination)
Source dir (verified, read-only — do NOT edit): `arteamis-system/landing/favicon/` contains exactly:
`favicon.ico` (15406 B), `favicon-16x16.png`, `favicon-32x32.png`, `apple-touch-icon.png`,
`android-chrome-192x192.png`, `android-chrome-512x512.png`, `site.webmanifest`.
**There is NO `icon.svg` / `favicon.svg` in the source folder** (the task brief mentioned one; it does not exist —
do not fabricate it). All icons are raster PNG/ICO.

Destination: copy the whole set into a `frontend/public/favicon/` subfolder, because the source
`site.webmanifest` already references icons at the `/favicon/...` path prefix (see below). Keeping the subfolder
means the manifest works verbatim. Copy command (implementation step):
`cp -R arteamis-system/landing/favicon/. Arteamis-fe/frontend/public/favicon/`

Resulting `frontend/public/favicon/` files:
- `favicon.ico`, `favicon-16x16.png`, `favicon-32x32.png`, `apple-touch-icon.png`,
  `android-chrome-192x192.png`, `android-chrome-512x512.png`, `site.webmanifest`.

The current `frontend/public/` holds only unrelated Next/Vercel starter SVGs
(`file.svg`, `globe.svg`, `logo.svg`, `next.svg`, `vercel.svg`, `window.svg`) — there is **no existing favicon
today**. Those SVGs are out of scope (leave them; optional cleanup can drop `next.svg`/`vercel.svg` later).

Note: Next.js App Router auto-detects a `favicon.ico` placed in `frontend/src/app/`. We are NOT using that
mechanism — we declare icons explicitly in `metadata` (below) and serve from `public/favicon/`, which is
unambiguous and keeps all brand assets in one folder.

### 2. `frontend/public/favicon/site.webmanifest`
Copied verbatim, its current content is:
```json
{
  "name": "Arteamis",
  "short_name": "Arteamis",
  "icons": [
    { "src": "/favicon/android-chrome-192x192.png", "sizes": "192x192", "type": "image/png" },
    { "src": "/favicon/android-chrome-512x512.png", "sizes": "512x512", "type": "image/png" }
  ],
  "theme_color": "#ffffff",
  "background_color": "#ffffff",
  "display": "standalone"
}
```
Optional refinement (in scope, one-line edits, keeps names): set `"background_color": "#fafaf9"` (Arteamis warm
paper) and `"theme_color": "#d97757"` (coral) so the PWA splash/address-bar matches the brand. If you prefer to
keep the copied file byte-identical, leave `#ffffff` — either is acceptable; the icons array is already correct.

### 3. `frontend/src/app/layout.tsx`
Current `metadata` (lines 15-18) is:
```ts
export const metadata: Metadata = {
  title: "Open Notebook",
  description: "Privacy-focused research and knowledge management",
};
```
Replace with Arteamis branding + icon/manifest wiring, and add a `viewport` export (Next 16 requires
`themeColor` in `viewport`, not `metadata`). Target shape:
```ts
import type { Metadata, Viewport } from "next";

export const metadata: Metadata = {
  title: "Arteamis",
  description: "AI-Native Company Operating System",
  manifest: "/favicon/site.webmanifest",
  icons: {
    icon: [
      { url: "/favicon/favicon.ico" },
      { url: "/favicon/favicon-16x16.png", sizes: "16x16", type: "image/png" },
      { url: "/favicon/favicon-32x32.png", sizes: "32x32", type: "image/png" },
    ],
    apple: [{ url: "/favicon/apple-touch-icon.png", sizes: "180x180", type: "image/png" }],
  },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#fafaf9" },
    { media: "(prefers-color-scheme: dark)", color: "#1a1a19" },
  ],
};
```
Everything else in `layout.tsx` (the `Inter` font import + `inter.className` on `<body>`, the provider nesting
ErrorBoundary → ThemeProvider → QueryProvider → I18nProvider → ConnectionGuard → Toaster, the `themeScript`,
`suppressHydrationWarning`) stays exactly as-is. `title`/`description` are hardcoded here today (not i18n), so
changing the two literals introduces no new i18n keys — no locale files are touched.

### 4. `frontend/src/app/globals.css` — palette value swap (the core of P0)
Only the `oklch(...)` literals inside `:root { … }` (lines 47-80) and `.dark { … }` (lines 82-114) change.
The `@theme inline` mapping block (lines 7-45) and `@layer base` (lines 116-201) are untouched. `--radius`
stays `0.65rem`.

**Source of truth (hex):** `arteamis-system/ref/Arteamis Design System/tokens.css` (raw hex base palette) and
`arteamis-system/app/globals.css` (same values as RGB triples). oklch values below were computed from those
hex values (sRGB → OKLab → OKLCH); each row shows the source hex so implementation can re-verify.

#### `:root` (light theme)
| Token | Arteamis role → hex | New value |
|---|---|---|
| `--radius` | (unchanged) | `0.65rem` |
| `--background` | paper `#fafaf9` | `oklch(0.985 0.001 106.4)` |
| `--foreground` | ink / heading `#262626` | `oklch(0.269 0 90)` |
| `--card` | surface `#ffffff` | `oklch(1 0 0)` |
| `--card-foreground` | ink `#262626` | `oklch(0.269 0 90)` |
| `--popover` | surface `#ffffff` | `oklch(1 0 0)` |
| `--popover-foreground` | ink `#262626` | `oklch(0.269 0 90)` |
| `--primary` | coral `#d97757` | `oklch(0.672 0.131 38.8)` |
| `--primary-foreground` | **ink** `#262626` (label on coral is ink, NOT white — 3.12:1 rule) | `oklch(0.269 0 90)` |
| `--secondary` | bg-alt `#f4f3ef` | `oklch(0.964 0.005 95.1)` |
| `--secondary-foreground` | ink `#262626` | `oklch(0.269 0 90)` |
| `--muted` | surface-sunk `#f7f6f2` | `oklch(0.973 0.005 95.1)` |
| `--muted-foreground` | text-muted `#58534d` | `oklch(0.445 0.012 72.5)` |
| `--accent` | bg-alt `#f4f3ef` | `oklch(0.964 0.005 95.1)` |
| `--accent-foreground` | ink `#262626` | `oklch(0.269 0 90)` |
| `--destructive` | danger `#b3392b` | `oklch(0.521 0.16 29.9)` |
| `--border` | border `#e7e5df` | `oklch(0.922 0.008 91.5)` |
| `--input` | border `#e7e5df` | `oklch(0.922 0.008 91.5)` |
| `--ring` | coral (border-focus) `#d97757` | `oklch(0.672 0.131 38.8)` |
| `--chart-1` | coral `#d97757` | `oklch(0.672 0.131 38.8)` |
| `--chart-2` | blue `#0a50d0` | `oklch(0.481 0.208 261.8)` |
| `--chart-3` | green `#58783b` | `oklch(0.533 0.095 131.7)` |
| `--chart-4` | warning `#8f6913` | `oklch(0.546 0.106 81.8)` |
| `--chart-5` | orange `#f1590f` | `oklch(0.658 0.2 40.4)` |
| `--sidebar` | bg-alt `#f4f3ef` | `oklch(0.964 0.005 95.1)` |
| `--sidebar-foreground` | ink `#262626` | `oklch(0.269 0 90)` |
| `--sidebar-primary` | coral `#d97757` | `oklch(0.672 0.131 38.8)` |
| `--sidebar-primary-foreground` | ink `#262626` | `oklch(0.269 0 90)` |
| `--sidebar-accent` | n-100 hover `#ecebe5` | `oklch(0.939 0.008 98.9)` |
| `--sidebar-accent-foreground` | ink `#262626` | `oklch(0.269 0 90)` |
| `--sidebar-border` | border `#e7e5df` | `oklch(0.922 0.008 91.5)` |
| `--sidebar-ring` | coral `#d97757` | `oklch(0.672 0.131 38.8)` |

#### `.dark` (dark theme)
| Token | Arteamis role → hex | New value |
|---|---|---|
| `--background` | dark bg `#1a1a19` | `oklch(0.217 0.002 106.6)` |
| `--foreground` | dark heading `#ffffff` | `oklch(1 0 0)` |
| `--card` | dark surface `#242423` | `oklch(0.26 0.002 106.5)` |
| `--card-foreground` | white `#ffffff` | `oklch(1 0 0)` |
| `--popover` | dark surface `#242423` | `oklch(0.26 0.002 106.5)` |
| `--popover-foreground` | white `#ffffff` | `oklch(1 0 0)` |
| `--primary` | coral `#d97757` (same fill both themes) | `oklch(0.672 0.131 38.8)` |
| `--primary-foreground` | **ink** `#262626` (btn label is ink in BOTH themes) | `oklch(0.269 0 90)` |
| `--secondary` | dark surface-sunk `#171716` | `oklch(0.204 0.002 106.6)` |
| `--secondary-foreground` | white `#ffffff` | `oklch(1 0 0)` |
| `--muted` | dark surface-sunk `#171716` | `oklch(0.204 0.002 106.6)` |
| `--muted-foreground` | dark text-muted `#b3b3b3` | `oklch(0.767 0 90)` |
| `--accent` | dark surface-sunk `#171716` | `oklch(0.204 0.002 106.6)` |
| `--accent-foreground` | white `#ffffff` | `oklch(1 0 0)` |
| `--destructive` | dark danger `#e2645a` | `oklch(0.657 0.159 26.9)` |
| `--border` | dark border `#33322e` | `oklch(0.317 0.007 95.3)` |
| `--input` | dark border-strong `#454339` | `oklch(0.382 0.017 97.8)` |
| `--ring` | coral `#d97757` | `oklch(0.672 0.131 38.8)` |
| `--chart-1` | coral `#d97757` | `oklch(0.672 0.131 38.8)` |
| `--chart-2` | dark blue `#6d9bff` | `oklch(0.702 0.155 264.2)` |
| `--chart-3` | dark green `#71964b` | `oklch(0.628 0.111 130.6)` |
| `--chart-4` | dark warning `#e3b53c` | `oklch(0.794 0.143 87.1)` |
| `--chart-5` | orange `#f1590f` | `oklch(0.658 0.2 40.4)` |
| `--sidebar` | dark surface `#242423` | `oklch(0.26 0.002 106.5)` |
| `--sidebar-foreground` | white `#ffffff` | `oklch(1 0 0)` |
| `--sidebar-primary` | coral `#d97757` | `oklch(0.672 0.131 38.8)` |
| `--sidebar-primary-foreground` | ink `#262626` | `oklch(0.269 0 90)` |
| `--sidebar-accent` | dark border-strong hover `#454339` | `oklch(0.382 0.017 97.8)` |
| `--sidebar-accent-foreground` | white `#ffffff` | `oklch(1 0 0)` |
| `--sidebar-border` | dark border `#33322e` | `oklch(0.317 0.007 95.3)` |
| `--sidebar-ring` | coral `#d97757` | `oklch(0.672 0.131 38.8)` |

**Conversion note:** oklch triples above were derived from the source hex via the standard sRGB→OKLab→OKLCH
transform (D65). If the implementer's tool produces values differing in the 3rd decimal, prefer re-converting the
listed **hex** (the source of truth) rather than the displayed oklch; the hex is authoritative. Near-neutral rows
(`#262626`, `#ffffff`) legitimately have chroma ~0 — I collapsed tiny residual chroma/hue to `0 90` for `#262626`
and `0 0` for pure white/black.

**Two design-system rules that MUST survive the swap** (from `tokens.css` header + arteamis-system CLAUDE.md):
1. `--primary-foreground` is **ink `#262626`**, not white, in BOTH `:root` and `.dark` — the coral fill is only
   3.12:1 against white but AA against ink, and the primary button is designed to *lighten* on hover.
2. Coral (`#d97757`, `oklch(0.672 0.131 38.8)`) is used only as a **fill** (`--primary`, `--ring`, chart-1). It is
   2.99:1 as text on paper — never set a foreground/text token to raw coral. The palette above never does.

## Permissions / RBAC rules
Not applicable. P0 is presentation-only; no roles, no gated actions, no auth surface.

## Error handling
Not applicable (no runtime code paths, endpoints, or user input). Failure modes are build/asset-level only:
- A wrong icon path in `metadata` yields a 404 for the icon but does not break the app — verify via browser
  devtools Network tab that `/favicon/favicon.ico` and `/favicon/site.webmanifest` return 200.
- An invalid `oklch(...)` literal would fail the Tailwind/PostCSS build — caught by `npm run build`.

## Testing (concrete)
- `cd frontend && npm run build` — must pass (validates the oklch literals and the `metadata`/`viewport` exports
  compile under Next 16). This is the primary gate.
- `cd frontend && npm run lint` — must pass (no unused `Viewport` import, etc.).
- Asset presence: confirm all 7 files exist under `frontend/public/favicon/` (`ls frontend/public/favicon/`).
- Manual visual check (`npm run dev`, http://localhost:3000):
  - Browser tab shows the Arteamis favicon (not the Next default).
  - Page background is warm paper `#fafaf9`; primary buttons render coral `#d97757` with dark ink labels.
  - Toggle dark mode (next-themes `.dark` class) → background `#1a1a19`, coral primary retained, ink button label.
  - `/favicon/site.webmanifest` returns 200 and `name` = "Arteamis".
- No new automated test file is required; `__tests__` contrast/token guards from arteamis-system are NOT ported
  (that guard lives in the source repo and is out of scope here).

## Open questions / risks
- **Fonts deferred:** `layout.tsx` still loads `Inter`; the Arteamis identity is Hanken Grotesk (sans) +
  Newsreader (serif display). Swapping fonts touches `--font-sans` in `globals.css` and `layout.tsx` font wiring
  and is intentionally excluded from P0 (color+favicon only). Flag as a candidate follow-up phase/ticket.
- **`--border`/`--input` in dark went opaque:** Open Notebook's original dark theme used translucent borders
  (`oklch(1 0 0 / 10%)`). The Arteamis palette specifies opaque warm-gray borders (`#33322e`/`#454339`), which I
  adopted for brand fidelity. If a designer prefers the translucent look, that is the one intentional deviation to
  revisit — it does not affect token names.
- **Manifest `theme_color`:** left as the copied `#ffffff` vs. updated to coral/paper (section 2) is a taste call;
  either passes build. Recommend paper/coral to match the `viewport.themeColor`.
- **No `icon.svg`:** the source folder has no SVG icon despite the brief mentioning one; all icons are raster.
  If a crisp scalable tab icon is later wanted, an SVG must be produced separately (out of P0 scope).
