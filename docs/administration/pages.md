# Pages per role

What each kind of user sees, and what the technical details preference adds (decision D105).
The rule behind every page: the entity, its state and the next action first; identities,
ports, traces and provider fields under Technical details.

## The preference

Every person has a "Technical details" switch at the bottom of the sidebar. Off, the pages
show the operational picture only. On, the folded Technical details sections open by default
and the Network section appears in the sidebar. Server admins start with it on, everyone else
off; the choice is kept per user on the server, so it follows the person to another browser.
A folded section opens for one page with a click without changing the preference.

## Project viewer

| Page | Shows | With technical details on |
| --- | --- | --- |
| Live map | Entities with their health, the layers panel (Entities, Devices, Features, Events, Coverage), tracks with the Tracks card and its length settings, recent events. The Devices tab is the device layer: every device of the project, off by default, with or without an entity; a device track is dashed | Nothing more |
| All projects (server admins) | The project switcher's first entry: the live map, entities, devices, alerts, events, gateways and traffic over every project, with the project as the top level of the layers panel and a Project column in the lists; links go to the object's own project. Devices in no project appear under "Not in a project" on the device layer and in the devices list's project filter. The other pages stay per project | Only server admins see the entry |
| Entities | Name, type, status, group, last seen, the device by name, a map link | Nothing more |
| Entity page | The entity, the device tracking it with its health, the assignment history | Nothing more |
| Devices | Name, type, status, serial, entity, group, last seen, health | The driver column |
| Device page | Device, health, assignments, actions, recent positions | External identities, the traffic section, the deliveries and provenance links on positions |
| Alerts, Events | The open alerts and the recent events | Nothing more |
| Commands | The command timelines | Nothing more |
| Data explorer, Exports, Dashboards | The data | Nothing more |
| Network: Traffic, Gateways, Trace explorer | Hidden | The whole section |

## Project admin

Everything a viewer sees, plus Rules, Automations, Integrations, Curation and the Project
admin section (Members, Features, Groups, Notifications, Settings). The technical details
preference works the same way.

## Server admin

Everything, plus the Server admin section (Needs attention, System health, Traffic, Backup
and recovery, System alerts, Automations, Notifications, Projects, Users, Devices, Data
sources, Gateways, Audit, AI policy, catalogues). Server admins start with technical details
on, since their pages are the machinery; switching it off gives the same operational view a
ranger has, which is the way to check what a ranger sees.

## Where the machinery lives

- Identities, ports and frames: the device page's Technical details and Network, Traffic.
- Processing traces: Network, Trace explorer, and the provenance links on a position.
- Provider fields: the source event dialog reached from traffic rows and provenance links.
- Gateways: Network, Gateways, the map's Coverage tab and Server admin, Gateways.
