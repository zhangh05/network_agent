# DESIGN.md — 网工智枢 (Network Agent)

> AI-friendly design system document.  
> Consumable by Stitch, human designers, and code-generation agents.  
> Version: v1.0.1-UI | Last updated: 2026-06-12

---

## 1. Brand Identity

| Field | Value |
|---|---|
| **Product name** | 网工智枢 |
| **English name** | Network Agent |
| **Tagline** | Operations Console |
| **Brand mark** | 网 (calligraphic single character, displayed in a 30×30 rounded square) |
| **Personality** | Professional, precise, calm, scholarly — like a skilled network engineer with classical Chinese aesthetic sensibilities |
| **Design language** | 暖墨 (Warm Ink) — traditional ink painting meets modern dev-tool UI |

---

## 2. Color System

### 2.1 Theme Concept

The design language is rooted in **Chinese ink painting aesthetics**: warm paper tones for the background, vermillion (朱红) as the accent, and a spectrum from deep ink-black to faint ink-wash grays for text hierarchy.

Two themes are supported: **light** (default, `[data-theme]` omitted) and **dark** (`data-theme="dark"`).

### 2.2 Light Theme

```yaml
colors:
  light:
    background:
      base:        "#f7f3e8"   # warm paper
      elevated:    "#fdfbf4"   # slightly brighter
      soft:        "#efe9d8"   # subtle depth
      deep:        "#e6dec8"   # deepest background layer
      overlay:     "rgba(28, 26, 23, 0.45)"  # modal backdrop

    ink:            "#1c1a17"   # primary text — deep black-brown
    ink-soft:       "#4a463f"   # secondary text
    ink-mute:       "#8a857a"   # tertiary / muted
    ink-faint:      "#b8b3a6"   # placeholder / disabled

    border:
      line:         "#e3dcc8"   # default border
      line-soft:    "#ede7d5"   # subtle border
      line-strong:  "#c8c0a8"   # emphasized border

    accent:          "#b8302c"   # 朱红 — primary brand color
    accent-soft:     "#f3d5d1"   # accent background / selection
    accent-deep:     "#8e211d"   # accent hover / pressed
    accent-on:       "#fdfbf4"   # text on accent background

    secondary:       "#1f4a6b"   # 墨蓝 — info / secondary actions
    secondary-soft:  "#d5dee7"
    secondary-deep:  "#14334d"

    semantic:
      success:       "#4a7c4d"
      success-soft:  "#d8e4d4"
      warning:       "#c7891a"
      warning-soft:  "#f0e0c0"
      danger:        "#b8302c"
      danger-soft:   "#f3d5d1"

    review-states:
      pending:       "#c7891a"
      accepted:      "#4a7c4d"
      ignored:       "#8a857a"
      modified:      "#1f4a6b"
```

### 2.3 Dark Theme

```yaml
colors:
  dark:
    background:
      base:        "#0f0e0c"
      elevated:    "#181612"
      soft:        "#14130f"
      deep:        "#0a0907"
      overlay:     "rgba(0, 0, 0, 0.65)"

    ink:            "#f3eddc"
    ink-soft:       "#c4bdab"
    ink-mute:       "#8a857a"
    ink-faint:      "#5a554c"

    border:
      line:         "#2a2620"
      line-soft:    "#1f1d18"
      line-strong:  "#3a362d"

    accent:          "#e85d4a"   # warmer vermillion for dark
    accent-soft:     "#3a1814"
    accent-deep:     "#ff7a64"
    accent-on:       "#0f0e0c"

    secondary:       "#6ba0c8"
    secondary-soft:  "#1a2c3a"
    secondary-deep:  "#9bbedb"

    semantic:
      success:       "#7ab87a"
      success-soft:  "#1c2c1c"
      warning:       "#e0a040"
      warning-soft:  "#2c2418"
      danger:        "#e85d4a"
      danger-soft:   "#3a1814"

    review-states:
      pending:       "#e0a040"
      accepted:      "#7ab87a"
      ignored:       "#8a857a"
      modified:      "#6ba0c8"
```

