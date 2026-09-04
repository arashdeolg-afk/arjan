# Jedar AI

A calm, voice-first faith-guidance companion. Jedar helps people reflect, pray, journal, learn,
and talk through personal concerns in the context of their chosen faith: Sikh, Muslim,
Christian, Hindu, or Jewish.

Jedar is **not** a deity, prophet, therapist, clergy member, or religious authority. It never
claims supernatural certainty and never replaces qualified human guidance. Those boundaries are
written into the server-side system instructions and tested.

```
jedar/
├── server/     Express + TypeScript API (curated reflections, Realtime voice broker, text fallback)
├── mobile/     Expo SDK 57 + Expo Router + TypeScript app (development build; voice needs native WebRTC)
├── docs/       UI mockup and asset prompts
├── CONTENT_REVIEW.md
└── README.md   (this file)
```

## Contents

1. [How it works](#how-it-works)
2. [Requirements](#requirements)
3. [Quick start](#quick-start)
4. [Server](#server)
5. [Mobile app](#mobile-app)
6. [Development build (required for voice)](#development-build-required-for-voice)
7. [Physical device setup](#physical-device-setup)
8. [Backend deployment](#backend-deployment)
9. [Testing and verification](#testing-and-verification)
10. [Religious-content integrity](#religious-content-integrity)
11. [Privacy and data](#privacy-and-data)
12. [Production safety and privacy checklist](#production-safety-and-privacy-checklist)
13. [File tree](#file-tree)
14. [Known limitations](#known-limitations)

## How it works

```
┌──────────────┐  SDP offer + faith/mode/voice/reflectionId (headers)  ┌──────────────┐
│  Mobile app  │ ───────────────────────────────────────────────────▶ │ Jedar server │
│ (react-native│                                                      │  (Express)   │
│   -webrtc)   │ ◀─────────────────── SDP answer ──────────────────── │              │
└──────┬───────┘                                                      └──────┬───────┘
       │  WebRTC audio + "oai-events" data channel                            │ POST /v1/realtime/calls
       ▼                                                                      │ (server-only API key,
   OpenAI Realtime (media flows peer-to-peer once the answer is applied)  ◀───┘  full instructions)
```

- **Curated content only.** `GET /api/reflections/today` picks a record from
  `server/content/reflections.json` deterministically from faith + local date. The model never
  writes daily content.
- **Trusted context.** "Talk about this" sends only a reflection **ID**. The server looks the
  text up and embeds it in Jedar's instructions. The client can never supply instructions or
  reflection text.
- **One instruction builder.** `server/src/instructions.ts` produces Jedar's system
  instructions for both the Realtime voice session and the `/api/text` fallback.
- **Keys stay on the server.** The mobile bundle contains only `EXPO_PUBLIC_API_URL`.
- **Private journal.** Reflections, notes, and (only on explicit request) conversations are
  stored in an on-device SQLite database and never uploaded.

## Requirements

| Tool | Version |
| --- | --- |
| Node.js | 22.13 or newer (the server uses global `fetch`/`FormData`; the mobile tests use `node:sqlite`) |
| npm | 10 or newer |
| Expo SDK | 57 (pinned in `mobile/package.json`) |
| Xcode / Android Studio | Needed to compile the development build for iOS / Android |
| An OpenAI API key | With access to the Realtime and Responses APIs |

## Quick start

```bash
cd jedar
npm install                      # installs server/ and mobile/ (postinstall)

# 1. Server
cp server/.env.example server/.env
#    edit server/.env: set OPENAI_API_KEY and a long random SAFETY_ID_SALT
npm run server                   # http://0.0.0.0:8787

# 2. Mobile
cp mobile/.env.example mobile/.env
#    edit mobile/.env: EXPO_PUBLIC_API_URL=http://<your LAN IP>:8787
cd mobile
npx expo prebuild                # generates ios/ and android/ with the WebRTC + notifications plugins
npx expo run:ios --device        # or: npx expo run:android --device
```

Without an `OPENAI_API_KEY` the server still starts (outside production) and the text
composer answers with a clearly labelled offline reply, so the whole app can be exercised
end to end. Voice needs a real key.

## Server

Location: `server/`. Stack: Express 5, TypeScript, Zod, Helmet, CORS, express-rate-limit.
No OpenAI SDK; the two upstream calls use `fetch` directly so the request shapes are explicit.

### Environment (`server/.env.example`)

```
OPENAI_API_KEY=sk-server-only          # server only; never copy into the mobile project
PORT=8787
OPENAI_REALTIME_MODEL=gpt-realtime-2.1
OPENAI_TEXT_MODEL=gpt-5-mini
OPENAI_TRANSCRIPTION_MODEL=gpt-4o-mini-transcribe
CORS_ORIGIN=http://localhost:8081      # comma-separated browser origins; native apps send no Origin
SAFETY_ID_SALT=replace-with-a-long-random-value
```

`loadEnv()` validates all of this at boot and refuses placeholder values in production.

### Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | `{ ok, voice }` where `voice` is whether an API key is configured |
| GET | `/api/reflections/today?faith=sikh&date=YYYY-MM-DD` | Deterministic daily record for that faith and local date |
| GET | `/api/reflections/:id` | One record by ID (IDs match `^[a-z]+-[a-z0-9-]{1,40}$`) |
| POST | `/api/realtime/session` | Body: SDP offer (`Content-Type: application/sdp`). Headers: `X-Jedar-Faith`, `X-Jedar-Mode`, `X-Jedar-Voice`, optional `X-Jedar-Reflection`, optional `X-Jedar-Install`. Returns the SDP answer with status 201. |
| POST | `/api/text` | JSON `{ message, faith, mode?, reflectionId?, history? }` → `{ text }` |

Validation: faith ∈ {sikh, muslim, christian, hindu, jewish}; mode ∈ {calm, prayer, guidance,
journal, learn}; voice ∈ {maya, noor, ayaan}; message ≤ 2000 chars; history ≤ 20 turns of
user/assistant only; a reflection must belong to the selected faith. Unknown JSON fields are
ignored, so a client cannot smuggle `instructions`.

### Realtime flow

`server/src/openai.ts` posts a `multipart/form-data` body with `sdp` and a `session` JSON
object to `POST {OPENAI_BASE_URL}/realtime/calls`. The session config sets the model, the full
Jedar instructions, `output_modalities: ["audio"]`, input transcription with
`OPENAI_TRANSCRIPTION_MODEL`, semantic voice-activity detection with interruption enabled, and
the mapped OpenAI voice. The answer SDP is returned to the app. The `x-request-id` and
`Location` (call ID) headers plus the hashed safety identifier are logged; content is not.
(The Realtime session object has no `safety_identifier` field; the text path sends one.)

### Voices

| Product name | Description | OpenAI voice |
| --- | --- | --- |
| Maya | Calm female | `marin` |
| Noor | Gentle female | `shimmer` |
| Ayaan | Grounded male | `cedar` |

The mapping lives in `server/src/voices.ts`. The app never sees the right-hand column.

### Security measures

Helmet, CORS allow-list (native requests without an `Origin` header are accepted), JSON body
limit 32 kB, SDP body limit 64 kB, per-IP rate limits (120/min reads, 20/min AI routes), Zod on
every input, generic client-facing error messages, structured logs with secret redaction, no
transcript or journal storage, and HMAC-hashed safety identifiers (`server/src/safety.ts`) so
OpenAI never receives the raw install ID.

## Mobile app

Location: `mobile/`. Stack: Expo SDK 57, Expo Router, TypeScript, `react-native-webrtc`,
`expo-sqlite`, `expo-notifications`, `expo-linear-gradient`.

### Journey

```
Welcome → Faith selection → Voice selection → Today (tabs: Today · Voice · Journal · Settings)
Today card "Talk about this" → Voice tab with the reflection as trusted context
```

### Screens

- **Welcome**: "Jedar AI", "Faith guidance by voice", **Begin**, and the boundary line
  "A supportive companion, never a religious authority".
- **Faith selection**: five cards with abstract glyphs (no sacred symbols or text).
- **Voice selection**: Maya, Noor, Ayaan.
- **Today**: the daily card (label Reflection or Scripture, faith, title, text, source only for
  approved scripture, **Talk about this**, **Save to journal**) and a reminder indicator.
- **Voice**: layered midnight gradient, breathing orb (calmer when idle, brighter and quicker
  while speaking, halo while listening, dimmer and slower while reflecting), mode chips (Calm,
  Prayer, Guidance, Journal, Learn), status text (Ready when you are / Connecting / Listening /
  Reflecting / Speaking / Connection paused), live transcript, text composer, End session,
  optional reflection banner, and an explicit "Save conversation to journal" action.
- **Journal**: search, faith and type filters, entry list, New entry, open / edit / delete with
  confirmation, created and updated timestamps.
- **Settings**: faith, voice, daily reminder (explanation before permission, on/off, time picker
  in local time, permission status, link to device settings when denied), server status, the
  boundary statement, **Delete all journal data**, and **Start over**.

### Realtime events handled (`mobile/src/lib/realtimeEvents.ts`)

`session.created`, `input_audio_buffer.speech_started`, `input_audio_buffer.speech_stopped`,
`conversation.item.input_audio_transcription.completed`,
`response.output_audio_transcript.delta`, `response.output_audio_transcript.done`,
`response.done`, `error`, plus peer-connection state changes (`disconnected`/`failed` →
"Connection paused", `closed` → idle). Ending a session or leaving the Voice tab stops the
microphone track, remote tracks, data channel, and peer connection.

### Notifications

- Permission is never requested at launch. Enabling reminders in Settings first shows an
  explanation; only tapping **Continue** triggers the OS prompt.
- One daily local notification, scheduled with expo-notifications' `DAILY` trigger in the
  device's timezone, rescheduled whenever the time changes, cancelled when disabled.
- Copy: "Your Jedar reflection is ready" / "Take a quiet moment for today's reflection."
  No personal content ever appears on the lock screen.
- Tapping the notification opens the Today tab (payload `{ screen: "today" }` is validated).
- Denied permission is handled gracefully; the app keeps working.

## Development build (required for voice)

`react-native-webrtc` contains native code. **Expo Go cannot run the voice feature.** In Expo
Go the app will launch, onboarding, Today, Journal, Settings, and the text composer work, but
tapping **Start talking** fails because the WebRTC native module is missing. Build a
development client instead:

```bash
cd mobile
npx expo prebuild                 # applies expo-router, expo-notifications, expo-sqlite,
                                  # expo-splash-screen and @config-plugins/react-native-webrtc
npx expo run:ios --device         # needs Xcode + a signing team
npx expo run:android --device     # needs Android Studio / SDK, USB debugging enabled
npx expo start --dev-client       # afterwards, start Metro for the installed dev client
```

Or with EAS Build (cloud):

```bash
npm i -g eas-cli
eas login
eas build:configure
eas build --profile development --platform ios     # or android
```

The config plugin adds `NSMicrophoneUsageDescription` on iOS and `RECORD_AUDIO` /
`MODIFY_AUDIO_SETTINGS` on Android. iOS also lists `audio` in `UIBackgroundModes` so a
conversation continues if the screen locks.

## Physical device setup

1. Put the phone and the computer on the same Wi-Fi network.
2. Find the computer's LAN IP (`ipconfig getifaddr en0` on macOS, `hostname -I` on Linux,
   `ipconfig` on Windows).
3. In `mobile/.env` set `EXPO_PUBLIC_API_URL=http://<LAN IP>:8787`. Restart Metro after
   changing it (`npx expo start --dev-client -c`).
4. Start the server (`npm run server` from `jedar/`). It binds to `0.0.0.0` so the phone can
   reach it. Allow port 8787 through the computer's firewall.
5. Install the development build on the device (see above), open it, and connect to Metro.
6. Open **Settings** in the app: the Connection card shows whether the server is reachable and
   whether voice is configured.
7. iOS: the first **Start talking** shows the microphone prompt. Android 13+: the reminder
   toggle shows the notification prompt after the in-app explanation.
8. Plain `http://` to a LAN IP works in development builds on both platforms (the generated
   iOS project sets `NSAllowsLocalNetworking`). For a production build use HTTPS (see
   deployment).

### iPhone specifics

- Any Apple ID works for a development build. `mobile/plugins/withoutPushEntitlement.js`
  strips the remote-push entitlement that expo-notifications adds, because that capability
  is unavailable on free personal teams and Jedar only uses local notifications. With a free
  team the install expires after 7 days; rebuild to renew.
- First run of `npx expo run:ios --device` stops at "requires a development team": open
  `ios/JedarAI.xcworkspace` in Xcode, select the JedarAI target → Signing & Capabilities →
  choose your Team, then run the command again.
- On the phone: enable Developer Mode (Settings → Privacy & Security → Developer Mode,
  iOS 16+), and after the first install trust the developer certificate under Settings →
  General → VPN & Device Management.
- Expect two system prompts on first launch: Local Network (so the app can reach Metro and
  the Jedar server on your Wi-Fi) and Microphone (on first **Start talking**).
- Remote audio plays through the default route, which may be the earpiece; hold the phone to
  your ear or see Known limitations for loudspeaker output.

## Backend deployment

The server is a single Node process with no database. Any Node 22 host works.

```bash
cd server
npm ci
npm run build          # emits dist/
NODE_ENV=production node dist/index.js
```

- Set `OPENAI_API_KEY`, `SAFETY_ID_SALT` (32+ random characters), `CORS_ORIGIN`, and
  `NODE_ENV=production` as real environment variables, not in a committed file.
- Put the server behind HTTPS (a platform load balancer, Caddy, or nginx). The app must use
  an `https://` URL in production; App Transport Security on iOS blocks plain HTTP.
- `app.set("trust proxy", 1)` is enabled so rate limiting sees the real client IP behind one
  proxy layer. Adjust if you run more hops.
- Example Dockerfile:

  ```Dockerfile
  FROM node:22-alpine
  WORKDIR /app
  COPY server/package*.json ./
  RUN npm ci
  COPY server/ .
  RUN npm run build
  ENV NODE_ENV=production PORT=8787
  EXPOSE 8787
  CMD ["node", "dist/index.js"]
  ```

- Health check: `GET /health`. Logs are single-line JSON on stdout; secrets are redacted.
- Update `mobile/.env` (`EXPO_PUBLIC_API_URL=https://your-host`) and rebuild the app.

## Testing and verification

From `jedar/`:

```bash
npm install
npm run typecheck     # tsc for server and mobile
npm test              # node:test suites for server and mobile
cd mobile && npx expo-doctor
```

Results at delivery (Node 22.22, Expo SDK 57.0.19):

| Check | Result |
| --- | --- |
| `server` typecheck | pass |
| `server` tests | 35 passed, 0 failed |
| `mobile` typecheck | pass |
| `mobile` tests | 24 passed, 0 failed |
| `npx expo prebuild --no-install` | success (iOS and Android projects generate; microphone and notification permissions present) |
| `npx expo-doctor` | 18 of 19 checks passed offline; the "Expo config schema" check could not download the schema in the build sandbox (blocked host), so run it locally |
| SDK version alignment | every Expo/React Native package matches `expo/bundledNativeModules.json` for SDK 57 (checked offline) |

expo-doctor's config-schema, dependency-version, and React Native Directory checks call the
Expo API. The sandbox used to build this project blocks those hosts, so those checks were run
offline (`EXPO_OFFLINE=1`) and the version alignment was verified against
`node_modules/expo/bundledNativeModules.json` instead. Run `npx expo-doctor` locally with
network access before releasing. Warnings about unknown packages in React Native Directory are
informational and already muted in `mobile/package.json` (`expo.doctor`).

What the tests cover:

- Server: the exact five faiths; deterministic daily selection; unapproved records always
  labelled Reflection; scripture requiring approval, source, reference, and reviewer; a
  reflection never carrying a citation; invalid reflection IDs; authority boundaries and
  faith-specific guidance in the instructions; every API validation path; generic errors;
  safety-identifier hashing; environment validation; log redaction; CORS.
- Mobile: journal create/list/filter/search/update/delete/delete-all on a real SQLite
  database; preference persistence and clamping; notification trigger, content, next-fire
  date, time parsing, and rescheduling decisions; the voice session state machine for every
  handled Realtime event; API header construction; local-date handling.

The mobile tests exercise pure modules with Node's built-in SQLite so they run without a
device or Jest. Screen components are typechecked; UI behaviour is verified manually on a
development build.

## Religious-content integrity

See [`CONTENT_REVIEW.md`](./CONTENT_REVIEW.md). Summary of enforced rules:

- Daily content comes only from `server/content/reflections.json`.
- Unapproved content is always type `reflection` and shows the label **Reflection**.
- A reflection can never carry a source or reference.
- Scripture is shown only when `approved: true` with `sourceName`, `reference`, and
  `reviewedBy`; otherwise the server refuses to start.
- The sample data contains only original reflections (20 records, four per faith) and no
  scripture at all.
- Jedar's instructions forbid fabricating scripture, quotations, laws, historical claims, or
  divine messages and direct rulings to qualified clergy or scholars.

## Privacy and data

| Data | Where it lives | Leaves the device? |
| --- | --- | --- |
| Faith, voice, reminder settings | On-device SQLite (`jedar.db`) | No |
| Journal entries | On-device SQLite | No |
| Voice audio | Streams to OpenAI via WebRTC during a session | Yes, during the session only; the Jedar server never sees audio |
| Voice transcripts | In memory on the device | Not stored anywhere unless the user chooses "Save conversation to journal" |
| Text composer messages and last 20 turns | Sent to the Jedar server, forwarded to OpenAI with `store: false` | Yes, not persisted by the server |
| Install ID | Random UUID on the device | Sent as a header; the server hashes it with `SAFETY_ID_SALT`. The hash goes to OpenAI as `safety_identifier` on text requests and only to server logs for voice sessions |

## Production safety and privacy checklist

- [ ] `OPENAI_API_KEY` exists only in the server environment. Grep the mobile project and the
      built bundle for `sk-` before every release.
- [ ] `SAFETY_ID_SALT` is a unique, long random value per environment and is never rotated
      silently (rotation changes all safety identifiers).
- [ ] `NODE_ENV=production` on the server so placeholder values are rejected and the offline
      text gateway is disabled.
- [ ] Server reachable only over HTTPS; `EXPO_PUBLIC_API_URL` uses `https://`.
- [ ] `CORS_ORIGIN` lists only your web origins (native apps are unaffected).
- [ ] Rate limits reviewed for your expected traffic; consider per-install limits using the
      hashed identifier.
- [ ] Logs contain request IDs and status codes only. Confirm no transcripts, messages, or
      journal text are logged (grep for `message:` fields in log calls).
- [ ] Every scripture record has been reviewed by a qualified representative of that faith
      and carries `reviewedBy`; sample data contains no scripture.
- [ ] Reflections re-read with a faith advisor within the last year.
- [ ] Crisis guidance in `instructions.ts` reviewed against local emergency and crisis-line
      practice for your launch regions; consider showing local numbers in the app.
- [ ] App Store / Play listing states clearly that Jedar is not clergy, therapy, or medical
      care and does not provide religious rulings.
- [ ] Microphone and notification permission strings reviewed; no permission requested
      before an in-app explanation.
- [ ] Notification content contains no personal data.
- [ ] Journal data stays on device; "Delete all journal data" verified on both platforms.
- [ ] Privacy policy published covering audio streaming to OpenAI during sessions, the hashed
      install identifier, and data retention (server: none).
- [ ] OpenAI data-retention and usage settings reviewed for your organisation; Realtime
      sessions are not stored by this server.
- [ ] Dependency audit (`npm audit`) run on both packages; `react-native-webrtc` and Expo SDK
      kept current.
- [ ] Accessibility pass: dynamic type up to 140% (capped in components), VoiceOver / TalkBack
      labels on cards, chips, buttons, and the orb.
- [ ] Voice sessions end on tab change and screen unmount; verify the microphone indicator
      disappears on both platforms.

## File tree

```
jedar/
├── .gitignore
├── CONTENT_REVIEW.md
├── README.md
├── package.json                      # root scripts: install (postinstall), typecheck, test, doctor
├── docs/
│   └── ui-mockup-prompts.md
├── server/
│   ├── .env.example
│   ├── .gitignore
│   ├── package.json
│   ├── tsconfig.json
│   ├── tsconfig.build.json
│   ├── content/
│   │   └── reflections.json          # curated daily content (20 original reflections)
│   ├── src/
│   │   ├── app.ts                    # Express app: helmet, cors, limits, rate limits, routes, errors
│   │   ├── content.ts                # schema validation, integrity rules, deterministic selection
│   │   ├── domain.ts                 # faiths, modes, voices
│   │   ├── env.ts                    # environment validation + tiny .env loader
│   │   ├── index.ts                  # entrypoint
│   │   ├── instructions.ts           # the one Jedar system-instruction builder
│   │   ├── logger.ts                 # JSON logs with secret redaction
│   │   ├── openai.ts                 # Realtime call broker + Responses API client + offline gateway
│   │   ├── safety.ts                 # HMAC safety identifiers
│   │   ├── voices.ts                 # Maya/Noor/Ayaan → OpenAI voices
│   │   └── routes/
│   │       ├── realtime.ts           # POST /api/realtime/session
│   │       ├── reflections.ts        # GET /api/reflections/today, /api/reflections/:id
│   │       └── text.ts               # POST /api/text
│   └── test/
│       ├── api.test.ts
│       ├── content.test.ts
│       ├── domain.test.ts
│       ├── helpers.ts
│       └── instructions.test.ts
└── mobile/
    ├── .env.example
    ├── .gitignore
    ├── app.json                      # Expo config + plugins (router, notifications, sqlite, splash, webrtc)
    ├── package.json
    ├── tsconfig.json
    ├── plugins/
    │   └── withoutPushEntitlement.js # drops the remote-push entitlement (local notifications only)
    ├── app/                          # Expo Router
    │   ├── _layout.tsx               # providers, notification tap routing, root stack
    │   ├── index.tsx                 # redirect: onboarding or Today
    │   ├── onboarding/
    │   │   ├── welcome.tsx
    │   │   ├── faith.tsx
    │   │   └── voice.tsx
    │   ├── (tabs)/
    │   │   ├── _layout.tsx           # Today · Voice · Journal · Settings
    │   │   ├── today.tsx
    │   │   ├── voice.tsx
    │   │   ├── journal.tsx
    │   │   └── settings.tsx
    │   └── journal/
    │       ├── new.tsx
    │       └── [id].tsx
    ├── src/
    │   ├── components/
    │   │   ├── Button.tsx
    │   │   ├── Card.tsx
    │   │   ├── Chip.tsx
    │   │   ├── Composer.tsx          # text fallback
    │   │   ├── FaithGlyph.tsx        # abstract per-faith marks
    │   │   ├── Orb.tsx               # animated Jedar orb
    │   │   ├── ReflectionCard.tsx
    │   │   ├── Screen.tsx            # gradient + atmosphere background
    │   │   ├── TabGlyph.tsx
    │   │   ├── TimePicker.tsx
    │   │   ├── TranscriptPanel.tsx
    │   │   └── Typography.tsx
    │   ├── lib/
    │   │   ├── api.ts                # server client (reflections, text, realtime session)
    │   │   ├── dates.ts
    │   │   ├── db.ts                 # expo-sqlite bootstrap
    │   │   ├── domain.ts             # mirrors server domain
    │   │   ├── journal.ts            # JournalRepository
    │   │   ├── notificationService.ts# expo-notifications wiring
    │   │   ├── notifications.ts      # pure scheduling helpers
    │   │   ├── preferences.ts
    │   │   ├── realtime.ts           # WebRTC session (react-native-webrtc)
    │   │   ├── realtimeEvents.ts     # session state machine
    │   │   ├── schema.ts             # SQLite schema + Database interface
    │   │   └── useVoiceSession.ts
    │   ├── state/
    │   │   └── AppContext.tsx
    │   └── theme/
    │       └── tokens.ts
    └── test/
        ├── api.test.ts
        ├── journal.test.ts
        ├── notifications.test.ts
        ├── realtimeEvents.test.ts
        └── sqliteAdapter.ts          # node:sqlite adapter for tests
```

## Known limitations

- **Audio route.** `react-native-webrtc` plays remote audio through the default route. On some
  iOS devices that is the earpiece rather than the speaker. If you need loudspeaker output by
  default, add `react-native-incall-manager` and call `setSpeakerphoneOn(true)` when a session
  starts.
- **No app icon or splash artwork yet.** Expo's default icon is used until the assets from
  `docs/ui-mockup-prompts.md` are produced and referenced in `app.json`.
- **Model names are configuration.** `OPENAI_REALTIME_MODEL`, `OPENAI_TEXT_MODEL`, and
  `OPENAI_TRANSCRIPTION_MODEL` are environment variables; update them as OpenAI releases new
  models.
- **Expo Go** shows the app but cannot run voice; use a development build.
- **Single-device journal.** There is no sync or export in the MVP by design.
