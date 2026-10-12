# CodeBrain — Design System Specification (DESIGN_SYSTEM.md)

**System Version:** 1.0.0  
**Implementation:** TailwindCSS v4 + CSS Custom Properties (`frontend/src/index.css`)  
**Design Philosophy:** Precision Dark IDE, Restrained Purple Accents, High Information Density, Zero Visual Noise.  
**Last Updated:** October 2026  

---

## 1. Brand Direction

CodeBrain is built specifically for software engineers, systems architects, and technical maintainers. The visual language conveys high reliability, terminal-like precision, and focus.

### Core Visual Tenets
- **Neutral Dark Surfaces:** Deep dark tones with zero blue or warm tint, eliminating eye fatigue during extended coding sessions.
- **Strict Background Separation:**
  - **General Page / Marketing Surfaces:** `#161718` provides subtle ambient separation for landing sections, marketing showcases, and login cards.
  - **Workspace Surfaces:** Uniform `#0c0d0e` across all IDE panels (Editor, File Tree, Chat, Terminal, BottomPanel) to provide a unified, seamless workspace experience.
- **Restrained Purple Accents:** Vibrant purple (`#8b5cf6`, `#9f75ff`) is applied sparingly as a signature accent for active tabs, selected states, key interactive controls, and AI brand identity. It must never dominate entire panels.
- **Deliberate Typography:** Crisp system sans-serif for UI labels and proportional navigation, paired with monospace fonts for code, symbols, paths, and diffs.

---

## 2. Color Tokens

### 2.1 CSS Custom Properties (`:root` in `frontend/src/index.css`)

```css
:root {
  /* CodeBrain Core Palette Tokens */
  --cb-page: #0c0d0e;
  --cb-surface: #0c0d0e;
  --cb-surface-raised: #0c0d0e;
  --cb-surface-hover: #141518;
  --cb-border: #1e1f23;
  --cb-border-subtle: rgba(255, 255, 255, 0.06);
  --cb-text: #f3f3f4;
  --cb-text-secondary: #a1a1aa;
  --cb-text-muted: #71717a;
  --cb-accent: #8b5cf6;
  --cb-success: #34d399;
  --cb-danger: #f87171;

  /* IDE Workspace Theme Mapping (Unified to #0c0d0e) */
  --bg-ide: #0c0d0e;
  --bg-sidebar: #0c0d0e;
  --bg-activity-bar: #0c0d0e;
  --bg-editor: #0c0d0e;
  --bg-tab-active: #0c0d0e;
  --bg-tab-inactive: #0c0d0e;
  --bg-tab-hover: #141518;
  --bg-panel: #0c0d0e;
  --bg-status-bar: #0c0d0e;

  /* Functional Color Tokens */
  --border-color: var(--cb-border);
  --border-subtle: var(--cb-border-subtle);
  --accent-color: var(--cb-accent);
  --accent-hover: #9f75ff;
  --text-primary: var(--cb-text);
  --text-muted: var(--cb-text-muted);
  --text-bright: #ffffff;
  --status-error: var(--cb-danger);
  --status-warning: #fbbf24;
  --status-info: #60a5fa;
  --status-success: var(--cb-success);
}
```

### 2.2 Background Color Policy (Non-Interchangeable)

| Background Token | Hex Value | Permitted Contexts | Prohibited Contexts |
| :--- | :--- | :--- | :--- |
| **Workspace Uniform Background** | `#0c0d0e` | EditorArea, FileTree, ChatPanel, BottomPanel, Terminal, ActivityBar, StatusBar, Navigation bar. | Landing page hero, marketing feature columns. |
| **General Page Background** | `#161718` | HomePage container (`/`), Hero section, LoginScreen card backdrop, Documentation standalone pages. | IDE workspace panels, Monaco editor background, active tabs. |
| **Elevated Surface / Hover** | `#141518` | Hovered menu items, hovered table rows, inactive hovered tabs, secondary button states. | Base panel canvas. |
| **Interactive Popover / Modal** | `#18191c` | Context menus, SettingsModal dialog body, ConnectRepoModal card, ModelSelector dropdown menu. | Full-screen workspace canvas. |

