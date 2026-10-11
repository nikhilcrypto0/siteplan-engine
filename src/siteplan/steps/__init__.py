"""The architect's steps for any project, one at a time (the stage-wise build, 2026-10-10).

Each step reads the survey and the project and writes a report that says what it did, what is
happening, what it looks at, which rules it used and where each one comes from, what the engine
decided by itself, and the result, with one picture; then it stops. Step 1 copies the survey
(survey_copy.py); step 3 takes off the land given up for road widening (road_widening.py). The
other steps come in later stages (run.LATER). `siteplan steps` runs them (run.py). Every step
after step 1 carries everything step 1 found that a rule may need (carried.py): a row in its
report, an entry in its facts, a place in its picture.
"""
