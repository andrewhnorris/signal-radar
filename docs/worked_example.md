# Worked example: the signal that justifies the system

*Structured for reuse in a readout deck. One idea per section; each maps to a slide.*

---

## Slide 1 — The setup

RTW's disclosed book holds **both sides of a competitive pair**:

| | | |
|---|---|---|
| **MDGL** — Madrigal | Largest disclosed position | Rezdiffra (resmetirom), THR-beta, approved in F2–F3 MASH |
| **IVA** — Inventiva | New position, initiated Q1 2026 | Lanifibranor, pan-PPAR, Phase 3 NATiV3, **topline H2 2026** |

Same indication. Same patient segment. Opposite sides of the trade.

---

## Slide 2 — What happened on the call

On **30 July 2026**, Madrigal's Q2 earnings call ran for an hour. An analyst asked, near the end of Q&A, about competitive impact if a rival Phase 3 succeeds.

The CEO's answer included proprietary market research:

> 80% of prescribers said they wouldn't use lanifibranor because of the weight gain

He also characterised the asset as a 1,200mg pill, a PPAR associated with weight gain and edema, positioned against a market "obsessed with weight loss."

**This is a portfolio company publishing its launch playbook against another portfolio company, weeks before that company's binary readout.**

---

## Slide 3 — Why it is not noise

The claim survives scrutiny. Inventiva's own disclosure puts weight gain at roughly **30% of patients gaining 5% or more**, and management has discussed mitigating it with an SGLT2 combination.

So the attack has a factual anchor. It is not spin — it is the commercial bar lanifibranor has to clear *even if NATiV3 succeeds on histology*.

That distinction — positive data is necessary but not sufficient — is exactly the kind of judgment the brief asks for.

---

## Slide 4 — Three more signals in the same hour

| Signal | Type | Why it matters |
|---|---|---|
| CMO: rivals "maybe not seeing as robust accrual of events" | Clinical | Competitor trial-operations health is normally invisible from outside |
| CMO: "we haven't actually confirmed the target number of events" | Timeline | Event count sets trial duration; refusing to confirm it widens the F4c readout window both ways |
| CEO volunteers a semaglutide critique **unasked** | Competitive | No analyst raised it. Volunteering a rebuttal suggests GLP-1 pressure is felt in the field despite reported numbers showing none |

Four material signals. One call. **None of them findable by searching for a drug name.**

---

## Slide 5 — The case for automation

An analyst covering MDGL was on this call and heard the lanifibranor comment. The question is whether the analyst covering **IVA** heard it.

At ~60 competitor calls a quarter, clustered into a three-week window, cross-coverage is where signals are lost. Not because anyone is careless — because the material comment arrives 52 minutes into someone else's call.

**Cost to monitor the full competitor universe: roughly $30 of inference per quarter.**

---

## Slide 6 — What a static competitor list would have missed

In **October 2025**, Novo Nordisk agreed to acquire **Akero Therapeutics** for up to $5.2B. Akero's efruxifermin (FGF21) was MDGL's closest mechanism rival. RTW exited AKRO.

The competitor did not disappear. It **moved inside a mega-cap** whose earnings call is dominated by obesity and diabetes.

MASH commentary that used to arrive on a focused 40-minute biotech call now arrives as two sentences inside a Novo Nordisk call. A ticker-based watchlist stops working the moment a competitor is acquired.

**This is why linkage is evaluated on mechanism and indication, not company name.**

In the shipped demo the Novo Nordisk call surfaces two MASH claims and the efruxifermin one reaches MDGL on `shared_mechanism` alone — the call never says "Madrigal". It scores 1.035, just under the 1.10 alert bar, so it lands in Context rather than interrupting anyone. That is the right outcome for a single mention with no prior quarter to compare against, and it is the difference between finding something and shouting about it.

---

## Slide 7 — Terminology, from the actual transcripts

Five failure modes for naive keyword matching, all observed in the sample:

1. **MASH and NASH are the same disease** — used interchangeably within a single call, sometimes in adjacent sentences.
2. **Brand vs INN** — rivals say "resmetirom", the owner says "Rezdiffra". Both must match.
3. **ASR errors** — one vendor renders "hepatologists and GIs" as **"Hepatitis C and GIs"**. A keyword rule files a liver-disease comment under infectious disease.
4. **Vendor disagreement** — the same call, transcribed by two vendors, gives the CMO **two different names**. One renders the company as "Magical Pharmaceuticals".
5. **Broken speaker separation** — in the Inventiva transcript the operator is labelled as an analyst with a numeric suffix, and one name is reused for several speakers. Left unhandled, the parser silently merges those lines into the previous speaker's turn, corrupting exactly the quote provenance the system depends on.

And one that is not a terminology problem at all but breaks coverage the same way: **Inventiva reports semi-annually**, not quarterly. A scheduler expecting four calls a year per name under-covers every European holding and reports full coverage while doing it.

Transcripts are dirty. Any design that assumes clean entity strings breaks on contact.

---

## Slide 8 — What the system does with this

```
Needs an analyst

### IVA

1. IVA, MDGL — Madrigal cited research claiming 80% of prescribers
   would not use lanifibranor because of weight gain.

   Competitive · score 2.20 · named asset · NEW

   > 80% of prescribers said they wouldn't use lanifibranor
     because of the weight gain
   — Bill Sibold, Madrigal Q2 2026, Q&A [passage 47]

   Why it matters: A direct, quantified attack on IVA's only asset
   weeks before its Phase 3 topline...
```

Grouped by the holding at risk, because an analyst reads by coverage, not by score.

Speaker, section, verbatim quote, passage index. **An analyst can verify it in one click or ignore it in five seconds.** Both outcomes are acceptable; an unverifiable summary is not.

---

## Slide 9 — Honest limitations

- **Only one call here is a parsed transcript.** Madrigal Q2 2026. The MDGL Q1 baseline and the IVA and NVO calls are reconstructed from published disclosure, so they exercise the diff and cross-company linkage but carry no verified verbatim span. The digest labels them `reconstructed` rather than citing a passage index, and they are excluded from the eval set.
- **Eval is 20 hand-labelled rows on one company.** It measures whether ranking puts the right things on top. It does not measure whether extraction found everything — that is the recall question, and it is unanswered.
- **Two false positives remain at the configured threshold**, both defensible-but-below-bar: a repeated timeline guide and a business-development payment. `run_eval.py` names them with the labelling rationale.
- **A third was found and fixed during the build**: Q1 called the Arrowhead asset `ARO-PNPLA3`; Q2 calls it `MGL-0795` after in-licensing, and the "went quiet" detector reported a renamed asset as a dropped programme. `config/aliases.yaml` now resolves programme identity before comparison. The map is hand-maintained and will be incomplete on names outside the sample.
- **No causal claim.** Price moves after a flagged signal are confounded by everything else in the quarter. This deck asserts the signals are material on their merits, not that they were tradeable.

---

## Sources

All public disclosure. No MNPI, no expert networks.

- RTW Investments LP Form 13F-HR, SEC CIK 0001493215
- Madrigal Pharmaceuticals Q2 2026 earnings call, 30 July 2026
- Inventiva NATiV3 Phase 3 disclosures and management commentary, 2025–2026
- Novo Nordisk / Akero Therapeutics acquisition announcement, 9 October 2025
