# Movement Assessment Engine

Automated scoring, clinical reporting, and CPT billing for movement assessments.

## Architecture

```
fms/
├── scoring/
│   ├── deep_squat.py      # Rule engine: CSV → score (0-3) + criteria details
│   └── thresholds.py      # Angle thresholds (tunable, research-backed)
├── reporting/
│   ├── report_generator.py # LLM API calls → clinical report + CPT suggestions
│   └── templates.py        # Prompt templates for the LLM
├── billing/
│   └── cpt_codes.py        # Rule-based CPT suggestions (no LLM needed)
├── pipeline.py              # Ties it all together: CSV → score + report + codes
└── __main__.py              # CLI entry point
```

## Two Modes

### Quick Mode (no API key needed)
```bash
python -m fms.pipeline path/to/video_labeled.csv
```
Runs the rule engine + rule-based CPT suggestions. Instant results.

### Full Mode (requires Anthropic API key)
```bash
export ANTHROPIC_API_KEY=your-key-here
python -m fms.pipeline path/to/video_labeled.csv --full-report
```
Adds LLM-generated clinical narrative report + smarter CPT suggestions.

## Options
```
--pain          Flag that patient reported pain (auto-scores 0)
--json          Output raw JSON
--output FILE   Save results to a file
--full-report   Enable LLM-powered clinical report generation
```

## Threshold Tuning

The angle thresholds in `scoring/thresholds.py` are starting values based on
published biomechanical research (Butler et al. 2010, Heredia et al. 2021).

**You will need to calibrate these** against real assessment videos scored by a PT.
The process:
1. Record 10-20 deep squat videos
2. Have a certified PT score each one (1, 2, or 3)
3. Run each through the engine
4. Compare engine scores to PT scores
5. Adjust thresholds until agreement is high

## Integration

Import directly in your FastAPI backend:
```python
from fms.pipeline import run_quick, run_full

# In your API endpoint:
result = run_quick("path/to/exported.csv")
# Returns dict with score, criteria, and CPT suggestions
```

## CPT Code Disclaimer

All CPT code suggestions are for informational purposes only.
The treating physical therapist must review and approve all billing codes.
This system does not provide billing or medical advice.