### 2.4 Usage Rules

- **Accent (朱红)**: Primary buttons, active states, brand mark, card title bar decoration, focus rings. Never use for informational elements.
- **Secondary (墨蓝)**: Info pills, secondary indicators, modified review state.
- **Ink hierarchy**: `ink` for primary content, `ink-soft` for descriptions, `ink-mute` for metadata, `ink-faint` for placeholders/disabled.
- **Semantic colors**: success=green for OK/accepted, warning=amber for pending/alerts, danger=red for errors/rejected.
- **Review states**: dedicated pill colors for review workflow (pending/accepted/ignored/modified).

---

## 3. Typography

### 3.1 Font Stack

```yaml
typography:
  display:  "Noto Serif SC", "Source Han Serif SC", "Songti SC", "STSong", "宋体", serif
  sans:     "Noto Sans SC", -apple-system, BlinkMacSystemFont, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "微软雅黑", "Helvetica Neue", Arial, sans-serif
  mono:     "JetBrains Mono", "Cascadia Code", "Fira Code", "SF Mono", Menlo, Consolas, monospace
```

### 3.2 Usage

| Role | Font | Weight | Note |
|---|---|---|---|
| Headings (h1–h4) | `display` | 600 | Serif font for classical feel |
| Body / UI text | `sans` | 400/500 | Clean, modern Chinese typography |
| Code / data / metadata | `mono` | 400/500 | Tabular numbers, no ligatures |
| Brand text | `display` | 600/700 | |

### 3.3 Type Scale

```yaml
scale:
  xs:    11px
  sm:    12px
  base:  13px    # body default
  md:    14px
  lg:    16px
  xl:    20px
  2xl:   24px
  3xl:   32px
```

### 3.4 Line Heights

```yaml
line-height:
  tight:  1.3    # headings
  base:   1.55   # body
  loose:  1.7    # chat bubbles, spacious text
```

### 3.5 Font Rendering

```yaml
rendering:
  - -webkit-font-smoothing: antialiased
  - -moz-osx-font-smoothing: grayscale
  - text-rendering: optimizeLegibility
  - -webkit-tap-highlight-color: transparent
```

---

## 4. Spacing & Layout

### 4.1 Spacing Scale

```yaml
spacing:
  xs:  2px
  sm:  4px    # gap minimal
  md:  8px    # default gap, mb-2/mt-2
  lg:  12px   # mb-3/mt-3
  xl:  16px   # mb-4/mt-4
  2xl: 20px
  3xl: 24px
  4xl: 32px
```

### 4.2 Page Layout

```yaml
page:
  header-padding:   "24px 28px 16px"
  body-padding:     "20px 28px 32px"
  header:
    border-bottom:  "1px solid var(--line-soft)"
    background:     "var(--bg-elev)"
```

### 4.3 Content Width

```yaml
content:
  chat-max-width:   760px   # centered in chat view
  suggestion-grid:  540px   # suggestion cards
  message-gap:      20px    # between chat messages
```

---

## 5. Border Radius

```yaml
radius:
  xs:  4px    # code inline, tags
  sm:  6px    # small buttons, sidebar items, icons
  md:  10px   # default for buttons, inputs, cards
  lg:  14px   # cards, chat bubbles
  xl:  20px   # hero mark
```

---

## 6. Shadows

