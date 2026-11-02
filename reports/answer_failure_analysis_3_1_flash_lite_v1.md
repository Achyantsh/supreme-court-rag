# Answer-Failure Analysis: Gemini 3.1 Flash-Lite

## Scope and method

This analysis uses only the persisted Gemini 3.1 Flash-Lite answer records and
the human labels in:

- `data/answer_evaluation_3_1_flash_lite_v1.jsonl`
- `data/answer_review_3_1_flash_lite_v1.xlsx`

The 30 questions all generated successfully, use
`gemini-3.1-flash-lite`, and contain five persisted Hybrid RRF evidence
passages. Human labels were not changed. The analysis treats a low score as a
triage signal, not proof by itself: each issue below is included only where the
review note and the answer/evidence comparison identify a concrete claim,
citation, or omission.

The workbook's low-score inventory is:

- Correctness <= 1: 13 answers
- Citation support <= 1: 18 answers
- Completeness <= 1: 15 answers
- At least one score <= 1: 23 answers

## Verified failure patterns

### 1. The answer addresses a neighboring question or omits the requested test

This is the most repeated completeness problem.

- **H07 — notice to appear versus arrest:** The answer says the extracts “do
  not explicitly detail the procedural mechanism of a ‘notice to appear’,”
  then answers when arrest may be unnecessary using *Md. Asfak Alam*. The
  retrieved *Choodamani* passage mentions Sections 41 and 41A and says arrest
  after a notice can still occur for recorded reasons, but the answer does not
  use that passage to state the actual notice/arrest relationship. It instead
  presents the quoted UK Criminal Law Act passage in *Priya Indoria* as an
  Indian-law rule.
- **H16 — delay in a corruption trial:** The answer discusses delay in lodging
  an FIR, delayed ED registration, a stay of trial, and civil laches. Its own
  cited passages support those statements, but they do not answer the asked
  question about delay during a corruption trial and relief under speedy-trial
  or Article 21 principles.
- **H22 — movement restrictions during criminal proceedings:** The answer
  gives general statutory-law and proportionality principles, but does not
  address bail or anticipatory-bail travel/location restrictions. It also
  says restrictions must fit Article 19(2), while the movement provision is
  Article 19(5); the cited *Kaushal Kishor* passage concerns free speech.
- **H26 — excessive pre-trial incarceration:** The answer correctly abstains
  from claiming the retrieved set contains the requested test, but then
  discusses post-conviction premature release, suspension of sentence, and
  default bail. Those excerpts support what is said, but do not answer the
  pre-trial question. The review specifically notes that a relevant
  excessive-delay/pre-trial passage was not in this question's retrieved top
  five.
- **H30 — jurisdictional defect versus curable irregularity:** The answer
  discusses failure-of-justice, arbitration-record irregularity, review
  jurisdiction, and the Supreme Court's inherent power. It never gives the
  requested jurisdictional-defect/nullity versus Sections 460–465 CrPC
  distinction. The cited passages are individually supported but not
  responsive.
- **H18 — unexplained delay in deciding a preventive-detention
  representation:** The answer says “earliest opportunity” and “anxious
  care,” but omits the operative assessment that each day's delay must be
  explained and that unexplained delay can vitiate continued detention.

### 2. A cited passage is not the holding attributed to the Supreme Court

The answer frequently turns quoted submissions, lower-court reasoning, or
foreign-law background into a Supreme Court holding.

- **H01:** The answer says the Court “held” that custodial interrogation was
  a “must” and release was at a “premature stage.” The retrieved *Santosh
  Karnani* excerpt contains that language in the quoted Special Judge's
  reasoning, not necessarily the Supreme Court's own holding. The answer also
  uses *Teesta Atul Setalvad*, a regular/interim-bail context, as if it were a
  direct Section 438 rule.
- **H08:** The answer calls custodial interrogation “qualitatively more
  elicitation-oriented” based on the *Santosh Karnani* excerpt. The review
  identifies this as the CBI's submission citing *Anil Sharma*, not a Court
  observation. The answer then pivots from arbitrary detention to preventive
  detention authorities.