---

## 3. Typography

### 3.1 Font Families
- **Interface / Proportional:**
  ```css
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  ```
- **Monospace (Code, Line Numbers, Paths, Terminals):**
  ```css
  font-family: "Cascadia Code", "Fira Code", Consolas, "Courier New", monospace;
  ```

### 3.2 Type Scale & Hierarchy

| Role | Font Size | Line Height | Weight | Tailwind Utility | Example Usage |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Hero Display** | 48px – 72px | 1.08 | 700 (Bold) | `text-4xl sm:text-6xl lg:text-7xl font-bold` | HomePage hero title |
| **Page Heading (H1)** | 24px – 28px | 1.25 | 700 (Bold) | `text-2xl font-bold text-white` | Page titles (`/docs`, `/cicd`) |
| **Section Heading (H2)**| 18px – 20px | 1.3 | 600 (Semibold) | `text-lg font-semibold text-gray-200` | Modal headers, panel titles |
| **Sub-heading (H3)** | 14px – 15px | 1.4 | 600 (Semibold) | `text-sm font-semibold text-gray-300` | Card titles, group labels |
| **Body / Prose** | 13px – 14px | 1.5 | 400 (Regular) | `text-sm text-gray-300` | Chat responses, descriptions |
| **UI Labels / Buttons** | 12px – 13px | 1.4 | 500 (Medium) | `text-xs font-medium` | Navigation items, badges, tab labels |
| **Micro Labels / Meta** | 11px – 12px | 1.3 | 400 (Regular) | `text-[11px] text-gray-400 font-mono` | Line numbers, timestamps, SHA tags |

---

## 4. Spacing, Borders, and Elevation

### 4.1 Spacing Grid
Built on a 4px increment scale:
- `p-1` (4px), `p-2` (8px), `p-3` (12px), `p-4` (16px), `p-6` (24px), `p-8` (32px).
- Compact UI components (tabs, toolbar buttons, activity bar icons) use `gap-1` (4px) or `gap-1.5` (6px).

### 4.2 Borders & Dividers
- **Standard Border:** `border border-[#1e1f23]` (1px solid `#1e1f23`).
- **Subtle Inner Border:** `border border-white/[0.06]`.
- **Active State Border:** `border border-purple-500/50` or `border-purple-500`.
- **Top Active Tab Indicator:** `border-top: 2px solid var(--accent-color)`.
- **Left Activity Bar Indicator:** `border-left: 2px solid var(--cb-accent)`.

### 4.3 Corner Radii
- **Sharp / IDE Elements:** `rounded-none` for editor tabs and connected panel dividers.
- **Compact Controls:** `rounded` (4px) or `rounded-md` (6px) for toolbar buttons, search inputs, badges, and dropdown triggers.
- **Cards & Modals:** `rounded-lg` (8px) or `rounded-xl` (12px) for modals (`SettingsModal`, `ConnectRepoModal`).
- **Pills / Badges:** `rounded-full` for status chips (`RECOMMENDED`, `FAST`, `AVAILABLE`).

### 4.4 Elevation & Shadows
- Shadows are restrained to prevent washing out dark surfaces:
  - Modals: `shadow-2xl shadow-black/80`.
  - Dropdowns: `shadow-xl shadow-black/60 border border-[#1e1f23]`.
  - Subtle Accent Glows: `shadow-md shadow-purple-950/40`.

---

## 5. Reusable Component Inventory

