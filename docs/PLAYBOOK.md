# The Playbook

The strategy this repo encodes. Read once, then let `revops today` drive the day.

---

## The core claim

**Sell the capability, not the content.**

Everyone building an AI-content channel assumes the money is ad revenue. Run the
numbers and it isn't, not at any scale you'll reach this year:

| Stream | Rate | What 1,000,000 views pays |
|---|---|---|
| YouTube Shorts | $0.01–$0.15 RPM | **$10 – $150** |
| TikTok Creator Rewards | $0.40–$1.00 RPM | **$400 – $1,000**, and only on 1min+ videos |
| One client ad spot | $300–$2,000 flat | **$300 – $2,000**, no views required at all |

A million short-form views is a genuinely hard year of work. One client spot is
an afternoon with the pipeline you already run. The asymmetry isn't close.

So the model is:

```
content  →  proof of capability  →  clients + products  →  money
   └──────→ audience ─────────────→ merch + sponsors (later, bigger)
```

Content is the **top of the funnel and the portfolio**. It is not the product.
Treating it as the product is the single most common way creators work for years
at minimum wage.

The corollary that matters day to day: **a video that gets 5,000 views and one
client enquiry beats a video that gets 500,000 views and none.** The system
tracks clicks and revenue per piece precisely so you can tell those apart.

---

## Why this fits your setup specifically

You already own the expensive half. `gemini-anime-clip-chain` produces the
clips, `marketing-head` distributes to seven platforms, Higgsfield generates and
predicts virality, Shopify can sell without inventory. Production and
distribution are solved.

What's missing is the **revenue layer and the feedback loop** — knowing which
content earns, and having something to sell to the people it reaches. That gap
is the entire opportunity, and it's what this repo closes.

---

## Phases

### Phase 0 — Instrument (week 1)

Do not change what you make yet. You cannot optimise what you haven't measured,
and every "obvious" content instinct is wrong about half the time.

- [ ] Log every piece with `revops new` — **topic, hook, cost, minutes**
- [ ] Log every upload with `revops post`
- [ ] Snapshot performance ~7 days after posting with `revops track`
- [ ] Sign up for affiliate programs and put **one** link destination in every bio
- [ ] Log the recurring tool costs you already pay with `revops spend`

Exit when ~20 pieces are logged. Below that, rankings are noise — the tool
tells you so rather than pretending otherwise.

### Phase 1 — First real dollar (weeks 2–6)

Affiliate income starts now and stays small; that's expected. Its job is to
prove the audience→click→buy bridge exists at all.

The actual target this phase is **client work**, which needs no audience:

- [ ] Cut a **45-second showreel** from your six best clips. This is your entire sales asset.
- [ ] Pick one vertical that already pays for animation: indie games, mobile apps, streamers, Shopify brands.
- [ ] Send **10 personalised offers a day**. The offer that converts: *a free 5-second custom spot for their product,* made before they reply.
- [ ] Price the first three at **$300** to earn testimonials. Then $800. Then $1,500.

Ten free spots costs you a weekend of credits and closes roughly one to three
clients. That single conversion outearns your first year of Shorts RPM.

### Phase 2 — Products and compounding (months 2–4)

Your audience contains people who want to make what you make. Sell them the
process at ~95% margin:

- [ ] Package your working pipeline: prompts, character sheets, settings, project files
- [ ] $19–$49 on Shopify as a digital product — no inventory, no shipping
- [ ] One "how I made this" post per week that ends at the product
- [ ] Raise client rates every three closed jobs until you start losing deals

### Phase 3 — Audience monetization (month 4+)

Only now do follower-gated streams pay enough to bother with. Merch needs a
**recurring character** — people buy identity, not quality. Sponsorships need a
**defined niche**. Both are unlocked by consistency in Phases 0–2, not chased
directly.

---

## The daily loop (1–2 hours)

```
 10 min   revops today            — read the brief, note the one action
 60 min   produce                 — make the next piece; copy last week's winners
 10 min   revops new / post       — log it, publish via marketing-head
 20 min   sell                    — 10 client DMs, or one product-facing post
 --------------------------------------------------------------
  ~5 min  revops track            — snapshot last week's pieces
```

The selling block is non-negotiable and it is the block people skip. Production
feels productive; only the sell block has ever produced a $300 line item.

---

## Budget allocation (a few hundred dollars)

Spend it in this order. Do not skip ahead.

| Priority | Item | Why |
|---|---|---|
| 1 | Generation credits | Volume is the input to everything. Nothing else matters if you can't ship. |
| 2 | Domain + Shopify basic | You need somewhere to send clicks and sell products. |
| 3 | Reserve ~$50 | Free spec spots for client prospects. Highest-ROI dollars available. |
| 4 | Ads — **last** | Only after one piece of organic content already converts. Paid traffic amplifies a working funnel and burns money on a broken one. |

---

## Kill criteria

Decide these now, while you're calm, so a bad month doesn't get rationalised:

- **A topic** with n≥10 and a median below half your overall median → stop making it.
- **A platform** returning under 25% of your best platform's views/post → automate it or drop it.
- **Affiliate** at 100k+ views and under $10 → the offer is wrong, not the traffic. Change the offer.
- **Client outreach** at 100 sent DMs and zero replies → the showreel is the problem, not the pitch.
- **Ads** that don't return spend within 14 days → stop. Immediately.

---

## Honest expectations

Realistic outcomes for one person at 1–2 hours a day, consistently:

- **Month 1:** $0–$50. Almost entirely instrumentation and the first showreel.
- **Month 3:** $300–$1,500, dominated by one or two client spots.
- **Month 6:** $1,000–$4,000/mo if client work compounds and a product launches.
- **Month 12:** genuinely wide. Depends almost entirely on whether you shipped daily.

The variable that predicts the outcome is **consistency**, not talent, not tools,
and not the algorithm. This system exists to make consistency measurable and to
stop you optimising the wrong half of the business.
