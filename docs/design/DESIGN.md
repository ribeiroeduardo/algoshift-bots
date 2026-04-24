# Design System: Vercel (Marketing) + Dashboard Density

Single reference: **Part I** = Vercel marketing site (light, whitespace). **Part II** = product/dashboard (dark, max info/pixel). Same Geist family; density and surfaces differ. Complements monolith `DESIGN.md` where applicable.

---

## Part I — Vercel (Marketing)

### 1. Theme

- Canvas `#ffffff`, primary text `#171717` (not pure black). Gallery whitespace; structure over decoration.
- **Geist Sans**: aggressive negative tracking at display (-2.4px … -2.88px @ 48px); relaxes as size drops. **Geist Mono**: code, technical labels. OpenType `"liga"` global; `"tnum"` where tabular numbers needed.
- **Shadow-as-border**: `box-shadow: 0 0 0 1px rgba(0,0,0,0.08)` instead of `border` on cards. Stacks: border ring + soft lift + ambient + inner `#fafafa` highlight on featured cards.

**Characteristics:** compressed display type; mono for dev voice; multi-layer shadows; workflow accents only in pipeline context; focus `hsla(212, 100%, 48%, 1)`; pill badges `9999px`.

### 2. Colors

| Role | Hex / value |
|------|----------------|
| Vercel Black | `#171717` — text, dark fills |
| White | `#ffffff` — page, cards, text on dark |
| True black | `#000000` — console-specific |
| Ship / Preview / Develop | `#ff5b4f` / `#de1d8d` / `#0a72ef` |
| Console blue/purple/pink | `#0070f3` / `#7928ca` / `#eb367f` |
| Link | `#0072f5` |
| Focus | `hsla(212, 100%, 48%, 1)` |
| Ring (Tailwind) | `rgba(147, 197, 253, 0.5)` |
| Gray 900→50 | `#171717`, `#4d4d4d`, `#666`, `#808080`, `#ebebeb`, `#fafafa` |
| Border shadow | `rgba(0,0,0,0.08) 0 0 0 1px` |
| Card stack (full) | `rgba(0,0,0,0.08) 0 0 0 1px, rgba(0,0,0,0.04) 0 2px 2px, rgba(0,0,0,0.04) 0 8px 8px -8px, #fafafa 0 0 0 1px` |

### 3. Typography (Marketing)

| Role | Font | Size | Wt | LH | Tracking |
|------|------|------|-----|-----|----------|
| Display hero | Geist | 48px | 600 | 1.00–1.17 | -2.4 … -2.88px |
| Section heading | Geist | 40px | 600 | 1.20 | -2.4px |
| Sub-heading | Geist | 32px | 600/400 | 1.25/1.50 | -1.28px |
| Card title | Geist | 24px | 600/500 | 1.33 | -0.96px |
| Body large / body / small | Geist | 20 / 18 / 16px | 400 | 1.80 / 1.56 / 1.50 | normal |
| Body medium / semibold | Geist | 16px | 500/600 | 1.50 | -0.32px semi |
| Button / link | Geist | 14px | 500/400 | 1.43 / 1.00 | normal |
| Caption | Geist | 12px | 400–500 | 1.33 | normal |
| Mono body / caption / small | Mono | 16 / 13 / 12px | 400/500 | per row | small: uppercase |
| Micro badge | Geist | 7px | 700 | 1.00 | uppercase |

**Principles:** tracking scales with size; weights 400/500/600 only (700 only micro-badge); mono uppercase = technical voice.

### 4. Components (Marketing)

- **Buttons:** white + ring `rgb(235,235,235) 0 0 0 1px`, hover to dark; primary dark `#171717` / white text, `8px 16px`, `6px` radius. Pill badge `#ebf5ff` / `#0068d6`, `12px` / 500, `9999px` radius. Large nav pills `64–100px` radius.
- **Cards:** `#fff`, shadow border + stack above; `8px` / `12px` radius for featured; image cards `1px #ebebeb`, top radius `12px`.
- **Forms:** focus outline `2px` focus blue; inputs use shadow-border pattern.
- **Nav:** sticky white, links `14px` / 500 `#171717`; logo ~262×52 workflow pipeline (Develop → Preview → Ship) with accent colors; trust bar grayscale + `#ebebeb` dividers; metric cards 48px/600 numbers.

### 5. Layout (Marketing)

- Base **8px**; scale includes 1–16, 32, 36, 40 (gap jumps 16→32).
- ~**1200px** max content; hero centered; sections `80–120px+` vertical rhythm; separation via shadow-borders + space, not alternating bg colors.
- **Radius:** 2 / 4 / 6 / 8 / 12 / 64 / 100 / 9999 / 50% per use case (see original scale).

### 6. Depth (Marketing)

