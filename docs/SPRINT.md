# The 7-Day Sprint

The most predictable money you can make in a week, and exactly how.

---

## Why this and not anything else

Every other option fails the 7-day test for a structural reason:

| Option | Why it can't pay inside 7 days |
|---|---|
| Ad revenue | Threshold-gated. 1,000 subs / 10k followers minimum. Not reachable. |
| Affiliate | Needs traffic volume you don't have. Realistically $0–$20. |
| Digital products | Needs an audience to sell to. You're building one, not done. |
| Merch | Needs a recurring character people already love. |
| A viral hit | Not a plan. It's a lottery ticket with someone else's algorithm. |

**Client work is the only path where the outcome is a function of effort you
control.** If 15 contacts produce 1 sale, 45 contacts produce ~3. There is no
algorithm in the loop, no audience requirement, and no waiting for a threshold.
You already own the production capability — this just points it at someone
holding a budget.

`revops pipeline` tracks the funnel and tells you daily whether you're on pace.

---

## The offer

> **A free 5-second animated spot for their product, made *before* they reply.**
> If they want a longer one: **$200, 48-hour turnaround.**

This converts where a normal pitch dies, for three reasons:

1. **It removes imagination.** They aren't evaluating a promise, they're
   watching their own product already animated.
2. **Reciprocity.** You gave first, with no strings. That is rare enough in a
   DM inbox to earn a reply on its own.
3. **It filters instantly.** Someone who watches their product animated and
   feels nothing was never going to buy. You lose them in a day, not a month.

Cost to you: roughly $0.50–$2.00 in credits and ~10 minutes per spec piece.
Forty of them across the week is ~$40–80 — inside your budget.

---

## Who to target

Aim precisely. The aesthetic has to match or the spec piece lands wrong.

### 1. Indie game devs launching in the next 60 days — *best target*
They have a deadline, an allocated marketing budget, and no in-house animator.
A dated launch is the highest-intent signal you can filter on.

- **Steam → Upcoming / Popular Upcoming** (filter by release date)
- **itch.io → newest**, devs posting devlogs
- **r/IndieDev, r/gamedev** — Screenshot Saturday threads
- **X**: `#indiedev` `#screenshotsaturday` `#gamedev`

### 2. Anime & gaming Shopify stores — *exact aesthetic match*
They sell anime products, so anime-style ad creative is not a stretch for
them — it's what they already want. They buy creative continuously and have
revenue to pay from.

- Search Shopify stores in anime apparel, figures, gaming peripherals
- Instagram: brands running ads with obviously static/stock creative

### 3. VTubers and small streamers — *fastest decisions*
Need intros, stingers, "starting soon" screens. Perfect style match, decide in
minutes, but smaller budgets ($100–200).

- Twitch directory, 100–2,000 follower range
- VTuber tags on X

**Do not** pitch anime-style work to plumbing companies, law firms, or generic
local businesses. The style mismatch kills a good offer.

---

## The message

Send the clip **in the first message**. Never ask permission to send it.

```
made this for [Game] — no strings

Hey [Name], been following [Game] since [specific detail you actually noticed].
Made you a 5-second animated spot for it this morning: [link]

Yours to use. Free, no catch, no credit needed.

If a longer one would help for the Steam page or socials, I do those for $200
with a 48h turnaround. Either way, hope the clip is useful.

— Arjan
```

Why each line is there:
- **The specific detail** is the whole message. It proves this isn't a blast.
  If you can't name something real about their product, skip that prospect.
- **"Free, no catch"** pre-empts the suspicion that kills most cold DMs.
- **The price is stated.** No "let's hop on a call." Removing the negotiation
  step is what makes a 48-hour close possible.
- **The offer is a P.S., not the point.** The gift has to read as a gift.

### Follow-ups

Most deals die from silence, not rejection. `revops followups` queues these.

**+3 days:**
```
hey — no worries if the clip wasn't a fit. Just wanted to make sure you saw
it: [link]. Happy to redo it in a different style if it's close but not right.
```

**+7 days (last one, always):**
```
last ping from me — if a trailer ever comes up, I'm around. Good luck with
the launch.
```

Three touches, then stop. A clean exit keeps the door open; a fourth message
closes it permanently.

---

## Day by day

### Day 1 — Setup (2 hours, the only heavy day)

- [ ] Pick **one** segment from above. One. Not three.
- [ ] Build a list of **50 prospects** with a specific detail noted for each
- [ ] Set up a payment link (Stripe payment link or PayPal invoice — 15 min)
- [ ] Cut a **45-second showreel** from your six best existing clips
- [ ] `revops sprint --goal 600 --price 200`

### Days 2–6 — The engine (~95 min/day)

```
20 min   source 6 prospects, note a real detail on each   → revops lead add
30 min   batch-generate 6 spec clips (queue them together)→ revops lead set N spec_made
30 min   send 6 personalised messages                     → revops lead set N contacted
15 min   follow-ups + log replies                         → revops followups
```

Run `revops pipeline` at the start of each day. It tells you whether you're on
pace and how many contacts today needs.

### Day 7 — Close

- [ ] Final follow-up to everyone who hasn't replied
- [ ] Deliver anything sold (48h turnaround starts on payment)
- [ ] Ask every paying client for a one-line testimonial. This is worth more
      than the fee — it's what lets you charge $400 next week.
- [ ] `revops pipeline` → check which segment converted, aim there next week

---

## Pricing

| When | Price | Why |
|---|---|---|
| First 3 clients | **$150–200** | You're buying testimonials, not maximising rate |
| After 3 testimonials | **$400** | Proof lets you double |
| Rush (<24h) | **+50%** | Deadline pressure is worth real money to them |

Take payment **on delivery** for anything under $300 — asking for a deposit
adds a step and costs you more in lost deals than it saves in risk. Above
$300, 50% upfront.

---

## Honest expectations

Running the full 40+ contacts:

- **~10 replies**, **2–3 closes** at $200 → **$400–$600**
- Probability of at least one sale: **roughly 75–85%**
- Probability of zero: **roughly 15–25%** — real, and usually means the
  targeting or the spec quality was off, not that the model is wrong

The single biggest predictor is **volume actually sent**. Nearly everyone who
fails at this fails by sending 8 messages instead of 40, then concluding it
doesn't work.

---

## What goes wrong, and the fix

| Symptom | Diagnosis | Fix |
|---|---|---|
| 20+ sent, 0 replies | The spec clips are generic or the detail is fake | Make the clip *about their specific product*, not a generic anime loop |
| Replies but no closes | Price ambiguity or too many steps | State price and turnaround in message one. Never propose a call. |
| "Looks great!" then silence | No deadline | "I've got a slot open Thursday — want it?" |
| Can't find 6/day | Segment too narrow | Widen to the next segment on the list |
| Clips take >15 min each | Over-polishing a freebie | It's a 5-second teaser. Ship rough. |

---

## After day 7

If you closed anything, you've proved the machine works and you have a
testimonial. Then:

1. Raise the price to $400
2. Reinvest one fee into credits — volume is the input to everything
3. Go back to `docs/PLAYBOOK.md` Phase 2: the same clients buy repeat work, and
   repeat clients are where this stops being a sprint and becomes a business
