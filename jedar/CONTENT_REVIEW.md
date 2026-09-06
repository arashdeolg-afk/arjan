# Content review for Jedar AI

Daily content shown in the Today screen comes only from `server/content/reflections.json`.
The language model never writes daily content and never adds scripture on its own.
This document explains how to add content and who must review it.

## Two kinds of records

| type | What it is | Who may approve | Label shown to users |
| --- | --- | --- | --- |
| `reflection` | An original, plain-language thought written for Jedar. Never a quotation, verse, paraphrase, or translation of sacred text. | Editorial review, ideally with a faith advisor | **Reflection** |
| `scripture` | A verbatim passage from a recognised sacred text in a stated translation, with an exact reference. | A qualified representative of that faith (see below) | **Scripture** (only when approved) |

Rules enforced by the server at startup (`server/src/content.ts`):

- Any record with `approved: false` is treated as a `reflection`, whatever its `type` says, and its
  `sourceName` and `reference` are dropped. It can never be displayed as scripture.
- An approved `scripture` record **must** have `sourceName`, `reference`, and `reviewedBy`. If any
  is missing the server refuses to start, so a mistake cannot reach users.
- A `reflection` record may not carry `sourceName` or `reference`, so an ordinary reflection can
  never be dressed up to look like scripture.
- IDs must be unique and look like `faith-001`.

## Record schema

```ts
type DailyContent = {
  id: string;                          // e.g. "sikh-001", lowercase, unique
  faith: "sikh" | "muslim" | "christian" | "hindu" | "jewish";
  type: "reflection" | "scripture";
  title: string;                       // up to 120 characters
  body: string;                        // up to 1200 characters
  approved: boolean;
  sourceName?: string;                 // scripture only: text and translation
  reference?: string;                  // scripture only: exact location
  reviewedBy?: string;                 // scripture only: reviewer role and date
};
```

The file has this shape:

```json
{ "version": 1, "note": "…", "items": [ { …DailyContent } ] }
```

## Adding a reflection

1. Write an original reflection of two to four short sentences. Warm, plain, and non-directive.
   It may mention concepts (seva, sabr, grace, dharma, chesed) but must not quote, paraphrase,
   or allude to a specific verse, and must not state religious law.
2. Do not write "as scripture says" or similar framings.
3. Add it with `type: "reflection"` and `approved: false`.
4. Have at least one editor and, where possible, a member of that faith community read it for
   tone, accuracy of vocabulary, and respect. Set `approved: true` only after that review.
   Approval does not change how reflections display; it records that the review happened.
5. Run the server tests: `cd server && npm test`.

## Adding scripture

Scripture is shown with its source and reference, so the bar is higher. Do not add scripture
until every step is complete.

1. **Choose the text and a translation you have the right to use.** Many translations are
   copyrighted. Record the translation name in `sourceName` (for example, the name of the
   published translation and edition).
2. **Copy the passage verbatim.** No trimming that changes meaning, no blending of translations,
   no added words.
3. **Record the exact reference** in the tradition's own citation style in `reference`.
4. **Arrange review by a qualified representative** of that faith. Suggested reviewers:
   - Sikh: a granthi or a scholar of Gurbani associated with a gurdwara or Sikh studies program.
   - Muslim: an imam or a scholar with recognised training in Quran and hadith sciences.
   - Christian: an ordained minister, priest, or a scholar of biblical studies; note the
     denomination consulted, since canons and translations differ.
   - Hindu: a priest, acharya, or a scholar of the specific text and tradition; note the tradition.
   - Jewish: a rabbi or a scholar of Torah and rabbinic literature; note the movement consulted.
   The reviewer checks the passage is accurate, the reference is correct, the translation is
   acceptable, and that showing it alone, without context, will not mislead.
5. Fill `reviewedBy` with the reviewer's role and the review date, for example
   `"Rabbi (Conservative), reviewed 2026-09-01"`. Do not include private contact details.
6. Set `approved: true` and `type: "scripture"`.
7. Run `cd server && npm test`. The tests confirm that approved scripture carries its source,
   reference, and review status.

## What not to add

- Invented verses, "inspired by" verses, or model-generated scripture of any kind.
- Passages whose accuracy or translation rights you cannot confirm.
- Rulings, legal opinions, or statements that one interpretation is correct.
- Content that assumes all followers of a faith believe the same thing.
- Anything that would be inappropriate on a lock screen or read aloud in public.

## Review cadence

Re-review scripture whenever the translation, reference, or reviewer changes. Re-read all
reflections at least once a year with a faith advisor. Remove anything that receives credible
community complaints while it is investigated; removal only needs `approved: false` (for
scripture, which then downgrades to a plain reflection) or deleting the record.