| Level | Treatment |
|-------|-----------|
| 0 | No shadow |
| 1 | `rgba(0,0,0,0.08) 0 0 0 1px` |
| 1b | `rgb(235,235,235) 0 0 0 1px` |
| 2 | ring + `rgba(0,0,0,0.04) 0 2px 2px` |
| 3 | full card stack (border + lift + ambient + `#fafafa` inner) |
| Focus | `2px solid hsla(212,100%,48%,1)` |

Heavy shadows avoided; inner `#fafafa` ring keeps “glow”.

### 7. Do / Don’t (Marketing)

**Do:** Geist + negative tracking at display; shadow-as-border; `liga`; three weights; workflow colors only in pipeline; `#171717` not `#000` for body black.

**Don’t:** positive tracking on Sans; 700 on body; real `border` on marketing cards; warm decorative chrome; workflow colors decorative; skip inner highlight in full card stack; `9999px` on primary CTAs (badges only).

### 8. Responsive (Marketing)

Breakpoints: `<400`, `400–600`, `600–768`, `768–1024`, `1024–1200`, `1200–1400`, `>1400`. Grids collapse 3→2→1; nav → hamburger; section spacing `80px+` → `~48px` mobile; hero type scales, tracking proportional.

### 9. Agent quick ref (Marketing)

Colors: bg `#fff`, heading `#171717`, body `#4d4d4d`, link `#0072f5`, shadow border `rgba(0,0,0,0.08) 0 0 0 1px`, focus blue as above. Prompt patterns: hero 48px/600/-2.4px; card white + stack + 24px title; pill badge spec; nav sticky + dark CTA; workflow tri-color steps.

---

## Part II — Dashboard (Dark, Dense)

> **Uso:** tokens de densidade para **produto** (não marketing). Objetivo: máxima informação por pixel, legível. Regra grossa: espaçamentos do marketing ÷ ~**2.5**.

### 1. Marketing vs dashboard

| Propriedade | Site | Dashboard |
|-------------|------|-------------|
| Font base | 16–20px | 13–14px |
| Padding card | 24px | 12–14px |
| Gap cards | 20px | 8–10px |
| Section padding | 64–96px | 16–24px |
| Line-height | 1.5–1.8 | 1.2–1.35 |
| Topbar | — | 48px |
| Sidebar | — | 220px |

### 2. Tipografia (dashboard)

| Role | Font | Size | Wt | LH | Tracking | Uso |
|------|------|------|-----|-----|----------|-----|
| Page title | Geist | 14px | 600 | 1.20 | -0.28px | Breadcrumb |
| Section label | Geist Mono | 11px | 500 | 1.20 | 0.4px | ALL CAPS |
| Card title | Geist | 13px | 600 | 1.25 | -0.13px | Projeto/item |
| Card meta | Geist Mono | 11px | 400 | 1.30 | normal | URL, branch, data |
| Body / list | Geist | 13px | 400 | 1.35 | normal | Listas |
| Nav / active | Geist | 13px | 500/600 | 1.20 | -0.13px active | Sidebar |
| Stat value/label | Geist | 13/12px | 400 | 1.20 | normal | Usage |
| Badge / tag | Geist | 11px | 500 | 1.00 | normal | Pills |
| Timestamp | Geist Mono | 11px | 400 | 1.20 | normal | Deploy line |
| Button | Geist | 13px | 500 | 1.00 | normal | Ações |
| Topbar breadcrumb | Geist | 14px | 500 | 1.20 | normal | |

### 3. Spacing scale (dashboard)

Base **4px** (not 8px like marketing).

```
2,4,6,8,10,12,14,16,20,24,32,48px — micro → page padding; 48 = topbar height
```

### 4. Layout dimensions

**Topbar:** `48px`, `0 16px` pad, `var(--surface)` + blur if sticky, `1px` bottom `rgba(255,255,255,0.06)`.

**Sidebar:** `220px` (collapsed `48px`), pad `8px`, bg `#0e0e0e` vs canvas `#111`, nav row `32px`, radius `6px`, item pad `6px 10px`, icon `16px`.

**Main:** pad `16px 24px`, full width, card gap `8px` list / `12px` grid.

**Project card grid:** `minmax(280px,1fr)`, radius `8px`, pad `12px 14px`, thumb `120px` tall, top radius only on thumb.

### 5. Component CSS (dashboard)

