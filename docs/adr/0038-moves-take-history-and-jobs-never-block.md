# 0038. Moves take the history along, and assignment changes never wait for a job

Date: 2026-09-25

Status: accepted; amends 0032 and replaces the handover rule of architecture 28.10 and 28.14

## Context

Architecture 28.10 and 28.14 said that moving a device between projects is a handover that closes the old assignment at a moment and opens the new one, and that historical ownership is never rewritten. That served the case it was written for, a device that changes hands in the field. It did not serve the case Tim met on 2026-09-25: a device onboarded in one project by mistake, or a reserve reorganised into projects after the devices were already sending, where the new project should see the data from when the device was first seen. Through the interface that was impossible; through the API it took four calls and still left events, contacts, state history, log files and commands with the old project, because the attribution rewrite covered positions and measurements only. Entities could not change project at all, so an animal moved with its device would have its history split over two entities.

Decision D206 (ADR 0032) also made the pages disable every assignment button while a device's attribution job was queued or running, and the API refused a change while one ran. After "Assign to project" with the start at the device's first data, the job covers the whole history, minutes for a device with a year of data, and "Assign to entity" stayed grey the whole time. The backend needed only the running part of that wait, and even that was a convenience of the implementation, not a rule of the data.

## Decision

A move (`POST /devices/move`, `POST /projects/{id}/entities/move`; decisions D292 and D293) takes the history from a chosen moment: the device's project assignments from that moment are cut, split or removed, a new open assignment starts there, and the attribution job rewrites the records from that moment on. The rewrite covers every table stamped with a project or an entity. An entity whose whole history lies within the move goes along, with its current state, events, alerts and commands; an entity that keeps history in the old project stays, and the moving device arrives without one. A moved entity takes its devices over the spans they tracked it, splitting a device's project assignment around the span when the device was reused elsewhere. "From now" is the old handover. Both endpoints answer a preview first, so the dialog says what will come along and what will stay before anything is written. The rule of architecture 28.10 and 28.14 is replaced by: a move by an admin of every project involved rewrites the ownership of the records from the chosen moment; the old project keeps what lies before.

Assignment changes never wait for a job (decision D291). A change while a job is running queues a follow-up job for its own window; a change while one is queued still folds into it. The worker runs one job per device at a time, waiting for a running one of the same device, and the message carries the device id so the bus keeps one device in one lane. The pages show the progress and disable nothing.

## Alternatives considered

- Keep the handover and add the missing repair pieces (an assignment ended with attribution, a start extended into the gap): the person would do a move in four steps with a 409 between some of them, and the entity would still not move.
- Copy the records into the new project instead of rewriting them: two projects would carry one record, and every count, export and rule would see it twice.
- Move the device only and let the person make a new entity in the new project: the animal's history would split over two entities and every analysis over the animal would have to join them.
- Keep the 409 while a job runs and only stop the pages disabling on a queued job: the common case would improve, but a change during the run itself would still fail, and the person would have to retry by hand.

## Consequences

A move is a real change of ownership: members of the old project lose the records from the chosen moment, which the dialog says in plain words, and the audit carries the moment and the projects. The rewrite reaches more tables, so a job over a long history takes a little longer; the extra tables are small beside the positions and measurements. Two jobs of one device can exist at once; the worker's wait and the lane by device keep them in order, and a job that fails leaves the follow-up to run. The preview and the move share one plan, so what the dialog says is what happens.
