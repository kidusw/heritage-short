# One command: `make film`. Without make (e.g. Windows): `python -m pipeline.run`.
PY ?= python
LANG_ARGS = $(if $(LANG),--lang $(LANG),)
SHOT_ARGS = $(if $(SHOTS),--shots $(SHOTS),)

.PHONY: film setup validate smoke narration radio keyframes shots music assemble offline costs clean

film: validate          ## whole pipeline, all languages (LANG=am for one)
	$(PY) -m pipeline.run $(LANG_ARGS) $(SHOT_ARGS)

setup:                  ## install dependencies
	$(PY) -m pip install -r requirements.txt

validate:               ## schema + consistency check of storyboard.json
	$(PY) -m pipeline.validate

smoke:                  ## call each provider once, log to runs.jsonl
	$(PY) -m pipeline.smoke

narration:
	$(PY) -m pipeline.narration $(LANG_ARGS) $(SHOT_ARGS)

radio: narration        ## narration-only prototype cut
	$(PY) -m pipeline.radio_cut $(LANG_ARGS)

keyframes:
	$(PY) -m pipeline.keyframes $(SHOT_ARGS)

shots:
	$(PY) -m pipeline.shots $(SHOT_ARGS)

music:
	$(PY) -m pipeline.music

assemble:
	$(PY) -m pipeline.assemble $(LANG_ARGS)

offline:                ## full run with placeholders, no keys needed
	$(PY) -m pipeline.run --offline $(LANG_ARGS)

costs:                  ## summarise runs.jsonl per stage
	$(PY) -m pipeline.costs

clean:                  ## delete generated outputs (keeps runs.jsonl)
	rm -rf outputs/*/