- **H09:** The answer uses an *A. Sreenivasa Reddy* High Court order quoted in
  the judgment and an *Aryan Singh* passage containing the ASG's submissions
  as Supreme Court ratio. The directly supported portions were the civil-
  dispute and no-mini-trial principles.
- **H10:** The answer generalizes *Dilipsinh* language about a revisional court
  reviewing a discharge application into a general quashing rule. It also
  uses the *Aryan Singh* counsel-submission excerpt as if it were the Court's
  holding.
- **H13:** The answer attributes the Section 20 presumption point to
  *Sarangapani*, although the retrieved excerpt presents it as counsel's
  submission that the Court rejected. The legal proposition is supported by
  *Neeraj Dutta*, but the adjacent citation is wrong for that claim.
- **H20:** The answer says the Court held that blind reliance on a police
  proposal and a maximum 12-month detention without reasons vitiate the
  order. The retrieved *Pesala Nookaraju* passages are numbered as the
  petitioner's submissions (“Without prejudice... the Petitioner”), not the
  Court's holding. A more relevant *Ameena Begum* passage was retrieved but
  not used.
- **H27:** The answer presents the *Rajpal* High Court reasoning about checking
  whether a co-accused's bail violated *Mohit Aggarwal* as a Supreme Court
  rule, although the Supreme Court expressly said it did not need to decide
  that issue in the withdrawn-SLP order.

### 3. Context-specific law is generalized beyond the retrieved authority

- **H05 — arrest memo:** The answer explicitly admits that arrest-memo
  contents are not in the extracts, but presents PMLA Section 19 duties from
  *Ram Kishor Arora* as general arrest duties. The passage is PMLA-specific.
  The “written grounds as a matter of course, without exception” formulation
  is attributed to *Ram Kishor Arora* even though the excerpt ends before the
  quoted *Pankaj Bansal* holding. *Mukesh Singh* on test identification is
  irrelevant to arrest-memo preparation.
- **H06 — statutory arrest safeguards:** The answer says non-compliance
  “entitles the arrestee to be released,” which is supported for PMLA
  Section 19 by *Pankaj Bansal*, but adds that the Court can initiate action
  against authorities without that proposition appearing in the retrieved
  excerpt. It also does not plainly state the requested consequence for
  subsequent custody: the safeguard failure makes the arrest/remand
  consequence unlawful or requires release under the applicable statute.
- **H19 — public order:** The answer's public-order distinction is mostly
  supported by *Pesala*, but the “absence of insurrection, riot, turbulence
  or crimes of violence” wording is from the *Arup Bhuyan* passage, not the
  *Pesala* passage cited beside it. This is a citation-to-claim mismatch,
  even though the overall proposition is supported somewhere in retrieval.
- **H24 — fair hearing:** *Raj Kumar* and *Sunil* support the Section 313
  and curable-irregularity points. However, the answer uses disciplinary-
  inquiry and death-reference authorities to support a broader claim that
  sealed-cover reliance is inconsistent with a fair hearing; that conclusion
  is not visible in the cited *Madhyamam* excerpt.

### 4. Unsupported or off-topic additions reduce precision

- **H03 — alleged misuse of earlier protection:** The question asks about
  misuse/cancellation. The answer cites *Ms. X* on a previously rejected
  bail application, which is not misuse of an earlier protection, and cites
  fixed-duration/event conditions not visible in that excerpt. *Ramesh
  Kumar*'s point about payment undertakings is supported but off-topic.
  *Asfak Alam*'s no-blanket/no-future-offence point is the relevant supported
  portion.
- **H04 — cooperation:** The answer says custodial interrogation can prevail
  “regardless of cooperation.” The *Pratibha Manchanda* and *Santosh
  Karnani* excerpts support a case-specific need for custodial interrogation,
  but do not establish that categorical override. The answer also omits the
  adverse effect of actual non-cooperation shown in the *Karnani* material.