```yaml
shadows:
  light:
    sh-1:     "0 1px 2px rgba(28, 26, 23, 0.04)"                               # subtle elevation
    sh-2:     "0 2px 8px rgba(28, 26, 23, 0.06), 0 1px 2px rgba(28, 26, 23, 0.04)"  # cards, dropdowns
    sh-3:     "0 8px 24px rgba(28, 26, 23, 0.10), 0 2px 6px rgba(28, 26, 23, 0.04)"  # modals, toasts
    sh-inset: "inset 0 1px 0 rgba(255, 255, 255, 0.5)"                         # buttons, brand mark

  dark:
    sh-1:     "0 1px 2px rgba(0, 0, 0, 0.3)"
    sh-2:     "0 2px 8px rgba(0, 0, 0, 0.4), 0 1px 2px rgba(0, 0, 0, 0.3)"
    sh-3:     "0 8px 24px rgba(0, 0, 0, 0.5), 0 2px 6px rgba(0, 0, 0, 0.3)"
    sh-inset: "inset 0 1px 0 rgba(255, 255, 255, 0.04)"
```

---

## 7. Component Patterns

### 7.1 Button System

```yaml
button:
  base:
    display:         inline-flex
    align-items:     center
    justify-content: center
    gap:             6px
    height:           32px
    padding:          0 14px
    font-family:     var(--font-sans)
    font-size:       13px
    font-weight:     500
    color:           var(--ink)
    background:      var(--bg-elev)
    border:          1px solid var(--line)
    border-radius:   var(--r)    # 10px
    box-shadow:      var(--sh-1)
    transition:      "background 0.15s ease, border-color 0.15s ease, color 0.15s ease, transform 0.1s ease"

  hover:             "border-color: var(--line-strong); background: var(--bg-soft)"
  active:            "transform: translateY(0.5px)"
  focus-visible:     "outline: 2px solid var(--accent); outline-offset: 2px"
  disabled:          "opacity: 0.45; cursor: not-allowed"

  variants:
    primary:
      background:    var(--accent)
      color:         var(--accent-on)
      border-color:  var(--accent)
      box-shadow:    "var(--sh-1), var(--sh-inset)"
      hover:
        background:  var(--accent-deep)
        border-color: var(--accent-deep)

    ghost:
      background:    transparent
      border-color:  transparent
      box-shadow:    none
      hover:
        background:  var(--bg-soft)

    danger:
      color:         var(--danger)
      hover:
        background:  var(--danger-soft)
        border-color: var(--danger)

  sizes:
    sm:
      height:        26px
      padding:       0 10px
      font-size:     12px
      border-radius: 6px

    icon-only:
      width:         32px
      padding:       0
    icon-only-sm:
      width:         26px
```

### 7.2 Input System

```yaml
input:
  base:
    height:          32px
    padding:         0 12px
    font-family:     var(--font-sans)
    font-size:       13px
    color:           var(--ink)
    background:      var(--bg-elev)
    border:          1px solid var(--line)
    border-radius:   var(--r)    # 10px
    width:           100%
    appearance:      none
    transition:      "border-color 0.15s ease, box-shadow 0.15s ease"

  hover:             "border-color: var(--line-strong)"
  focus:             "border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft)"
  placeholder:       "color: var(--ink-faint)"
  disabled:          "opacity: 0.5; cursor: not-allowed"

  textarea:
    height:          auto
    min-height:      80px
    padding:         10px 12px
    resize:          vertical

  select:
    background:      custom chevron via inline SVG
```

### 7.3 Card

```yaml
card:
  background:       var(--bg-elev)
  border:           1px solid var(--line)
  border-radius:    var(--r-lg)    # 14px
  padding:           18px
  margin-bottom:     14px
  box-shadow:       var(--sh-1)
  transition:       "border-color 0.15s ease, box-shadow 0.15s ease"
  hover:
    border-color:   var(--line-strong)

  title:
    font-family:    var(--font-display)
    font-size:      14px
    font-weight:    600
    margin-bottom:  14px
    gap:            10px
    decoration:     "3px × 14px accent bar (::before pseudoelement)"
```

### 7.4 Badge / Pill

