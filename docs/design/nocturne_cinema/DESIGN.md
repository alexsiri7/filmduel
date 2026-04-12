```markdown
# Design System: The Cinematic Curator

## 1. Overview & Creative North Star
The Creative North Star for this design system is **"The Noir Projectionist."** 

This system is not a standard mobile interface; it is a digital private screening room. It captures the atmosphere of a late-night, high-end film club where the environment is dim, the focus is singular, and the quality is uncompromising. To achieve this, we move away from the "app-like" grid and toward an **Editorial Cinematic** layout. 

The design breaks the template look through **intentional asymmetry**, utilizing large-scale condensed typography that occasionally bleeds off-canvas or overlaps image containers. We treat the screen as a film frame—every element must have "cinematic weight." By prioritizing tonal depth over structural lines, we create an immersive, game-like refinement that feels exclusive and atmospheric.

---

## 2. Colors
Our palette is rooted in the warmth of a vintage celluloid projector. It uses high-contrast accents against a near-black void to guide the eye like a spotlight.

### Core Palette
- **Background (`#0F0E0D`)**: The "Void." Used for the base canvas to ensure maximum immersion.
- **Primary: Amber Gold (`#E8A020`)**: The "Projection." Used for critical CTAs, active states, and highlighting key film data.
- **Secondary: Coral Rust (`#C04A20`)**: The "Velvet." Used for secondary actions, "Live" indicators, or warning states.
- **Typography (`#F5F0E8`)**: The "Script." Warm off-white to prevent the eye strain of pure white on black.

### The "No-Line" Rule
**Prohibit 1px solid borders for sectioning.** Boundaries must be defined solely through background color shifts. To separate a film category from the main feed, use a shift from `surface` to `surface_container_low`. If a separation is too subtle, increase the vertical whitespace rather than adding a stroke.

### Surface Hierarchy & Nesting
Treat the UI as layered sheets of acetate.
1.  **Base Layer:** `surface_dim` (#141312) for the global background.
2.  **Section Layer:** `surface_container_low` (#1d1b1a) for secondary content blocks.
3.  **Feature Layer:** `surface_container` (#211f1e) for primary interactive cards.
4.  **Floating Layer:** `surface_bright` (#3b3937) for modals or pop-overs.

### Glass & Texture
For floating navigation bars or "Now Playing" overlays, utilize **Glassmorphism**. Use the `surface` color at 70% opacity with a `backdrop-blur` of 20px. This allows the cinematic posters beneath to bleed through, maintaining the "Late-Night" depth.

---

## 3. Typography
The typography is the "Voice" of the club. It balances the aggressive authority of a movie poster with the legibility of a screenplay.

- **Display & Headline (Space Grotesk):** Bold, condensed, and architectural. Use `display-lg` for film titles and `headline-md` for section headers. Don't be afraid of tight letter-spacing (-2% to -4%) to increase the "Poster" feel.
- **Body & Title (Manrope):** A clean, modern sans-serif. Use `body-lg` for film synopses to ensure high legibility against dark backgrounds.
- **Labels:** Use `label-md` in all-caps with increased letter-spacing (+10%) for metadata (e.g., GENRE, RUNTIME, RATING).

---

## 4. Elevation & Depth
In this system, depth is a matter of light, not shadow.

- **The Layering Principle:** Achieve lift by stacking. A `surface_container_highest` card sitting on a `surface_dim` background creates a natural visual "pop" without needing a drop shadow.
- **Ambient Shadows:** When an element must float (e.g., a floating action button), use a shadow tinted with the primary amber color: `rgba(232, 160, 32, 0.08)` with a 32px blur. Avoid black or grey shadows.
- **The "Ghost Border" Fallback:** If a container requires definition against a similar background, use a 1px border of `outline_variant` at **15% opacity**. It should be felt, not seen.
- **Intentional Asymmetry:** Break the grid. Align a title to the far left, but place the "Play" button off-center to the right. This creates a "staggered" visual rhythm common in high-end film credits.

---

## 5. Components

### Buttons
- **Primary:** Background: `primary` (#ffbe5b), Text: `on_primary` (#442b00). Hard edges (`roundness-sm`). High-contrast, bold, uppercase.
- **Secondary:** Background: `none`, Border: `outline` (at 20% opacity), Text: `primary`.
- **Tertiary:** Text: `on_surface_variant`, no background. Used for "Cancel" or "Back" actions.

### Cards & Lists
- **Film Cards:** Strictly no borders or dividers. Use `surface_container_low` for the card background. The "Divider" is 24px of empty space.
- **Metadata Lists:** Use `label-md` for keys (e.g., DIRECTOR) in `muted grey` (#6B6760) and `body-md` for values in `off-white` (#F5F0E8).

### Input Fields
- **Text Inputs:** Use `surface_container_lowest`. No bottom line. Use a 2px `primary` left-border only when the field is focused to mimic a typewriter cursor.

### Signature Component: The "Ticket" Tab
For the navigation or selection chips, use a "Ticket" shape—rectangular with `roundness-none` and a subtle `outline_variant` "Ghost Border." When selected, the background fills with `primary` and the text knocks out to `on_primary`.

---

## 6. Do's and Don'ts

### Do
- **DO** use extremely high-quality film stills as the background for hero sections.
- **DO** use `primary` (Amber Gold) for interactive "touch points" only.
- **DO** allow typography to overlap image containers for an editorial feel.
- **DO** embrace "The Void"—negative space is your most valuable asset to create a premium feel.

### Don't
- **DON'T** use standard 8px or 16px border-radii. Keep it sharp (`sm` or `none`) to maintain the "Film Noir" edge.
- **DON'T** use dividers or lines to separate content. Let the colors and whitespace do the work.
- **DON'T** use pure black (#000000). Always use the warm near-black (#0F0E0D) to keep the "Private Club" atmosphere.
- **DON'T** use icons for everything. Where possible, use high-contrast text labels (e.g., "ENTER" instead of a right arrow).

---

## 7. Interaction States
- **Hover/Active:** When a film card is tapped, it should scale slightly (1.02x) and the `surface_container` should shift to `primary_container` at 10% opacity, creating a warm "glow" effect.
- **Loading:** Use a custom "Film Reel" shimmer—a subtle diagonal light sweep across `surface_container` elements using the `primary_fixed_dim` color at 5% opacity.```