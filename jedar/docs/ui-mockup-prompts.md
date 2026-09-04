# Jedar AI: UI mockup and asset prompts

These prompts are saved for future image and UI generation. They have not been run yet; the
MVP ships with gradients, shapes, and typography instead of generated assets. When assets are
produced, keep the constraints below: original identity, inclusive across Sikh, Muslim,
Christian, Hindu, and Jewish users, no sacred text as decoration, no stereotypes, and no
resemblance to ChatGPT or any other assistant.

## Overall design-system prompt

“Create an original premium mobile design system for Jedar AI, a voice-first faith reflection companion. Use deep charcoal, midnight navy, muted emerald, warm gold, and soft lavender. The mood should feel peaceful, intimate, respectful, and modern. Use subtle atmospheric glow, soft depth, mature rounded cards, elegant typography, generous spacing, and high accessibility. The visual identity must be inclusive across Sikh, Muslim, Christian, Hindu, and Jewish users. Do not copy ChatGPT or any existing AI assistant. Avoid decorative scripture, religious stereotypes, excessive symbols, neon cyberpunk styling, and crowded layouts.”

## Faith-selection mockup prompt

“Design a premium dark mobile faith-selection screen for Jedar AI. Show five respectful cards: Sikh, Muslim, Christian, Hindu, and Jewish. Each card has a restrained symbol or abstract icon, faith name, one-line description, and elegant selection indicator. Use a midnight gradient, soft mint and gold highlights, spacious composition, refined typography, and subtle depth. The screen should feel welcoming and neutral across traditions. No people, flags, costumes, sacred quotations, or visual stereotypes.”

## Daily-reflection mockup prompt

“Design the Today screen for Jedar AI, a premium faith-reflection app. Feature one large daily Reflection card with a small faith label, the label ‘Reflection,’ a short title, two or three lines of warm curated text, a primary ‘Talk about this’ button, and a secondary ‘Save to journal’ action. Add a restrained glowing atmospheric background and a small daily reminder indicator. Use deep navy and charcoal with muted emerald, warm gold, and lavender accents. Original design only; do not resemble ChatGPT.”

## Main voice-screen mockup prompt

“Design an original voice-first mobile conversation screen for Jedar AI. Place a unique softly glowing spiritual orb in the center against a layered midnight gradient. Include mode chips for Calm, Prayer, Guidance, Journal, and Learn; a ‘Start talking’ button; subtle listening status; a compact transcript panel; text fallback; and an End session control. The orb should feel warm, organic, and contemplative, not technological or copied from another AI product. Use soft mint, gold, and lavender light.”

## Journal mockup prompt

“Design a private journal screen for Jedar AI using a premium dark theme. Show a calm list of saved reflections, personal notes, and optional conversation entries. Include faith filters, dates, entry types, a minimal search field, and a warm floating New entry button. Use layered charcoal cards, subtle gold dividers, muted emerald highlights, elegant typography, and generous spacing. The mood should feel personal, safe, reflective, and uncluttered.”

## Orb asset prompt

“Create an isolated original glowing orb asset for Jedar AI on a transparent background. The orb should feel organic, calm, warm, and spiritual, formed from soft translucent layers of muted emerald, pearl white, warm gold, and lavender. Add a gentle luminous core and subtle flowing internal texture. No text, faces, religious symbols, hard rings, or resemblance to ChatGPT’s voice orb. Premium mobile UI asset, centered composition.”

## Background asset prompt

“Create a subtle vertical mobile background for Jedar AI using midnight navy and charcoal gradients with extremely soft emerald, warm gold, and lavender atmospheric light. Keep the center readable for white interface text. No stars, temples, churches, mosques, people, religious symbols, or written text. Elegant, inclusive, minimal, premium, and suitable behind a voice interface.”

## Where generated assets would go

| Asset | Path | Used by |
| --- | --- | --- |
| App icon (1024×1024) | `mobile/assets/icon.png` | `app.json` → `expo.icon` |
| Adaptive icon foreground | `mobile/assets/adaptive-icon.png` | `app.json` → `expo.android.adaptiveIcon` |
| Splash image | `mobile/assets/splash.png` | `expo-splash-screen` plugin `image` option |
| Notification icon (monochrome) | `mobile/assets/notification-icon.png` | `expo-notifications` plugin `icon` option |
| Orb | `mobile/assets/orb.png` | Optional replacement for the procedural `Orb` component |
| Background | `mobile/assets/background.png` | Optional replacement for the `Screen` gradient |

Current palette tokens live in `mobile/src/theme/tokens.ts`.