```yaml
badge:
  base:
    display:        inline-flex
    align-items:    center
    gap:            4px
    height:         20px
    padding:        0 8px
    font-size:      11px
    font-weight:    500
    border-radius:  10px    # fully rounded pill
    white-space:    nowrap

  variants:
    default:        "background: var(--bg-soft); color: var(--ink-soft); border: 1px solid var(--line-soft)"
    ok/success:     "background: var(--success-soft); color: var(--success); border: transparent"
    warn:           "background: var(--warning-soft); color: var(--warning); border: transparent"
    err/danger:     "background: var(--danger-soft); color: var(--danger); border: transparent"
    info:           "background: var(--secondary-soft); color: var(--secondary); border: transparent"
    accent:         "background: var(--accent-soft); color: var(--accent-deep); border: transparent"
    muted:          "background: transparent; color: var(--ink-mute); border: 1px solid var(--line)"

  dot-indicator:
    size:           5px × 5px
    shape:          circle
    color:          inherits from parent text color
```

### 7.5 Table

```yaml
table:
  font-size:        13px
  border-collapse:  separate
  border-spacing:   0

  thead:
    th:
      font-weight:  500
      padding:      10px 14px
      background:   var(--bg-soft)
      color:        var(--ink-mute)
      border-bottom: "1px solid var(--line)"
      font-size:    11px
      text-transform: uppercase
      letter-spacing: 0.08em
      sticky:       top 0

  tbody:
    td:
      padding:      12px 14px
      border-bottom: "1px solid var(--line-soft)"
      background:   var(--bg-elev)
    tr:
      hover:        "td background → var(--bg-soft)"

  corner-radius:    "thead th:first-child → border-top-left-radius, th:last-child → border-top-right-radius; value = var(--r)"
```

### 7.6 Sidebar List Item

```yaml
list-item:
  display:          flex
  align-items:      center
  gap:              8px
  height:           32px
  padding:          0 10px
  border-radius:    6px
  font-size:        13px
  color:            var(--ink-soft)
  cursor:           pointer
  background:       transparent
  width:            100%

  hover:            "background: var(--bg-soft); color: var(--ink)"
  active:
    background:     var(--accent-soft)
    color:          var(--accent-deep)       # light; var(--accent) in dark
    font-weight:    500

  status-dot:
    size:           6px × 6px
    shape:          circle
    states:
      ok:           var(--success)
      err:          var(--danger)
      warn:         var(--warning)
      busy:         var(--secondary) + pulse animation (1.5s)
      idle:         var(--ink-faint)
```

### 7.7 Modal

```yaml
modal:
  backdrop:
    position:       fixed, inset 0
    background:     var(--bg-overlay)
    z-index:        200
    animation:      fadeIn 0.15s ease-out
    filter:         blur(4px)

  container:
    background:     var(--bg-elev)
    border:         1px solid var(--line)
    border-radius:  var(--r-lg)
    padding:        22px 24px
    box-shadow:     var(--sh-3)
    min-width:      360px
    max-width:      600px
    animation:      slideUp 0.2s ease-out

  title:
    font-family:    var(--font-display)
    font-size:      20px
    font-weight:    600
    margin-bottom:  16px
    decoration:     "4px × 18px accent bar (::before pseudoelement)"

  actions:
    display:        flex, gap 8px
    justify-content: flex-end
    margin-top:      20px
```

### 7.8 Toast Notification

```yaml
toast:
  position:         "fixed, bottom: 20px, right: 20px, z-index: 1000"
  max-width:        380px
  gap:              8px

  item:
    background:     var(--bg-elev)
    border:         "1px solid var(--line)"
    border-left:    "3px solid var(--ink-mute)"  # colored per variant
    border-radius:  var(--r)
    padding:        12px 14px
    box-shadow:     var(--sh-3)
    animation:      slideUp 0.2s ease-out
    min-width:      240px

  variants:
    success:        "border-left-color: var(--success)"
    error:          "border-left-color: var(--danger)"
    warning:        "border-left-color: var(--warning)"
    info:           "border-left-color: var(--secondary)"
```

