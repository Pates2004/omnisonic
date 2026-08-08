# Contributing to OmniSonic

Thank you for contributing. OmniSonic bundles the upstream OmniVoice engine and
adds the maintained desktop application under `omnisonic/`.

## Setup

```powershell
python -m pip install -e ".[desktop,dev]"
pre-commit install
```

This enables automatic code style checks (linting, formatting, trailing whitespace, etc.) on every `git commit`.

Before committing, run:

```powershell
pre-commit run --all-files
python -m unittest -v tests.test_desktop_logic
python -m pytest
```

This will auto-fix any style issues. Then stage and commit as usual:

Model-dependent tests are skipped unless `OMNIVOICE_TEST_MODEL_PATH` points to
a local checkpoint. New desktop behavior should have a model-free unit test.

Before committing, also verify that no files from `presets/`, generated audio,
recordings, model checkpoints, or user settings are staged. Voice presets can
contain derived voice data and transcripts.

```powershell
git add .
git commit -m "your message"
```
