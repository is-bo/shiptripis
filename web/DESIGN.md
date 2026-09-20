---
name: ShipTrip public web
description: Warm Mediterranean travel, with the route as the product motif.
colors:
  canvas: "#f4efe6"
  surface: "#faf6ee"
  surface-raised: "#fffcf5"
  text-primary: "#0e1f2c"
  text-secondary: "#2a3b49"
  brand: "#0e5a4f"
  brand-strong: "#0a4a40"
  accent: "#fbbc04"
  attention-print: "#9b4318"
typography:
  display:
    fontFamily: "Fraunces, Georgia, serif"
    fontWeight: 600
    letterSpacing: "-.02em"
  body:
    fontFamily: "DM Sans, Segoe UI, sans-serif"
    fontSize: "1rem"
    lineHeight: 1.62
  arabic:
    fontFamily: "Noto Sans Arabic, Segoe UI, sans-serif"
rounded:
  sm: "8px"
  md: "14px"
  lg: "20px"
  pill: "999px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.pill}"
    height: "48px"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.pill}"
  card:
    backgroundColor: "{colors.surface-raised}"
    rounded: "{rounded.md}"
---

# Design System: ShipTrip public web

## Overview

**Creative North Star: "Editorial Mediterranean travel."**

The public site keeps ShipTrip's warm paper, deep ink, Algerian emerald,
terracotta identity seal, yellow primary action, and serif display voice.
The route is a meaningful motif: people already travel, and parcels can share
their journeys. Geographic visuals use recognizable places and restrained
natural tones. This document covers `web/`; root DESIGN.md covers Flutter.

**Key Characteristics:**

- Warm, human, travel-oriented typography and materials.
- Geographic illustration grounded in real coastlines and country shapes.
- Restrained borders, supporting captions, and clear sender/traveler actions.

## Colors

Paper and navy provide the ground and readable content. Emerald carries brand
emphasis and international routes. Yellow identifies the sender's primary
action; terracotta appears in the existing seal and local Algerian road routes.
Take values from `assets/site.css`; local hero styles reference those tokens.

## Typography

Fraunces sets display headings and the featured journey. DM Sans carries
Latin body text and controls. Noto Sans Arabic carries Arabic, with heavier
display weight instead of synthetic italics. All fonts are bundled locally.
JetBrains Mono remains available to existing reference/code components.
Display type is large and editorial; labels recede without competing with it.

## Layout

The existing header and downstream page sections retain the shared 1140px
shell. The hero extends to 1280px, with more room for the globe than the copy.
The globe is capped at 700px and stays within its column. Below 760px, copy and
actions precede a full-width globe; short landscape surfaces use two columns.
Arabic mirrors content placement and directional arrows, never geography.

## Elevation & Depth

The globe earns depth through perspective, directional light, horizon shading,
and a soft ground shadow. Its single journey card has a restrained paper edge
and shallow shadow. Keep imagery readable; do not add neon, glass, or dramatic
space lighting. Existing paper texture remains part of the supplied identity.

## Shapes

Controls retain the established pill silhouette, cards the existing medium
radius, and navigation the terracotta circular seal. Use fine country borders,
small endpoint dots, and light route halos on the globe.

## Components

The sender button uses the incumbent yellow primary treatment and links to
the existing sender section. The ghost button links to the traveler section.
Focus outlines and hover states come from the shared site stylesheet.

The globe is a progressive enhancement: local static sphere first, then
native WebGL geography with a separate canvas route layer. Its journey card
follows an active illustrative route without announcing continuous changes
to assistive technology. A labeled pause/resume control stops ambient motion;
reduced motion produces a complete still network with no spawning loop.

## Do's and Don'ts

- **Do** reuse the existing wordmark, paper, fonts, colors, and buttons.
- **Do** label synthetic journeys as illustrative in each locale.
- **Do** keep Algeria prominent and route density subordinate to geography.
- **Do** preserve local assets and the existing self-only CSP.
- **Don't** present simulated routes as actual bookings or departures.
- **Don't** mirror country geometry in RTL or add active Morocco/Tunisia routes.
- **Don't** replace flight/car symbols with people, emoji, or unrelated vehicles.
