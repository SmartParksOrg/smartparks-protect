# Fences and traps

Two modes of the OpenCollar Edge with the fence port (phase 32, design `docs/FENCE_AND_TRAP_PLAN.md`, decisions D263 to D266): a **FenceEdge** listens on an electric fence wire and reports what it hears; a **TrapEdge** watches a switch on a trap door. Both devices stand still, so their place is set by hand on the device page ([Bluetooth contacts](bluetooth-contacts.md) describes that control), and both are ordinary devices on ordinary entities.

## What the devices report

A FenceEdge sends a fence measurement every `fence_interval` seconds (port 12): whether the measurement worked, the number of pulses it counted in its sampling window, the average peak voltage in **volts** and an energy figure in the device's own units. Protect stores `fence_voltage`, `fence_pulse_count` and `fence_energy` as measurements and a `fence_measurement` state; a measurement that did not work raises a `fence_measurement_failed` event and no readings. The panels and the charts show the voltage in kV, which is how a fence person reads a fence; the stored value stays in volts.

A TrapEdge sends the switch's change at once (port 19) and its state every reporting interval (port 20). Protect stores `switch_active` and raises `switch_activated` and `switch_deactivated` events for any device that reports a switch.

## A fence line

A fence voltage is measured at one point, but the question is about a stretch of fence. So a fence is a **feature** of its own, a fence line, drawn on the map or the Features page like a route. What makes it live is the **Fence monitor** entities on it: a FenceEdge is a device on such an entity, with a fixed place, and the entity's page has a **Fence line** card that puts it on a line. A line holds any number of monitors.

The line reads its status from them, **section by section**: it is cut where its monitors stand (each monitor's place projected onto the line), a section reads the worse of the monitors at its two ends, the ends of the line read the nearest monitor, and one monitor colours the whole line. A monitor's level comes from its newest reading:

| Level | When |
| --- | --- |
| live (green) | the voltage is at or above the line's ok threshold and pulses were counted |
| low (amber) | the voltage is under the ok threshold |
| down (red) | the voltage is under the down threshold, or no pulse was counted in the window: a wire without pulses is dead whatever the noise reads |
| unknown (grey) | nothing was measured, the newest measurement failed, or the newest reading is older than twice the fence interval: a silent monitor says nothing about the wire |

The thresholds and the interval belong to the line, in its attributes under `fence` (`ok_v`, `down_v`, `interval_s`), with 4 kV, 2 kV and 60 s when nothing is set. A line without a monitor is grey and says so.

On the **live map** a fence line is drawn in its sections' colours, under Features as its own type. Its panel shows the level and since when, the thresholds, the sections with their monitors, and each monitor's newest voltage, pulses and time with a voltage chart over a day, a week or a month. The Features list shows the line's level.

Every time a section changes level the decoder raises a **`FENCE_STATUS`** event on the line: information when a stretch comes live, a warning when it reads low or unknown, critical when it is down. The event is placed in the middle of the stretch that changed and names it ("Fence East reads down near North gate to Corner"), so the feed and the automations see what happened where. The history of a line is these events and its monitors' voltage series.

Two shipped rule templates make the fence alert: **Fence down** (a fence monitor reads under 2 kV) and **Fence monitor silent** (no data for six hours; scope it to the Fence monitor type). Both create alerts and remind once a day.

## A trap

A trap is a **Trap** entity with a TrapEdge on it. For a device on such an entity, every switch reading becomes a `trap_triggered` measurement, and a change against the newest one raises **`TRAP_CLOSED`** (a warning: somebody has to go and look) or **`TRAP_OPENED`** (information).

A switch is a switch: whether "active" means the door is closed depends on how the magnet and the reed contact were mounted. The device page has a **Trap** card, shown while the device is on a Trap entity, with the answer; the default is that an active switch means closed. A wrong answer reports every catch as a release, which is why the card says so.

The shipped rule template **Trap closed** alerts when `trap_triggered` is on, reminds once a day while it stays shut, and makes the trap read critical on the live map.

## What it is not

A fence section's status is what its monitors last said, with the thresholds a person set; it is not a measurement of the whole wire. The energiser's own output is one more monitor, not a distinguished one. And a trap's count of activations (port 20) is stored as `switch_count` and not yet shown as a figure of the trap.