| Component | File Path | Responsibility | Primary Styling Tokens |
| :--- | :--- | :--- | :--- |
| **Navigation** | `frontend/src/components/Navigation.tsx` | Top application header with brand logo, route tabs, and toggle triggers. | Height `h-11`, bg `#0c0d0e`, border `#1e1f22`. |
| **FloatingHeader** | `frontend/src/components/homepage/FloatingHeader.tsx` | GoodsGo-inspired expanding header for public landing page. | Compact pill expanding on hover to full nav width. |
| **ActivityBar** | `frontend/src/components/ActivityBar.tsx` | Vertical left-hand icon bar (Explorer, Search, Problems, Docs, Git). | Width `w-12`, bg `#0c0d0e`, border-r `#1e1f23`, active `activity-bar-active`. |
| **PrimarySidebar** | `frontend/src/components/PrimarySidebar.tsx` | Collapsible sidebar housing FileTree, Issues list, and Git status. | bg `#0c0d0e`, border-r `#1e1f23`. |
| **EditorArea** | `frontend/src/components/EditorArea.tsx` | Monaco editor wrapper with file tabs, breadcrumbs, and line jumps. | bg `#0c0d0e`, tabs `border-b border-[#1e1f23]`. |
| **BottomPanel** | `frontend/src/components/BottomPanel.tsx` | Resizable panel hosting Problems, Output, Automation Logs, and Terminal. | Height resizable, bg `#0c0d0e`, border-t `#1e1f23`. |
| **ChatPanel** | `frontend/src/components/ChatPanel.tsx` | Right-side AI Copilot chat with streaming, citations, and conversation history. | Width resizable, bg `#0c0d0e`, border-l `#1e1f23`. |
| **ModelSelector** | `frontend/src/components/ModelSelector.tsx` | Provider-grouped LLM selector (NVIDIA, Groq, Anthropic, Custom). | Compact trigger, dropdown bg `#18191c`, purple hover. |
| **DiffViewer** | `frontend/src/components/DiffViewer.tsx` | Side-by-side or unified diff renderer for reviewing AI code fixes. | Green (`#34d399`) additions, red (`#f87171`) deletions. |
| **MermaidDiagram** | `frontend/src/components/MermaidDiagram.tsx` | Dynamic SVG renderer for architecture blueprints and flowcharts. | Custom dark theme config, zoom and pan controls. |
| **SettingsModal** | `frontend/src/components/SettingsModal.tsx` | Modal dialog for managing encrypted provider keys and user preferences. | Dialog backdrop `bg-black/70`, container `#141518`. |
| **ConnectRepoModal** | `frontend/src/components/ConnectRepoModal.tsx` | Modal for cloning from GitHub or uploading local `.zip` archives. | Tabbed dialog with drag-and-drop zone and clone form. |
| **ErrorSuggestionCard** | `frontend/src/components/ErrorSuggestionCard.tsx` | Card displaying static analysis issue details, explanation, and fix diff. | Border `#1e1f23`, severity badge, "Generate Fix" CTA. |
| **StatusBar** | `frontend/src/components/StatusBar.tsx` | Bottom workspace status bar displaying branch, encoding, model, and sync status. | Height `h-6`, bg `#0c0d0e`, border-t `#1e1f23`, text `text-xs`. |

---

## 6. Interaction States

All interactive controls (buttons, links, menu items, tabs) must implement clear, accessible state transitions:

- **Default:** Crisp text (`#a1a1aa` or `#f3f3f4`), subtle border, transparent or `#141518` background.
- **Hover:** Fast transition (`transition-all duration-150`), background elevates to `#141518` or `#1e1f23`, text brightens to `#ffffff`.
- **Focus:** Visible accessible focus ring: `focus:outline-none focus:ring-1 focus:ring-purple-500 focus:border-purple-500`.
- **Active / Pressed:** Scale micro-transition (`active:scale-[0.98]`), background `#1a1b1e`.
- **Selected:** Purple accent outline or left/top indicator bar, text `#ffffff`.
- **Disabled:** Reduced opacity (`opacity-50 cursor-not-allowed pointer-events-none`).
- **Loading:** Subtle pulsating skeleton or spinner with informative status label ("Analyzing...", "Cloning...").
- **Empty State:** Centered illustration/icon, muted message (`#71717a`), clear primary call-to-action button.

