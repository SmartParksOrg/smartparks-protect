# TODO list

- [ ] DO Quentins list from email: WATTHEZ Quentin <quentin.watthez@spw.wallonie.be> Mon, Aug 17, 3:15 PM "AddaxAI Connect new user"

- [ ] Add a new role for external which can get external email reports. See the specifics in the email thread between me and Annemieke Vredegoor <a.vredegoor@drenthe.nl>, "AddaxAI Connect - Mogelijke toevoeging: externe rapporten verzenden"

Reported by field in ER - do we want to fill it in? 



## Possible future features
- [ ] multi language
- [ ] Make it event aware. 
- [ ] Make it use label verification, and count confirmation just like AddaxAI WebUI. This improves the overcounting.... 
- [ ] Sensing clues integration
- [ ] Ingestion: scan uploads/ once at startup, a file that lands during a container restart is missed, so updates to servers can miss images...
- [ ] Make the graphs, maps and charts use icons next to the species names: https://www.phylopic.org/. 



# Add INSTAR camera profile
INSTAR — implemented as a path-based profile.

- Custom-path format: `INSTAR/lat<LAT>_lon<LON>` (e.g. `INSTAR/lat52.02368_lon12.98290`).
- Camera registered in Camera Management with `device_id = lat52.02368_lon12.98290`.
- Path-based profile parses lat/lon from the path segment and datetime from the filename.
- `record/*.mp4` clips are logged and deleted (no video support).
- `Test-Snapshot.jpeg` is rejected as `missing_datetime`.
- See `docs/camera-requirements.md` for the full setup guide.

Open follow-ups:
- Confirm what the `A_` filename prefix means once more INSTAR firmwares are seen. If it turns out to be a per-unit channel ID, the device_id scheme needs to grow another segment.
- INSTAR sends no daily health reports, so the camera health page will stay empty for these cameras. Worth a UI hint someday.

