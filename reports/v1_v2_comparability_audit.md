# V1 vs V2 comparability audit

Audited UTC: 2026-11-02T05:44:00.329953+00:00

## Conclusion

**Comparable for a paired descriptive DEVELOPMENT comparison on the recorded inputs.** No question, topic, model, retrieval configuration, SDK or retrieval-evidence differences were found. This is not proof of a prompt-only causal effect.

## All-record checks

- Both JSONL files contain exactly H01–H30, once each (30 records per run).
- Every record and answer response identifies `gemini-3.1-flash-lite`.
- Every record has successful generation, a non-empty answer and no generation error.
- V1 recorded settings: [('hybrid_rrf', 5)].
- V2 recorded settings: [('hybrid_rrf', 5)].
- Entire retrieval-response objects were compared exactly via canonical JSON hashes: ordered ranks, doc IDs, chunk IDs, excerpts, case names, SCR citations, decision dates, PDF names, scores, result modes and response envelopes. Object key order is immaterial; list order and excerpt whitespace are preserved.
- Each run's supplied citation metadata/previews were checked against its retrieval results. All V2 S1–S5 identity/rank mappings were checked; this is not semantic support verification.
- V1 answer-version tags are absent in the legacy records: V1 is inferred from baseline provenance and schema, not a frozen historical prompt/hash. Both V2 version tags are explicit.
- Both original workbooks have exact H01–H30 coverage and their questions, topics, answers, models, statuses, supplied citations, document-ID lists and evidence projections match JSONL.
- V1 workbook missing/invalid labels: 0/90.
- Existing V2 development workbook missing/invalid labels: 90/90.
- Original workbook evidence columns retain doc_id, case_name, citation and excerpt only; the new workbook adds a Sources sheet with full persisted retrieval metadata.

## Run provenance

- V1 run timestamps: 2026-10-27T15:08:24.448249+00:00, 2026-10-28T11:13:41.180310+00:00
- V1 SDK metadata: `{"google-genai": "2.33.0"}`.
- V2 run timestamps: 2026-10-28T11:46:45.186055+00:00
- V2 SDK metadata: `{"google-genai": "2.33.0"}`.

## Per-question evidence comparison