### 7.9 Chat (Agent Workbench)

```yaml
chat:
  shell:
    flex:           1
    background:     "var(--bg) + radial gradients at corners"

  stream:
    padding:        24px 28px 16px
    gap:            20px
    max-width:      760px (per message)

  message:
    animation:      fadeIn 0.25s ease-out
    avatar:
      size:         32px × 32px
      radius:       6px
      assistant:    "background: var(--accent); color: var(--accent-on)"
      user:         "background: var(--bg-soft); color: var(--ink-soft)"

    bubble:
      background:   var(--bg-elev)
      border:       1px solid var(--line)
      border-radius: 14px
      padding:      12px 16px
      font-size:    14px
      line-height:  1.7
      box-shadow:   var(--sh-1)
      max-width:    calc(100% - 44px)

      user-bubble:  "background: var(--accent); color: var(--accent-on); border-color: var(--accent); box-shadow: var(--sh-2), var(--sh-inset)"

    tool-calls:
      border-top:   "1px dashed var(--line)"
      item:
        background: var(--bg-soft)
        border:     1px solid var(--line-soft)
        border-radius: 6px
        padding:    6px 10px
        font-size:  12px
        font-family: var(--font-mono)

  input-area:
    border-top:     "1px solid var(--line)"
    background:     var(--bg-elev)
    padding:        16px 28px 20px

    textarea:
      flex:         1
      border:       none
      background:   transparent
      font-size:    14px
      min-height:   32px
      max-height:   160px
      placeholder:  "color: var(--ink-faint)"

  empty-state:
    centered text with:
      hello-text: "font-family: var(--font-display); font-size: 32px; with accent span"
      subtitle:   "font-size: 14px; max-width: 420px; color: var(--ink-mute)"
      suggestions: "2-column grid, max 540px, card-style hover items"
```

### 7.10 Tab Bar

```yaml
tabs:
  container:
    display:        flex
    gap:            4px
    border-bottom:  1px solid var(--line)
    margin-bottom:  16px

  tab:
    padding:        8px 14px
    font-size:      13px
    color:          var(--ink-mute)
    border-bottom:  2px solid transparent
    cursor:         pointer
    background:     transparent
    transition:     "color 0.15s ease, border-color 0.15s ease"

    hover:          "color: var(--ink)"
    active:         "color: var(--accent); border-bottom-color: var(--accent); font-weight: 500"
```

### 7.11 Skeleton Loader

```yaml
skeleton:
  background:       "linear-gradient(90deg, var(--bg-soft), var(--bg-deep), var(--bg-soft))"
  animation:        shimmer 1.5s ease-in-out infinite (200% background-size sweep)
  height:            16px
  border-radius:    6px
```

### 7.12 Tooltip

```yaml
tooltip:
  trigger:          "[data-tip] attribute on element"
  position:         "above element, centered"
  style:
    background:     var(--ink)
    color:          var(--bg)
    padding:        4px 8px
    border-radius:  4px
    font-size:      11px
    white-space:    nowrap
    box-shadow:     var(--sh-2)
```

### 7.13 Code Block

```yaml
code-inline:
  font-size:        0.92em (≈12px)
  padding:          2px 6px
  background:       var(--bg-soft)
  border-radius:    4px
  color:            var(--accent-deep)  # light; var(--accent) in dark
  border:           1px solid var(--line-soft)
  font-family:      var(--font-mono)

code-block:
  background:       var(--bg-deep)
  border:           1px solid var(--line)
  border-radius:    10px
  padding:          12px 14px
  font-size:        12px
  max-height:       320px
  overflow-y:       auto
  white-space:      pre-wrap
```

### 7.14 Inspector Panel

