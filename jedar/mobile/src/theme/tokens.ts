/**
 * Jedar design tokens. Deep charcoal and midnight navy grounds with muted
 * emerald, warm gold and soft lavender light. Nothing here belongs to a single
 * tradition; the palette is shared across all five faiths.
 */
export const colors = {
  charcoal: "#0F1217",
  midnight: "#0D1524",
  navy: "#152036",
  ink: "#1B2438",
  surface: "rgba(255,255,255,0.045)",
  surfaceRaised: "rgba(255,255,255,0.07)",
  border: "rgba(255,255,255,0.09)",
  borderStrong: "rgba(255,255,255,0.16)",
  emerald: "#2F6F5E",
  mint: "#A8E4CC",
  mintSoft: "rgba(168,228,204,0.18)",
  gold: "#D8B570",
  goldSoft: "rgba(216,181,112,0.18)",
  lavender: "#C7B8F2",
  lavenderSoft: "rgba(199,184,242,0.18)",
  pearl: "#F7F3EA",
  text: "#F3EFE7",
  textMuted: "#AAB0BC",
  textFaint: "#7C8494",
  danger: "#E08A8A",
  dangerSoft: "rgba(224,138,138,0.16)",
} as const;

export const gradients = {
  screen: ["#0B0F17", "#0F1626", "#101A2C", "#0C1119"] as const,
  orbCore: ["#FBF6EA", "#E8D5A8", "#C9B27A"] as const,
  orbMint: ["rgba(168,228,204,0.55)", "rgba(168,228,204,0.0)"] as const,
  orbLavender: ["rgba(199,184,242,0.5)", "rgba(199,184,242,0.0)"] as const,
  primaryButton: ["#E2C27F", "#C9A55B"] as const,
  cardEdge: ["rgba(216,181,112,0.28)", "rgba(216,181,112,0.02)"] as const,
} as const;

export const spacing = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32, huge: 48 } as const;

export const radius = { sm: 10, md: 16, lg: 22, xl: 28, pill: 999 } as const;

export const type = {
  display: { fontSize: 40, lineHeight: 46, fontWeight: "600" as const, letterSpacing: 0.4 },
  title: { fontSize: 26, lineHeight: 32, fontWeight: "600" as const, letterSpacing: 0.2 },
  heading: { fontSize: 20, lineHeight: 26, fontWeight: "600" as const },
  body: { fontSize: 16, lineHeight: 25, fontWeight: "400" as const },
  bodyLarge: { fontSize: 18, lineHeight: 28, fontWeight: "400" as const },
  caption: { fontSize: 13, lineHeight: 18, fontWeight: "500" as const, letterSpacing: 0.6 },
  label: { fontSize: 12, lineHeight: 16, fontWeight: "600" as const, letterSpacing: 1.2, textTransform: "uppercase" as const },
} as const;

export const shadow = {
  glow: (color: string, radiusPx = 24, opacity = 0.35) => ({
    shadowColor: color,
    shadowOpacity: opacity,
    shadowRadius: radiusPx,
    shadowOffset: { width: 0, height: 0 },
    elevation: 0,
  }),
} as const;
