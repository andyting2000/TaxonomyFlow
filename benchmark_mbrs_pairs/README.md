# Golden MBRS PDF/XML Pairs

Feature #17A standardizes the six local auditor-created MBRS XML benchmark pairs.

Each `case_*` folder contains:

- `source.pdf`: fully OCR annual financial statement PDF.
- `reference.xml`: auditor-created MBRS Tool XML reference instance.
- `metadata.json`: local provenance and optional normalized Azure DI report references.

The evaluation harness reads these files locally. It does not send reference XML to Azure DI, Qwen, or any other external provider.

Run the offline harness:

```powershell
python -B scripts\build_golden_mbrs_dataset.py --cases-dir benchmark_mbrs_pairs --no-live-llm
```

Cases without a captured normalized Azure DI report are reported as pending extraction evidence. Capture or supply normalized Azure DI output separately, then reference that local report in `metadata.json` or pass `--normalized-extraction-report`.