```yaml
inspector:
  section:
    border-bottom:  "1px solid var(--line-soft)"
    padding:        14px 18px

    title:
      font-family:  var(--font-display)
      font-size:    12px
      font-weight:  600
      color:        var(--ink-mute)
      text-transform: uppercase
      letter-spacing: 0.1em
      collapsible:  yes (chevron rotation)

    row:
      grid:         "80px 1fr, gap 8px"
      label:        "11px, uppercase, color: var(--ink-mute)"
      value:        "12px, mono, color: var(--ink)"
```

### 7.15 Theme Toggle

```yaml
theme-toggle:
  size:             32px × 32px
  border-radius:    6px
  background:       transparent
  border:           1px solid transparent
  color:            var(--ink-soft)
  hover:
    background:     var(--bg-soft)
    color:          var(--ink)
    border-color:   var(--line-soft)
  icons:            sun (☀) / moon (☽), 14px
```

### 7.16 Status Pill (Top Bar)

```yaml
status-pill:
  display:          inline-flex
  align-items:      center
  gap:              6px
  height:           24px
  padding:          0 10px
  background:       var(--bg-soft)
  border:           1px solid var(--line-soft)
  border-radius:    12px
  font-size:        11px
  font-family:      var(--font-mono)
  color:            var(--ink-soft)
  dot:
    size:           6px circle
    states:         ok=var(--success), warn=var(--warning), err=var(--danger)
```

### 7.17 Empty State

```yaml
empty-state:
  alignment:        center
  padding:          40px 20px
  color:            var(--ink-mute)
  icon:
    size:           40px × 40px
    radius:         12px
    background:     var(--bg-soft)
  title:            "font-family: var(--font-display); font-size: 14px; color: var(--ink-soft)"
  hint:             "font-size: 12px; color: var(--ink-mute)"
```

### 7.18 Tag

```yaml
tag:
  display:          inline-flex
  height:           18px
  padding:          0 6px
  font-size:        10px
  font-weight:      500
  border-radius:    4px
  background:       var(--bg-soft)
  color:            var(--ink-soft)
  border:           1px solid var(--line-soft)
  font-family:      var(--font-mono)
  letter-spacing:   0.02em
  margin-right:     4px
  margin-bottom:    2px
```

---

## 8. Animation & Motion

### 8.1 Animation Tokens

```yaml
motion:
  ease-standard:  cubic-bezier(0.2, 0.8, 0.2, 1)   # transitions
  ease-press:     cubic-bezier(0.2, 0, 0, 1)        # button press

  duration:
    fast:          120ms    # micro-interactions
    default:       180ms    # standard
    slow:          260ms    # page entry, modals
```

### 8.2 Named Animations

```yaml
animations:
  fadeIn:
    from:          "opacity: 0; transform: translateY(4px)"
    to:            "opacity: 1; transform: translateY(0)"
    duration:      0.25s
    easing:        ease-out
    use:           ".fade-in — chat messages, modals"

  slideIn:
    from:          "opacity: 0; transform: translateX(-8px)"
    to:            "opacity: 1; transform: translateX(0)"
    duration:      0.2s
    easing:        ease-out
    use:           ".slide-in — sidebar content"

  slideUp:
    from:          "opacity: 0; transform: translateY(8px)"
    to:            "opacity: 1; transform: translateY(0)"
    duration:      0.25s
    easing:        cubic-bezier(0.4, 0, 0.2, 1)
    use:           ".slide-up — toasts, modals"

  spin:
    from/to:       "transform: rotate(0deg / 360deg)"
    duration:      0.8s
    timing:        linear, infinite
    use:           loading spinner (16px, border: 2px solid var(--line), top-color: var(--accent))

  pulse:
    0%/100%:       "opacity: 1"
    50%:           "opacity: 0.4"
    duration:      1.5s
    timing:        ease-in-out, infinite
    use:           "busy status dot, processing indicators"

  skeletonShimmer:
    0%:            "background-position: 200% 0"
    100%:          "background-position: -200% 0"
    duration:      1.5s
    timing:        ease-in-out, infinite
    use:           skeleton loading states
```