---

## 7. Workspace Design Rules

1. **Panel Canvas Continuity:** The workspace must feel like a single cohesive desktop IDE rather than disparate web cards. The background color of the FileTree, Editor, Terminal, Problems panel, and Chat panel is uniformly `#0c0d0e`.
2. **Dividers Over Contrast:** Panel boundaries are established via hairline 1px borders (`#1e1f23`) and draggable resize handles (`.resize-handle`), NOT by alternating light and dark panel background colors.
3. **Monaco Editor Synchronization:** Monaco Editor is initialized with custom theme rules matching `#0c0d0e` background and `#f3f3f4` foreground to eliminate visible background clipping between the editor canvas and the surrounding tabs.
4. **Chat Panel Layout:** The chat message stream auto-scrolls smoothly; code blocks within chat responses are fenced with syntax highlighting, language tags, and a "Copy Code" button.

---

## 8. Header and Navigation Policy

### 8.1 Public HomePage Header (`FloatingHeader`)
- **Visual Design:** Floating pill floating above hero content, centered horizontally.
- **Interaction:**
  - Compact state by default displaying logo and primary CTA.
  - Expands smoothly on desktop pointer hover (`group-hover` or state trigger) to reveal full menu links (Features, Architecture, Docs, GitHub).
  - Collapses smoothly on mouse leave.
  - Graceful reduced-motion support without snapping.

### 8.2 Authenticated Top Navigation (`Navigation`)
- **Visual Design:** Full-width fixed top bar (`h-11`, bg `#0c0d0e`, border-b `#1e1f22`).
- **Route Tabs:**
  - Workspace (`/dashboard`)
  - Docs (`/docs`)
  - CI/CD (`/cicd`)
  - History (`/history`)
- **Right Utilities:** Terminal toggle button, Chat Copilot toggle button, Model status badge, Settings gear modal trigger, user avatar.

---

## 9. Responsive Layout Rules

- **Desktop (>= 1280px):** Full 3-column layout active (ActivityBar + PrimarySidebar + EditorArea/BottomPanel + ChatPanel). Resizable panels enabled via `react-resizable-panels`.
- **Laptop / Tablet Landscape (1024px – 1279px):** ChatPanel collapses to overlay or toggle drawer; BottomPanel height constrained to 30%.
- **Tablet Portrait (768px – 1023px):** PrimarySidebar collapses into drawer; editor occupies full width; navigation switches to dropdown menu.
- **Mobile (< 768px):** Single-column stacked layout; bottom navigation bar; modal overlays for Chat and FileTree.

---

## 10. Accessibility & Compliance

- **Semantic HTML:** Correct HTML5 tags (`<header>`, `<nav>`, `<main>`, `<aside>`, `<section>`, `<button>`).
- **Focus Visibility:** Never remove focus rings without providing custom `focus-visible:ring-1 focus-visible:ring-purple-500` replacements.
- **Screen Reader Support:** All icon-only buttons (`lucide-react`) must include descriptive `aria-label` or `title` attributes.
- **Color Contrast:** All body text meets WCAG AA 4.5:1 minimum contrast on `#0c0d0e` and `#161718` surfaces.
- **Motion Reduction:** Supported via `@media (prefers-reduced-motion: reduce)` in Tailwind utilities (`motion-reduce:transition-none`).

---

## 11. Design-System Change Policy

1. **Token Reusability:** Never write ad-hoc hex color codes directly in new components when a standard token exists in `index.css`.
2. **Component Reuse:** Prioritize extending existing components over creating duplicate variants.
3. **Documentation Synchronization:** Any modification to theme colors, fonts, or panel layouts must immediately be documented in this `DESIGN_SYSTEM.md` file.