```css
.project-card {
  background: #1a1a1a;
  border-radius: 8px;
  box-shadow: rgba(255,255,255,0.06) 0 0 0 1px;
  padding: 0;
  overflow: hidden;
  transition: box-shadow 0.15s;
}
.project-card:hover {
  box-shadow: rgba(255,255,255,0.12) 0 0 0 1px, rgba(0,0,0,0.3) 0 4px 8px;
}
.project-card__thumbnail { height: 120px; background: #111; border-bottom: 1px solid rgba(255,255,255,0.06); }
.project-card__body { padding: 12px 14px; }
.project-card__title { font-size: 13px; font-weight: 600; letter-spacing: -0.13px; margin-bottom: 4px; }
.project-card__meta { font-family: 'Geist Mono', monospace; font-size: 11px; color: #666; margin-bottom: 2px; }

.nav-item {
  display: flex; align-items: center; gap: 8px;
  height: 32px; padding: 0 10px; border-radius: 6px;
  font-size: 13px; font-weight: 500; color: #919191;
  cursor: pointer; transition: background 0.1s, color 0.1s;
}
.nav-item:hover { background: rgba(255,255,255,0.05); color: #ededed; }
.nav-item.active { background: rgba(255,255,255,0.08); color: #fff; font-weight: 600; }
.nav-item svg { width: 16px; height: 16px; flex-shrink: 0; }

.topbar {
  height: 48px; display: flex; align-items: center; justify-content: space-between;
  padding: 0 16px; border-bottom: 1px solid rgba(255,255,255,0.06);
  font-size: 14px; font-weight: 500;
}
.topbar__breadcrumb { display: flex; align-items: center; gap: 6px; color: #919191; }
.topbar__breadcrumb-current { color: #ededed; }
.topbar__breadcrumb-sep { color: #444; font-size: 12px; }
.topbar__actions { display: flex; align-items: center; gap: 4px; }

.stat-row {
  display: flex; align-items: center; justify-content: space-between;
  padding: 8px 0; border-bottom: 1px solid rgba(255,255,255,0.04); font-size: 13px;
}
.stat-row__label { color: #919191; }
.stat-row__value { color: #ededed; font-variant-numeric: tabular-nums; }

.badge {
  display: inline-flex; align-items: center; padding: 2px 6px; border-radius: 9999px;
  font-size: 11px; font-weight: 500; background: rgba(255,255,255,0.08); color: #919191;
}
.badge--success { background: rgba(0,200,100,0.12); color: #3ecf8e; }
.badge--error   { background: rgba(255,91,79,0.12);  color: #ff5b4f; }
.badge--pending { background: rgba(255,200,0,0.10);  color: #f0c040; }

.btn { height: 32px; padding: 0 12px; border-radius: 6px; font-size: 13px; font-weight: 500; border: none; cursor: pointer; }
.btn--primary { background: #ededed; color: #0a0a0a; }
.btn--primary:hover { background: #fff; }
.btn--secondary { background: transparent; color: #ededed; box-shadow: rgba(255,255,255,0.12) 0 0 0 1px; }
.btn--secondary:hover { box-shadow: rgba(255,255,255,0.2) 0 0 0 1px; }
.btn--ghost { background: transparent; color: #919191; }
.btn--ghost:hover { color: #ededed; background: rgba(255,255,255,0.05); }
.btn--icon { width: 32px; padding: 0; display: inline-flex; align-items: center; justify-content: center; }
```

### 6. Grids

```css
.projects-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 12px;
  padding: 16px 24px;
}
.projects-list { display: flex; flex-direction: column; gap: 1px; padding: 0 24px; }
.projects-list-item {
  display: flex; align-items: center; padding: 10px 0; gap: 12px;
  border-bottom: 1px solid rgba(255,255,255,0.04);
}
```

### 7. Regras de ouro (dashboard)

1. Body **13px**; **14px** só topbar/breadcrumb; **11px** meta/timestamp.  
2. Card pad **12×14** — nunca 24px.  
3. Gap grid **12px**, lista **8px** — nunca 20px tipo marketing.  
4. Linhas interativas **32px**; topbar **48px**.  
5. LH **1.2–1.35** em labels/títulos de card.  
6. Preferir tonal shift; border `rgba(255,255,255,0.05–0.08)`.  
7. Ícones **16px** (14px secundário topbar).  
8. Meta: **Geist Mono 11px `#666`**.  
9. Thumb projeto **120px**, sem pad no topo.  
10. Menu **⋯** canto superior direito, hover.

### 8. Tailwind cheatsheet (dashboard)

```
text-[13px] text-[11px] text-[14px] font-medium font-semibold
leading-tight leading-snug tracking-tight
p-3 px-3.5 gap-2 gap-3 h-8 h-12 rounded-md rounded-lg w-[220px]
grid-cols-[repeat(auto-fill,minmax(280px,1fr))]
```

### 9. Não fazer (dashboard)

- `p-6` em cards → `p-3` / `px-3.5 py-3`  
- `gap-5/6` entre cards → `gap-3`  
- `text-base` em lista → `text-[13px]`  
- `leading-relaxed` em labels → `leading-tight`  
- `py-16/20` em section → `py-4/6`  
- Border sólida sidebar/content → shift tonal  
- Sombra pesada (>~0.15)  
- Topbar >48px  

---