| Question | Exact retrieval equality | V1 evidence SHA-256 | V2 evidence SHA-256 |
|---|---|---|---|
| H01 | True | `8861ebf6d76a44f0f946aa349051b742db62bd7a09eeaafb8ae546c7ac6ae494` | `8861ebf6d76a44f0f946aa349051b742db62bd7a09eeaafb8ae546c7ac6ae494` |
| H02 | True | `706a0b772800f77eae6886c77d4539c7d1e45b3ad700c52dc9746cddf153a9e1` | `706a0b772800f77eae6886c77d4539c7d1e45b3ad700c52dc9746cddf153a9e1` |
| H03 | True | `30f9046f1dc482a2f5e98bc07084c290c0de4b0f18bcc9605957f4bc555df2da` | `30f9046f1dc482a2f5e98bc07084c290c0de4b0f18bcc9605957f4bc555df2da` |
| H04 | True | `89f50824d09efc4fa5b6bb8e25892e732156bf71d60992fb4c131b36dcb34930` | `89f50824d09efc4fa5b6bb8e25892e732156bf71d60992fb4c131b36dcb34930` |
| H05 | True | `0be55bb24405a7c4413cc3147c9c0538ef9625582b566fa88f4add8557659003` | `0be55bb24405a7c4413cc3147c9c0538ef9625582b566fa88f4add8557659003` |
| H06 | True | `cf5a1c50af6f4be19f73de4f705c2268a74ed18a647302125f89dda046b8527e` | `cf5a1c50af6f4be19f73de4f705c2268a74ed18a647302125f89dda046b8527e` |
| H07 | True | `0578cbfadd085b2dfdaf7efcaede05a84ef309132ec44a46e0c913d51137b89d` | `0578cbfadd085b2dfdaf7efcaede05a84ef309132ec44a46e0c913d51137b89d` |
| H08 | True | `7c7391b707f01d036bfe6de689ee92abb5ebeb017c9451b17e6e15698259dd57` | `7c7391b707f01d036bfe6de689ee92abb5ebeb017c9451b17e6e15698259dd57` |
| H09 | True | `0540c09a37e7edf5800ad3348206b0dc23fadc82a5dc6c7dd8637e5d7b30be15` | `0540c09a37e7edf5800ad3348206b0dc23fadc82a5dc6c7dd8637e5d7b30be15` |
| H10 | True | `e3f8f2d85615742659675103a659d006f761a225d337c50ec43e00899ff056b5` | `e3f8f2d85615742659675103a659d006f761a225d337c50ec43e00899ff056b5` |
| H11 | True | `05cb5358aac1f8187bff400e8b4bf3503cee5b5dd499550b944358fd0fb19808` | `05cb5358aac1f8187bff400e8b4bf3503cee5b5dd499550b944358fd0fb19808` |
| H12 | True | `6ca90323265ef8aa48392fce10911d9a1eb165435cf226818aca4dc4f0d4041d` | `6ca90323265ef8aa48392fce10911d9a1eb165435cf226818aca4dc4f0d4041d` |
| H13 | True | `8b50f64735579f9691eb7e769aebacdb260e58f0771f487a8c0c639434fe0704` | `8b50f64735579f9691eb7e769aebacdb260e58f0771f487a8c0c639434fe0704` |
| H14 | True | `8f757b9505020e0667082064f810a2110d4350fc4395168bf834025554868773` | `8f757b9505020e0667082064f810a2110d4350fc4395168bf834025554868773` |
| H15 | True | `63873a626442b6a2559c7d91020cc7076f51a50abd1ef7936406625b1bcc9c10` | `63873a626442b6a2559c7d91020cc7076f51a50abd1ef7936406625b1bcc9c10` |
| H16 | True | `3600d72cd9745ae1a943bb72f2b7ce4d67d2bbdf23fb3ed6184799296e8e7fc2` | `3600d72cd9745ae1a943bb72f2b7ce4d67d2bbdf23fb3ed6184799296e8e7fc2` |
| H17 | True | `c9dcabb23dd4891fad0179e1b732711ce4aaeb0db1c8bf3ba3ec1401acabbfa1` | `c9dcabb23dd4891fad0179e1b732711ce4aaeb0db1c8bf3ba3ec1401acabbfa1` |
| H18 | True | `75e8e6053060262a90db82be09d9279f94b0f50c19b8db85ae0474f333aa6f5f` | `75e8e6053060262a90db82be09d9279f94b0f50c19b8db85ae0474f333aa6f5f` |
| H19 | True | `1081bc02d90b7bb2979757b63110f7180fb684fa02da11f08023ff9d25446a1a` | `1081bc02d90b7bb2979757b63110f7180fb684fa02da11f08023ff9d25446a1a` |
| H20 | True | `afb01162f9ef46cd6ca6b21e623bb894276778be46c53de979761978f72f9585` | `afb01162f9ef46cd6ca6b21e623bb894276778be46c53de979761978f72f9585` |
| H21 | True | `7ed0e65e3f0156c364e1e40967b68e0cc7a035334708744638c24d58f8e1efec` | `7ed0e65e3f0156c364e1e40967b68e0cc7a035334708744638c24d58f8e1efec` |
| H22 | True | `3ade9d4a54f8c33f20839e18baac13043d52643f6770a68f71516acacaa902b9` | `3ade9d4a54f8c33f20839e18baac13043d52643f6770a68f71516acacaa902b9` |
| H23 | True | `6b73d824aa5e860a164a29b640050e983a736d6b3b7618f1d50a3fdbf5ab8128` | `6b73d824aa5e860a164a29b640050e983a736d6b3b7618f1d50a3fdbf5ab8128` |
| H24 | True | `9cb89893f1f741a696c7a20d98ec502f02a44bd106916390adbc628fa91b9508` | `9cb89893f1f741a696c7a20d98ec502f02a44bd106916390adbc628fa91b9508` |
| H25 | True | `dc6c5cd238937ff97cd197f7b2ac8d6d44bca6943c216ff5aa1f8e7de6a494fb` | `dc6c5cd238937ff97cd197f7b2ac8d6d44bca6943c216ff5aa1f8e7de6a494fb` |
| H26 | True | `de75be3e25b3b4250e3ccaf8d4344c81b3128c8b83686e55d9d0b17714e7396d` | `de75be3e25b3b4250e3ccaf8d4344c81b3128c8b83686e55d9d0b17714e7396d` |
| H27 | True | `f403bd22c2a7c52395753e220f295c3c33113aa518d13f4983861046fabcf594` | `f403bd22c2a7c52395753e220f295c3c33113aa518d13f4983861046fabcf594` |
| H28 | True | `508f8bc8e7a4c1174559250ff0a1c553bbd00e1c6b1d38c74e001dd880173f5f` | `508f8bc8e7a4c1174559250ff0a1c553bbd00e1c6b1d38c74e001dd880173f5f` |
| H29 | True | `0836f4bca99c7275fbd6ed463f8e62958384dfde7a7f4fcadf77fac6ca63d70a` | `0836f4bca99c7275fbd6ed463f8e62958384dfde7a7f4fcadf77fac6ca63d70a` |
| H30 | True | `444081bb66bf8b21979a220e59a4d372cc5ee554d9a4f7dd94d4c2e1de744ed2` | `444081bb66bf8b21979a220e59a4d372cc5ee554d9a4f7dd94d4c2e1de744ed2` |

