# Architecture

## Pipeline

```mermaid
flowchart TB
    subgraph IN["INPUTS — all public disclosure, no MNPI"]
        direction LR
        F13["SEC Form 13F-HR<br/><i>information table XML</i>"]
        TX["Earnings call transcript<br/><i>licensed API or manual import</i>"]
    end

    subgraph CFG["CONFIG — analyst-editable, no retraining"]
        direction LR
        PORT["<b>portfolio.yaml</b><br/>holdings · tier · indications<br/>mechanisms · catalysts"]
        MAT["<b>materiality.yaml</b><br/>type weights · multipliers<br/>alert threshold"]
        ALI["<b>aliases.yaml</b><br/>asset · indication<br/>mechanism identity"]
    end

    F13 -->|"<b>ingest_13f.py</b><br/>rank by weight, not value"| PORT

    TX --> PARSE["<b>parse.py</b><br/>speaker tags · role<br/>prepared vs Q&A split"]
    PARSE --> PASS[("Passages<br/><i>speaker · role · section</i>")]

    PASS --> EXT
    PORT -.->|"portfolio context<br/>injected into prompt"| EXT

    EXT["<b>extract.py</b> + <b>extract_claims.md</b><br/>━━━━━━━━━━━━━━<br/>MODEL: claude-sonnet-4-6<br/>━━━━━━━━━━━━━━<br/>claim · quote · type · linkage<br/>entities · materiality 0–1"]

    EXT --> VAL{"<b>validate</b><br/>quote verbatim in source?<br/>passage index real?"}
    VAL -->|fail| DROP["discarded<br/><i>hallucination guard</i>"]
    VAL -->|pass| CLAIMS[("Claims")]

    CLAIMS --> DIFF["<b>diff.py</b><br/>vs prior quarter<br/>entity-matched via aliases"]
    PRIOR[("Prior quarter<br/>claims cache")] --> DIFF
    ALI -.-> DIFF
    DIFF --> NOV["novelty: new / changed / repeated<br/>+ hedging appeared<br/>+ programmes gone quiet"]

    NOV --> SCORE["<b>score.py</b><br/>materiality × type × section<br/>× linkage × novelty × tier"]
    MAT -.-> SCORE

    SCORE --> PART{"<b>partition</b>"}
    PART -->|"score ≥ 1.10<br/>max 5 per call"| ALERT["<b>Needs an analyst</b>"]
    PART -->|"0.55 – 1.10"| WATCH["Context"]
    PART -->|"< 0.55"| ARCH["Archived<br/><i>retained, not deleted</i>"]

    ALERT --> RPT["<b>report.py</b> → digest.md<br/>email / Slack before the open"]
    WATCH --> RPT
    ARCH -.->|"recoverable for<br/>threshold retuning"| RPT

    CLAIMS --> PRIOR

    classDef input fill:#e8f0fe,stroke:#4285f4,stroke-width:1px,color:#111
    classDef cfg fill:#fef7e0,stroke:#f4b400,stroke-width:1px,color:#111
    classDef model fill:#e6f4ea,stroke:#0f9d58,stroke-width:2px,color:#111
    classDef out fill:#fce8e6,stroke:#db4437,stroke-width:1px,color:#111
    classDef drop fill:#f1f3f4,stroke:#9aa0a6,stroke-dasharray:3 3,color:#555

    class F13,TX input
    class PORT,MAT,ALI cfg
    class EXT model
    class ALERT,RPT out
    class DROP,ARCH drop
```

## Where the judgment lives

The model does one job: read passages and emit structured claims with a
materiality score for each claim **in isolation**. It is not asked to rank, to
compare quarters, or to decide what interrupts an analyst.

Everything downstream of the model is deterministic and config-driven:

| Stage | Deterministic? | Why it sits outside the model |
|---|---|---|
| Section weighting | yes | Prepared vs Q&A is a structural fact, not a judgment call |
| Novelty | yes | Requires the prior quarter, which the model never sees |
| Linkage strength | yes | Follows from `portfolio.yaml`, which an analyst owns |
| Ranking | yes | An analyst who disagrees must be able to change one YAML line |

This is the difference between a system a research team adopts and one they
argue with. A tuned end-to-end model that produces a ranking nobody can
interrogate does not get used, however good its AUC.

## The precision / recall split

The brief states two things that pull against each other: the team **misses**
signals, and not every mention is worth **interrupting** an analyst over. One
threshold cannot serve both.

```mermaid
flowchart LR
    A["Passages"] --> B["<b>Extract</b><br/>run LIBERALLY<br/><i>capture anything plausible</i>"]
    B --> C["<b>Score + rank</b><br/>deterministic"]
    C --> D["<b>Alert</b><br/>run CONSERVATIVELY<br/><i>only high conviction</i>"]
    C --> E["Watch + Archive<br/><i>nothing deleted</i>"]
    E -.->|"recover missed signals<br/>→ retune thresholds"| C

    classDef lib fill:#e6f4ea,stroke:#0f9d58,color:#111
    classDef con fill:#fce8e6,stroke:#db4437,color:#111
    class B lib
    class D con
```

Over-capture is cheap; a missed competitive signal on a binary readout is not.
So extraction is generous and alerting is strict, and the gap between them stays
on disk rather than being thrown away — which is the only honest way to approach
recall when there is no labelled ground truth.

Measured on the labelled set at the configured threshold: **precision 0.71,
recall 1.00**. Raising the threshold to 1.60 gives precision 1.00 at recall 0.80.
That is one line in `config/materiality.yaml`.

## Data boundaries

```mermaid
flowchart LR
    subgraph COMMIT["Committed to the repo"]
        direction TB
        C1["config/ · prompts/ · src/"]
        C2["data/replay/<br/><i>cached extraction output</i>"]
        C3["eval/labeled_set.csv"]
        C4["data/13f/<br/><i>abridged fixture</i>"]
    end

    subgraph LOCAL["Local only — gitignored"]
        direction TB
        L1["data/transcripts/<br/><i>licensed content</i>"]
        L2["data/raw/<br/><i>saved source pages</i>"]
        L3["out/claims/<br/><i>run cache</i>"]
    end

    classDef ok fill:#e6f4ea,stroke:#0f9d58,color:#111
    classDef no fill:#fef7e0,stroke:#f4b400,color:#111
    class C1,C2,C3,C4 ok
    class L1,L2,L3 no
```

Transcript text is never committed. What ships is *extraction output* — claims
with short verbatim quotes for audit — which is why `make demo` runs with no
API key, no network, and no licensed content in the repository.
