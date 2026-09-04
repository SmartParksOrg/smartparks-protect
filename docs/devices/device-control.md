# Device control

Smart Parks Protect sends commands to devices through one path whether a person clicks Actions on a device, an automation reacts to an event, or later an AI client asks (architecture 17). The driver owns what a command means and how it is encoded; the connectivity adapter of the chosen data source owns how it is delivered. No screen or rule contains provider logic.

## Actions

A device offers the actions its driver declares (`control_actions` on the driver, `shared/control/actions.py`). Each action has a stable key, a label, typed parameters (a Pydantic model whose JSON schema builds the form), the permission it needs, a confirmation policy, the connectivity capability the route must have, an encoder, and optionally an interpreter that recognises the device's answer in later uplinks.

| Policy | Meaning |
| --- | --- |
| none | Runs at once (request status, request position) |
| confirm | The UI asks the user to confirm |
| privileged | Needs `devices:control_high_impact` and confirmation (reset, configuration changes) |

`GET /devices/{id}/actions` lists every action with `available` and a reason when it is not: no identity on an enabled data source, no downlink capability, an adapter that cannot send commands. The UI shows disabled entries with that reason instead of hiding them.

## Route

A command travels through the enabled data source that holds an identity of the device, whose adapter has a command connector, and whose capabilities include what the action needs (`downlink`). When several qualify, the identity seen most recently wins. The command records the data source, the external id and the channel (`lorawan`).

ChirpStack (decision D50): the command becomes a device queue item through the REST API. The `txack` event reports it transmitted by a gateway, the `ack` event acknowledged by the device for confirmed downlinks, and a `log` error fails it. The device's queue can be read and flushed from the device page (flushing is high impact).

## Lifecycle

`created`, `encoded`, `submitted`, `accepted_by_network`, `queued`, `scheduled`, `transmitted`, `acknowledged`, `confirmed_by_device`, `failed`, `expired`. A stage the platform cannot observe stays unreached; nothing is invented (architecture 17.4). Every change is a `command_executions` row with its source (user, automation, adapter, device, expiry), and the command has an audit-class processing trace.

`confirmed_by_device` needs an interpreter (decision D51): OpenCollar confirms a status request with the next status uplink, a position request with the next port 2 fix, and a reset with a rejoin or a status uplink whose reset reason is a software request. Actions without an interpreter end at the last stage the network reports. Commands with no final state after the action's expiry (24 hours by default) become `expired`.

A platform refusal (unknown device, rejected payload) is stored as a failed command with the reason, so the attempt stays in the history.

## Permissions

`devices:control` for operational actions and `devices:control_high_impact` for reset and configuration, both project admin only, judged in the device's current project. A device without a project (inventory, repair) can be controlled by server admins only.

## Automations

An automation action of type `command` sends `action_key` with `parameters` to the event's device, with the automation as actor. It uses the same function as the API, so encoding, routing, lifecycle and trace are identical; a platform outage makes the delivery retry, a refusal fails it.

## API

| Endpoint | Purpose |
| --- | --- |
| `GET /devices/{id}/actions` | Actions with availability and reasons |
| `POST /devices/{id}/commands` | Issue a command (`action_key`, `parameters`, `confirmed`) |
| `GET /devices/{id}/commands` | The device's history |
| `GET /commands/{id}` | Lifecycle timeline |
| `GET /projects/{id}/commands` | Every command of the project, newest first |
| `GET`, `DELETE /devices/{id}/downlink-queue` | The platform's queue, and flush |

Realtime: `command.updated` messages reach the project's WebSocket clients.

## Adding an action to a driver

Declare a `ControlAction` in the driver's `control_actions`: a parameter model, an encoder returning `EncodedCommand(payload, f_port, confirmed)`, and an interpreter when the device answers. Write a golden test for the encoding and one for the interpreter. Document the action in the driver's page.