- **H02 — fixed duration/event:** The core rule and factors are supported by
  *Md. Asfak Alam*, *Ramesh Kumar*, and *Priya Indoria*. The cited *Ms. X*
  excerpt only shows the constitutional-bench questions about duration; it
  does not show the answer, so that citation is unverified from the persisted
  excerpt.

### 5. Correct abstention or supported claims still failed the question's
### completeness target

Not every low score indicates hallucination.

- **H23:** All five cited claims are supported by their excerpts, but only
  *Ranjan Kumar Chadha* is a criminal-procedure authority; the answer does
  not discuss discretion in bail, arrest, remand, or prosecution as asked.
- **H26:** The abstention is appropriately cautious and its replacement
  descriptions are supported, but it does not answer the requested
  pre-trial test.
- **H16 and H30:** The cited statements are supported by their excerpts, but
  the answers are materially non-responsive to the questions.

## Lowest-scoring cases

The most severe observed case is **H11 (0/1/1)**. The answer's central
conclusion says that quashing on settlement is “strictly contingent on the
offence being compoundable.” The review identifies this as wrong or
misleading because High Courts can quash some non-compoundable offences under
Section 482 subject to seriousness and public-interest limits. The sole cited
*Hemalatha Devi* excerpt is about arbitration/non-arbitrability and does not
support that settlement-quashing conclusion.

Other three-dimensional low cases are **H01, H03, H04, H05, H07, H08, H18**,
each scored 1/1/1. Their concrete issues are respectively: context mismatch
and attribution, misuse versus rejected bail conflation, an unsupported
“regardless of cooperation” inference, PMLA/general-arrest overgeneralizing,
failure to answer the notice mechanism, preventive-detention pivot and
submission attribution, and omission/misapplication of the delay test.

## Minimal recommended changes

These are recommendations only; no implementation was made in this task.

### 1. Make the prompt claim-local and evidence-closed

Require each material proposition to be emitted as a structured unit:

```text
Claim:
Supporting retrieved source: exact doc_id, case_name, citation, rank
Evidence excerpt: a short verbatim span
Qualification/context: statute, procedural posture, and whether the passage
is a holding, submission, quoted lower-court reasoning, or background law
```

If no retrieved passage supports the requested issue, require a concise
abstention instead of answering a neighboring question. Require the answer to
say when the retrieved authorities are only analogous or context-specific.

### 2. Add deterministic citation validation after generation

Before returning an answer:

1. Extract every cited case/citation.
2. Require an exact match to one of the retrieved `(case_name, citation,
   doc_id)` records; otherwise mark the citation unresolved.
3. Require each citation to be attached to a claim whose supporting excerpt
   contains a mapped evidence span.
4. Reject or rewrite citations that are not in retrieved metadata. Never
   silently replace them with a different case.
5. Preserve source rank and `doc_id` in the returned citation object.

This would catch the *Ms. X*, *Sarangapani*, *Rajpal*, *Aryan Singh*, and
*Pesala* attribution problems, but it cannot by itself determine whether a
passage is a submission or holding.

### 3. Add passage-role and procedural-context metadata

At ingestion or evidence preparation time, identify paragraph/source roles
where available: Supreme Court holding, quoted lower-court order, party
submission, headnote, statute, foreign-law background, and procedural posture.
The prompt should prohibit using submissions or background passages as
holdings and should require statute-specific qualifications such as PMLA
Section 19.

### 4. Add a question-relevance gate

Before synthesis, require the model to list the requested legal elements and
mark each as supported, partially supported, or absent in the retrieved
passages. If a requested element is absent, the answer should state that
limitation rather than fill the gap with a neighboring topic. This directly
targets H07, H16, H22, H26, and H30.

### 5. Keep human review separate from automated checks

The existing human labels should remain unchanged. A future validation layer
can report citation exact-match rate, claim-to-evidence coverage, and
off-topic/abstention flags separately. Those checks must not be presented as
new human correctness labels or as proof of general legal faithfulness.

## Limitations

This is a failure analysis of one 30-question held-out run and its reviewer
notes. It does not establish general legal accuracy, and it does not infer
errors from low scores alone. No Gemini call, retrieval call, label update,
metric update, prompt change, or application change was made.