### 8.3 Reduced Motion

```yaml
prefers-reduced-motion:
  all-animations:   "duration: 0.01ms; iteration-count: 1"
  all-transitions:  "duration: 0.01ms"
  scroll-behavior:  auto
```

---

## 9. App Shell & Layout Architecture

### 9.1 Shell Grid

```yaml
app-shell:
  display:          grid
  grid-template-rows: "56px 1fr"
  height:           100vh
  overflow:         hidden

app-header:
  display:          flex
  align-items:      center
  padding:          0 18px
  gap:              16px
  background:       var(--bg-elev)
  border-bottom:    1px solid var(--line)
  z-index:          10
  backdrop-filter:  saturate(180%) blur(8px)
  decoration:       gradient underline (pseudo ::after)

app-main:
  display:          grid
  grid-template-columns: "auto minmax(0, 1fr) auto"
  # sidebar | content | inspector

app-sidebar:
  width:            280px (collapsed: 64px)
  background:       var(--bg-elev)
  border-right:     1px solid var(--line)
  padding:          18px 14px
  transition:       width 0.2s cubic-bezier(0.4, 0, 0.2, 1)

app-content:
  flex:             1
  overflow:         hidden
  min-width:        0

app-inspector:
  width:            380px (collapsed: 0)
  background:       var(--bg-elev)
  border-left:      1px solid var(--line)
  transition:       width 0.2s cubic-bezier(0.4, 0, 0.2, 1)
```

### 9.2 Page Pattern

```yaml
page:
  page-header:    "padding: 24px 28px 16px; border-bottom: 1px solid var(--line-soft); background: var(--bg-elev)"
  page-body:      "padding: 20px 28px 32px; overflow-y: auto; flex: 1"
  page-body-no-pad: "padding: 0"
```

### 9.3 Route Pages

```yaml
routes:
  /workbench:       "Agent Workbench — chat interface, 3 columns (sidebar+content+inspector)"
  /knowledge:       "Knowledge Library — upload, import, search, 2 columns (sidebar+content)"
  /artifacts:       "Artifact Center — list, preview, actions, 2 columns"
  /reviews:         "Review Center — human review workflow, 2 columns"
  /capabilities:    "Capability Matrix — capability listing, 2 columns"
  /audit:           "Runtime Audit — runs, traces, tools, 2 columns"
  /settings:        "Settings — LLM config, 2 columns"
  /:                "Redirect → /workbench"
```

---

## 10. Responsive Breakpoints

```yaml
breakpoints:

  "≤1100px":
    header:          "compact: gap 10px, padding 0 12px"
    brand-subtitle:  hidden
    nav:             "overflow-x: auto (scroll without scrollbar)"
    status-pill:     hidden

  "≤900px":
    main:            "single column: grid-template-columns → minmax(0, 1fr)"
    sidebar:         hidden
    inspector:       hidden
    page-header:     "padding: 18px 18px 12px; flex-wrap: wrap"
    page-body:       "padding: 16px 18px 24px"
    split-shell:     "single column, aside → border-bottom, max-height 320px"
    table:           "min-width: 640px (horizontal scroll)"

  "≤560px":
    header-height:   52px
    brand-mark:      "28px × 28px, font-size: 14px"
    brand-text:      hidden
    nav-item:        "gap 4px, padding 0 8px, text overflow ellipsis"
    h1:              "font-size: 20px"
    card:            "padding: 14px"
    modal:           "width: calc(100% - 24px), padding: 18px, actions full-width stretch"
    toast:           "left: 12px, right: 12px, bottom: 12px, max-width: none"
```

---

## 11. Design Tokens Reference (CSS Custom Properties)

Complete list of all CSS custom properties defined in the design system:

