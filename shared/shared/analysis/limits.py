"""The bounds of a run (plan, section 14). The ones an operator may tune mirror a setting;
the rest are constants a module reads."""

MAX_SUBJECTS_MOVEMENT = 25
#: Contact tracing compares every pair, so the work grows with the square: 40 subjects
#: is 780 pairs, which is the honest limit rather than a number that quietly melts the
#: worker (design section 4.2).
MAX_SUBJECTS_CONTACT = 40
#: A cardiac run reads one series per subject and compares nothing between them, so the
#: bound is about how many curves a person can read on one page, not about the work.
MAX_SUBJECTS_CARDIAC = 25
#: A vehicle run reads one track per subject, like movement; the trips table grows per vehicle.
MAX_SUBJECTS_VEHICLE = 25
#: A habitat run validates leave-one-individual-out, one model per animal (phase 41).
MAX_SUBJECTS_HABITAT = 40
#: The raster stack of a habitat run: cells per layer, the resolution doubled until the area
#: fits (a 60 by 60 km park at 30 m); and the cells the selection surface is drawn on.
MAX_RASTER_CELLS = 4_000_000
MAX_SURFACE_CELLS = 2_000
#: Fewer animals than this and a habitat run skips the leave-one-individual-out validation.
MIN_SUBJECTS_LOIO = 3
MAX_DEVICES = 100
MAX_ROWS_PER_DEVICE = 500_000
MAX_ANIMALS_GRAZING = 100
MAX_AREAS_GRAZING = 50
MAX_DAYS = 366
MAX_FIXES_PER_SUBJECT = 200_000
KDE_MAX_CELLS = 250
MAX_GEOMETRIES = 5_000
MAX_RESULT_BYTES = 4 * 1024 * 1024
MAX_QUEUED_PER_PROJECT = 5
KEPT_RUNS_PER_PROJECT = 200