## Preserved source files

| Input | Path | SHA-256 |
|---|---|---|
| v1_jsonl | `answer_evaluation_3_1_flash_lite_v1.jsonl` | `17cc35038a37409365bbb3f149f503085f0df277d3fe2b9bc32f88957476b8e9` |
| v2_jsonl | `answer_evaluation_3_1_flash_lite_v2_dev.jsonl` | `36d4da6e26cd7befea00eca3e30dcb13999aceee3fa49f778364ba64f4a2c2cd` |
| v1_workbook | `answer_review_3_1_flash_lite_v1.xlsx` | `855e80a073fd282cb04fd3664cdf6c2efdf2f3aeff02c241804f22f5db424ce2` |
| v2_dev_workbook | `answer_review_3_1_flash_lite_v2_dev.xlsx` | `515344db6f1d47515e6a76b43544643f2b817818049a549e4b5f027152f10f66` |

## Human review gate

The new V2 final-review workbook contains original answers, exact retrieved excerpts, resolved source metadata and citation-navigation aids. All 90 human score cells and review notes start blank. Existing scores are not copied. No quality improvement is claimed.

After review, run from the repository root:

```powershell
.\.venv\Scripts\python.exe compare_answer_quality_v1_v2.py
```

The calculator rejects missing, duplicate or unexpected IDs, changed reviewed content, changed source hashes, formulas, missing labels and non-0/1/2 values before writing a report. It never overwrites an existing review workbook or comparison report.

## Methodological limitations

H01–H30 are now a DEVELOPMENT set: earlier V1 failures informed V2 prompt design. This comparison cannot establish generalization or final held-out improvement.

The scores are human judgments on an ordinal 0/1/2 rubric. Reported means and bootstrap intervals are descriptive summaries of these 30 paired answers, not proof of general legal accuracy. Each configuration has only one saved answer per question; generation stochasticity, different run times and provider changes are not separated from configuration effects. Exact historical prompt text, generation parameters, model revision and code hashes were not persisted, so prompt-only causal attribution is not established.

V1 lacks explicit persisted answer-version tags; its identification as V1 is inferred from the baseline artifact provenance and legacy response schema. V2 is explicitly tagged. V2 is a bundle of prompt, source-formatting and traceability changes, not an isolated instruction change.

Source-ID membership validation is NOT semantic citation support. Supplied citation metadata is not a verified claim-to-evidence mapping. Reviewers must evaluate actual claims, qualifications, attribution and abstentions against the persisted excerpts, consulting original judgments when necessary. The excerpts are bounded retrieval windows, not complete judgments.

The V2 workbook is not blinded to configuration and V1 scores already exist. Reviewer identity, consistency, independence and adjudication affect comparison validity; record them in Provenance. Bootstrap resamples questions as paired units, not individual score cells. Percentile intervals are nominal 95% intervals with no multiplicity correction across dimensions.