```yaml
tokens:
  background:       [--bg, --bg-elev, --bg-soft, --bg-deep, --bg-overlay]
  ink:              [--ink, --ink-soft, --ink-mute, --ink-faint]
  border:           [--line, --line-soft, --line-strong]
  accent:           [--accent, --accent-soft, --accent-deep, --accent-on]
  secondary:        [--secondary, --secondary-soft, --secondary-deep]
  semantic:         [--success, --success-soft, --ok, --warning, --warning-soft, --warn, --danger, --danger-soft]
  review:           [--st-pending, --st-accepted, --st-ignored, --st-modified]
  radius:           [--r-xs: 4px, --r-sm: 6px, --r: 10px, --r-lg: 14px, --r-xl: 20px]
  shadow:           [--sh-1, --sh-2, --sh-3, --sh-inset]
  font:             [--font-display, --font-sans, --font-mono]
  font-size:        [--fs-xs: 11px, --fs-sm: 12px, --fs-base: 13px, --fs-md: 14px, --fs-lg: 16px, --fs-xl: 20px, --fs-2xl: 24px, --fs-3xl: 32px]
  line-height:      [--lh-tight: 1.3, --lh-base: 1.55, --lh-loose: 1.7]
  layout:           [--h-header: 56px, --w-sidebar: 280px, --w-sidebar-collapsed: 64px, --w-inspector: 380px]
  ease:             [--ease-standard, --ease-press]
  duration:         [--dur-fast: 120ms, --dur: 180ms, --dur-slow: 260ms]
```

---

## 12. Design Principles

1. **Content-first**: The UI recedes; the network engineering content takes center stage. Backgrounds are warm and understated.
2. **Ink hierarchy**: Text weight is expressed through color, not just size — from `--ink` (primary) through `--ink-faint` (placeholder).
3. **Breathing room**: Generous padding (28px horizontal on pages) and spacing (20px gaps in chat). Clutter is the enemy of precision work.
4. **Predictable motion**: All interactions follow defined easing curves and durations. Nothing snaps — everything transitions.
5. **Accessible feedback**: Focus rings (accent, 2px offset), hover states, disabled states, and `prefers-reduced-motion` support are non-negotiable.
6. **Chinese-first**: Typography optimized for CJK text, with Noto Serif for headings and Noto Sans for body. English text uses system-native fallbacks.
7. **Ambient depth**: Subtle radial background gradients replace flat colors; backdrop blur on the header creates a sense of layered space.
8. **No mock data**: Every UI element is API-backed. Empty states explain when and why content appears.

---

## 13. Tech Stack Reference

```yaml
stack:
  framework:       React 18
  language:        TypeScript
  build:           Vite 5
  routing:         React Router (v7 future flags)
  state:           Zustand
  http:            Axios
  styling:         CSS (no preprocessor, designsystem-driven via custom properties)
  testing:
    unit:          Vitest (15 test files)
    e2e:           Playwright (12 spec files)
```

---

## 14. File Manifest

```yaml
files:
  design-tokens:    "frontend/src/styles/global.css"
  app-shell:        "frontend/src/app/App.tsx"
  layout:           "frontend/src/layouts/AppLayout.tsx"
  pages:            "frontend/src/pages/*/"
  components:       "frontend/src/components/*"
  icons:            "frontend/src/components/Icon.tsx"
  types:            "frontend/src/types/index.ts"
  api-client:       "frontend/src/api/client.ts"
```

---

## 15. How to Use This Document with Stitch

When sending this `DESIGN.md` to Stitch:

- **To generate a new page**: describe the page's purpose, data relationships, and user flow. Stitch will reference the component patterns, color system, and layout rules.
- **To iterate an existing page**: reference the page component name (e.g., "KnowledgeLibrary") and describe the desired changes. Stitch will preserve the existing design language.
- **To add a new component variant**: specify where in the component hierarchy it belongs (e.g., "new `btn.outline` variant") and what distinguishes it visually.
- **To check consistency**: ask Stitch to audit any generated UI against this DESIGN.md's tokens and patterns.
