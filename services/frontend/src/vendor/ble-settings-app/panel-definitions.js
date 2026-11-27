// Declarative definitions of the guided settings panels. Each panel lists fields in the
// order a person needs them; fields map to setting keys from the loaded schema. Keys that
// the connected firmware does not have are skipped by the renderer, so one definition
// serves every bundled firmware version.
//
// Field shapes:
//   { key, label, help, control, unit, zeroMeansOff, enabledWhen, reason, visibleWhen, dependsOn, writeAfter,
//     warnings: [{ when: <condition>, text }] }   (a warning shows while its condition holds)
//   (`reason` is shown when enabledWhen is false; a group's reason applies to its fields)
//   enabledWhen greys a field out. Use it only where the field has no meaning in the current
//   choice (a night window with a fixed schedule, a data rate without the Custom profile), never
//   for a feature's on/off switch: people set a feature up first and switch it on last. Mark a
//   feature's settings with dependsOn: <the switch's on condition> instead; they stay editable
//   while the feature is off, and Apply writes them before the switch turns on (after it turns off).
//   { control: 'mode' | 'choice', label, keys: [...], options: [{ id, label, help, when, set, ensure }] }
//   { control: 'switch', label, keys, on: <condition>, turnOff: { key: value }, turnOn: { ensure: {...} } }
//   { control: 'text' | 'pin' | 'select' | 'hex' | 'ports', key, ... }   (hex: secret: true masks the value)
//   { control: 'datarate', key, regionKey }   (LoRaWAN DR picker with SF/bandwidth per region)
//   { control: 'byte', key, byte: n, options | min, max, unit }   (one byte of a byte-array setting;
//     several byte fields may share a key, and conditions take `byte: n` to test one byte)
//   { control: 'hex', key, secret: true, generate: true, copy: true }   (generate: a button fills
//     random bytes; copy: a button copies the value to the clipboard)
//   Panel: { requires: [keys] } renders only when the schema has every key; { beta: true } tags the
//   title; { minFirmware: { major, minor } } lets the host hide it on older firmware.
//   { control: 'matrix', columns: [{ key, label, summaryLabel }] }  (rows are the schema's message ports)
//   { control: 'status', status: <id>, label }   (read-only line from host.getStatus(id), e.g. what the
//     device reports about its hardware; hidden while the host returns null, and in the composer)
//   { control: 'vhf-preview', label, help }   (no key: draws one VHF burst from the effective
//     values and plays it with sound; shown on the main page and in the composer alike)
//   Panel: { id, title, icon, description, summary, fields }   (every panel renders folded)
//   summary is an id ('positioning', 'data', 'network', 'device') or { type: 'schedule', ...keys }
//   zeroMeansOff fields may carry onAlso: [{ key, value, when }] applied when switched on.
//   A duration with zeroMeansOff renders an on/off toggle; `onDefault` is the value used when
//   turned on with no remembered value, `offLabel` the text shown while off.
//   (`set` values are written when the option is chosen; `ensure` values only where the
//   current value is empty or zero, so a mode never leaves an interval at 0 = off)
//   { group, help, advanced, summary, enabledWhen, fields: [...] }   (groups may nest one level)
// Conditions use the PanelEngine forms: { key, equals | truthy | gt ... }, { all }, { any }, { not }.
(function (root, factory) {
  const api = factory();
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  } else {
    root.PanelDefinitions = api;
  }
}(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  const dayNightOn = { key: 'ublox_multiple_intervals', truthy: true };
  const scheduleOn = { any: [{ key: 'ublox_send_interval', gt: 0 }, dayNightOn] };
  const motionOn = { key: 'enable_motion_trig_gps', truthy: true };
  const outdoorOn = { key: 'outdoor_detection_enabled', truthy: true };
  const windowMode = { all: [{ key: 'gps_triggered_interval', gt: 0 }, { key: 'gps_motion_triggered_min_num_of_triggers_per_interval', gt: 0 }] };
  const dayNightReason = 'Only used with the day and night schedule.';
  const windowReason = 'Only used with the "Fix after repeated movement" behaviour.';

  const positioning = {
    id: 'positioning',
    title: 'Positioning (GPS)',
    connectAppSection: 'GPS',
    description: 'When the tracker takes a GNSS position fix, and how hard it tries to get one.',
    summary: 'positioning',
    fields: [
      {
        control: 'switch',
        label: 'Scheduled fixes',
        keys: ['ublox_send_interval', 'ublox_multiple_intervals'],
        on: { any: [{ key: 'ublox_send_interval', gt: 0 }, { key: 'ublox_multiple_intervals', truthy: true }] },
        turnOff: { ublox_send_interval: 0, ublox_multiple_intervals: false },
        turnOn: { ensure: { ublox_send_interval: 300 } },
        help: 'Take position fixes on a schedule. When off, motion-triggered and outdoor detection have no effect either.',
      },
      {
        control: 'choice',
        label: 'Schedule type',
        keys: ['ublox_multiple_intervals'],
        enabledWhen: scheduleOn,
        reason: 'Turn on scheduled fixes first.',
        options: [
          {
            id: 'fixed',
            label: 'Fixed interval',
            help: 'One interval, all day.',
            when: { key: 'ublox_multiple_intervals', truthy: false },
            set: { ublox_multiple_intervals: false },
            ensure: { ublox_send_interval: 300 },
          },
          {
            id: 'day-night',
            label: 'Day and night schedule',
            help: 'Two intervals: one from the day start hour, another from the night start hour (UTC).',
            when: dayNightOn,
            set: { ublox_multiple_intervals: true },
            ensure: { ublox_send_interval: 300, ublox_send_interval_2: 3600 },
          },
        ],
      },
      { key: 'ublox_send_interval', label: 'Fix interval', control: 'duration', unit: 's', enabledWhen: scheduleOn, reason: 'Turn on scheduled fixes first.',
        help: 'Time between position fixes. With the day and night schedule this is the daytime interval.' },
      { key: 'ublox_interval1_start', label: 'Day window starts', control: 'utc-hour', enabledWhen: dayNightOn, reason: dayNightReason,
        help: 'UTC hour when the daytime interval starts. Shown with your local time.' },
      { key: 'ublox_send_interval_2', label: 'Night interval', control: 'duration', unit: 's', zeroMeansOff: true, onDefault: 3600, offLabel: 'No fixes at night', enabledWhen: dayNightOn, reason: dayNightReason,
        help: 'Time between fixes from the night start hour until the day start hour.' },
      { key: 'ublox_interval2_start', label: 'Night window starts', control: 'utc-hour', enabledWhen: dayNightOn, reason: dayNightReason,
        help: 'UTC hour when the night interval starts.' },
      { key: 'ublox_active_tracking', label: 'Active tracking', control: 'toggle',
        help: 'Keep the GNSS receiver on between fixes. Adds heading and speed to position reports. Uses considerably more battery.' },
      { key: 'gps_resend_interval', label: 'Resend last position', control: 'duration', unit: 's', zeroMeansOff: true, onDefault: 600,
        help: 'How often the last known position is sent.' },
      {
        group: 'Motion-triggered fixes',
        help: 'Use the accelerometer to decide when a fix is worth taking.',
        fields: [
          { key: 'enable_motion_trig_gps', label: 'Motion-triggered GPS', control: 'toggle',
            help: 'When the tracker is not moving, scheduled fixes are skipped.' },
          { key: 'motion_ths', label: 'Motion sensitivity', dependsOn: motionOn,
            help: 'Accelerometer threshold that counts as movement (see the LIS2DW12 datasheet).' },
          {
            control: 'choice',
            label: 'Behaviour',
            keys: ['gps_triggered_interval', 'gps_motion_triggered_min_num_of_triggers_per_interval'],
            dependsOn: motionOn,
            options: [
              {
                id: 'skip',
                label: 'Skip fixes while still',
                help: 'Keep the schedule, but skip fixes while nothing moves, up to a maximum number of skips.',
                when: { any: [{ key: 'gps_triggered_interval', equals: 0 }, { key: 'gps_motion_triggered_min_num_of_triggers_per_interval', equals: 0 }] },
                set: { gps_triggered_interval: 0, gps_motion_triggered_min_num_of_triggers_per_interval: 0 },
              },
              {
                id: 'window',
                label: 'Fix after repeated movement',
                help: 'Take a fix when enough movements happen within a time window. Firmware 8.0.3 takes no scheduled fixes in this mode.',
                when: { all: [{ key: 'gps_triggered_interval', gt: 0 }, { key: 'gps_motion_triggered_min_num_of_triggers_per_interval', gt: 0 }] },
                set: { gps_triggered_interval: 60, gps_motion_triggered_min_num_of_triggers_per_interval: 5 },
              },
            ],
          },
          { key: 'gps_skipped_triggered_interval', label: 'Maximum skipped fixes', dependsOn: motionOn,
            help: 'After this many skipped intervals a fix is taken even without movement. 0 fixes on every interval.' },
          { key: 'gps_triggered_interval', label: 'Movement window', control: 'duration', unit: 's',
            enabledWhen: windowMode, reason: windowReason, dependsOn: motionOn,
            help: 'Length of the window in which movements are counted.' },
          { key: 'gps_motion_triggered_min_num_of_triggers_per_interval', label: 'Movements needed in window',
            enabledWhen: windowMode, reason: windowReason, dependsOn: motionOn,
            help: 'Number of movements within the window that trigger a fix.' },
        ],
      },
      {
        group: 'Outdoor detection (experimental)',
        advanced: true,
        help: 'Only tested on the Pangolin deployment in Namibia. Do not enable it for other applications. Takes fixes when the tracker is probably outside, estimated from temperature, movement and time of day.',
        fields: [
          { key: 'outdoor_detection_enabled', label: 'Only fix when likely outdoors', control: 'toggle',
            help: 'Fixes are attempted when the tracker is probably outdoors instead of on every interval. Needs a fix schedule.' },
          { key: 'outdoor_detection_tau', label: 'Outdoor probability threshold', dependsOn: outdoorOn,
            help: 'Probability required before a fix is attempted.' },
          { key: 'outdoor_detection_parameters', label: 'Model weights', control: 'bytes', dependsOn: outdoorOn, advanced: true },
        ],
      },
      {
        group: 'Advanced fix settings',
        advanced: true,
        summary: 'fix-quality',
        help: 'How a fix attempt runs. The first fix after a long gap is a cold fix; once one succeeds, later fixes are hot fixes. The defaults suit most deployments.',
        fields: [
          {
            group: 'Cold fix (first fix, no recent satellite data)',
            fields: [
              { key: 'cold_fix_timeout', label: 'Attempt duration', control: 'duration', unit: 's',
                help: 'Duration of a cold fix attempt.' },
              { key: 'cold_fix_retry', label: 'Retries',
                help: 'Extra cold fix attempts after the first failed one, one per interval. After the last unsuccessful one the GPS stops until "Perform GPS fix now" or a restart.' },
              { key: 'ublox_cold_fix_hour_interval', label: 'Limit cold fix attempts', control: 'duration', unit: 'h', zeroMeansOff: true, onDefault: 24, offLabel: 'No limit',
                help: 'How often a cold fix attempt is allowed, in hours.' },
            ],
          },
          {
            group: 'Hot fix (after a successful fix)',
            fields: [
              { key: 'hot_fix_timeout', label: 'Attempt duration', control: 'duration', unit: 's',
                help: 'Duration of a hot fix attempt.' },
              { key: 'hot_fix_retry', label: 'Retries',
                help: 'Extra hot fix attempts after the first failed one, one per interval. After the last unsuccessful one the next fix is cold (4 retries: 5 failed hot fixes).' },
            ],
          },
          {
            group: 'Abandon attempts with too few satellites',
            help: 'Part-way into an attempt the receiver checks how many satellites it sees; with too few, the attempt is abandoned instead of running to its full duration. The check is off when the satellite count is 0; the timer below has no off value.',
            fields: [
              { key: 'ublox_min_satellites', label: 'Satellite check', zeroMeansOff: true, onDefault: 3, offLabel: 'Off',
                onAlso: [{ key: 'ublox_min_satellites_timer', value: 30, when: { key: 'ublox_min_satellites_timer', lt: 5 } }],
                help: 'Satellites needed to continue the attempt.' },
              { key: 'ublox_min_satellites_timer', label: 'Check after', control: 'duration', unit: 's',
                dependsOn: { key: 'ublox_min_satellites', gt: 0 },
                help: 'Seconds into an attempt at which the satellite count is checked. The firmware minimum is 5 seconds; the default is 30.',
                warnings: [{ when: { key: 'ublox_min_satellites_timer', lt: 5 },
                  text: 'The device reports a value below the firmware minimum of 5 seconds (often 0 after an upgrade from older firmware). The check then runs every second and can stop fixes before satellites are found. Set it to 30 seconds.' }] },
            ],
          },
          {
            group: 'Fix result and follow-up',
            fields: [
              { key: 'horizontal_accuracy', label: 'Horizontal accuracy', unit: 'm', help: 'Horizontal accuracy in metres.' },
              { key: 'ublox_min_fix_time', label: 'Minimum search time', control: 'duration', unit: 's', help: 'Minimum time the receiver keeps searching for GNSS satellites in order to make a fix.' },
              { key: 'ublox_require_time', label: 'Fix requires valid time', control: 'toggle',
                help: 'Firmware 8.2 (beta) only. Not yet described in the firmware documentation; leave it off unless the firmware team asks for it.' },
              { key: 'ublox_leave_on', label: 'Receiver stays on after a fix', control: 'duration', unit: 's', help: 'How long the receiver stays on after a fix completes.' },
              { key: 'gps_backoff_factor', label: 'Backoff after failed fix', help: 'Delay applied to the next fix after an unsuccessful attempt.' },
            ],
          },
          {
            group: 'Initial position',
            help: 'Position stored on the device before any fix has been made.',
            fields: [
              { key: 'gps_init_lat', label: 'Initial latitude', control: 'coordinate', help: 'Initial latitude in decimal degrees.' },
              { key: 'gps_init_lon', label: 'Initial longitude', control: 'coordinate', help: 'Initial longitude in decimal degrees.' },
            ],
          },
        ],
      },
    ],
  };

  // Message types (LoRaWAN ports) as people know them. Unknown ports fall back to the
  // port name without its prefix.
  const portLabels = {
    port_lr_gps: 'LR GPS position',
    port_ublox_gps: 'GPS position',
    port_ublox_short_message: 'GPS position (short)',
    port_ublox_resend_location: 'Last position resend',
    port_ublox_sat_data: 'GPS satellite data',
    port_lr_sat_data: 'LR satellite data',
    port_settings: 'Settings',
    port_status: 'Status report',
    port_timestamp: 'Timestamp',
    port_flash_status: 'Flash status',
    port_wifi_scan: 'WiFi scan',
    port_wifi_scan_aggregated: 'WiFi scan (aggregated)',
    port_ble_scan: 'BLE scan',
    port_ble_scan_aggregated: 'BLE scan (aggregated)',
    port_ble_cmdq: 'CMDQ detections',
    port_fence: 'Fence measurement',
    port_external_switch_detection: 'Switch detection',
    port_external_switch_detection_status: 'Switch status',
    port_air_quality: 'Air quality',
    port_lp0_ping: 'LP0 ping',
    port_lp0_statistics: 'LP0 station statistics',
    port_lp0_commands: 'LP0 commands',
    port_memfault: 'Memfault diagnostics',
    port_rf_scan: 'RF scan',
  };

  const dataSending = {
    id: 'data',
    title: 'Data sending and storing',
    icon: 'envelope',
    connectAppSection: 'Data sending and storing',
    description: 'Which message types the tracker sends over LoRaWAN, sends over satellite, and stores in the flash log.',
    summary: 'data',
    fields: [
      {
        control: 'matrix',
        label: 'Message types',
        keys: [],
        columns: [
          { key: 'lr_send_flag', label: 'LoRaWAN', summaryLabel: 'over LoRaWAN' },
          { key: 'sat_send_flag', label: 'Satellite', summaryLabel: 'over satellite' },
          { key: 'lp0_send_flag', label: 'LP0', summaryLabel: 'over LP0' },
          { key: 'flash_store_flag', label: 'Store', summaryLabel: 'stored to flash' },
        ],
        help: 'Each row is a message type. Tick where it should go.',
      },
      {
        group: 'Flash log',
        advanced: true,
        fields: [
          { key: 'data_log', label: 'Flash data log', control: 'toggle', help: 'Enable the flash data log.' },
          { key: 'flash_status_interval', label: 'Flash status report', control: 'duration', unit: 's', zeroMeansOff: true, onDefault: 86400,
            help: 'How often the flash status message (percentage used, number of stored messages) is sent. Off means it is not sent or stored.' },
        ],
      },
    ],
  };

  const customAdr = { key: 'lr_adr_profile', equals: 3 };

  const network = {
    id: 'network',
    title: 'Network (LoRaWAN)',
    icon: 'messages',
    connectAppSection: 'LoRa',
    description: 'How the tracker joins and talks to the LoRaWAN network.',
    summary: 'network',
    fields: [
      { key: 'lr_enabled', label: 'LoRaWAN', control: 'toggle',
        help: 'Master switch for the LoRaWAN stack, on by default. Firmware 8.2 (beta) only; the firmware documentation does not describe the effect of switching it off yet.',
        warnings: [{ when: { key: 'lr_enabled', truthy: false }, text: 'LoRaWAN is switched off. The firmware documentation does not yet describe what the device does without it; keep it on unless the firmware team asks otherwise.' }] },
      { key: 'lr_region', label: 'Region', control: 'select', help: 'LoRaWAN frequency region. Changing it makes the device rejoin the network.' },
      { key: 'lr_adr_profile', label: 'Adaptive data rate', control: 'select',
        help: 'Network controlled suits static devices; the mobile profiles suit moving trackers; Custom uses the data rate below.' },
      { key: 'lr_adr', label: 'Data rate', control: 'datarate', regionKey: 'lr_region', enabledWhen: customAdr,
        reason: 'Only used with the Custom adaptive data rate profile.',
        help: 'The data rate number means a different spreading factor per region (DR0 is SF12 in EU 868 but SF10 in US 915); the list shows the LoRaWAN Regional Parameters table for the selected region. A lower spreading factor sends faster and uses less battery; a higher one reaches further.' },
      { key: 'rejoin_interval', label: 'Rejoin interval', control: 'duration', unit: 's', help: 'How often the device tries to rejoin the network while not joined.' },
      {
        group: 'Credentials',
        help: 'Changing the app EUI or app key makes the device rejoin the network. Credentials are only exported when the export option is ticked.',
        fields: [
          { key: 'device_eui', label: 'Device EUI', control: 'hex', help: 'The unique ID for this device, read from the LoRa chip by the firmware.',
            warnings: [{ when: { key: 'device_eui', in: ['0000000000000000', ''] },
              text: 'The device reports an all-zero Device EUI. The firmware fills this from the LoRa chip after the modem is configured; an all-zero value means that has not happened yet, or the stored value was overwritten. The network join uses the chip EUI regardless, so joining is not affected, but do not copy this value as the device identity.' }] },
          { key: 'app_eui', label: 'App EUI (Join EUI)', control: 'hex', help: 'The app ID used when joining the network.' },
          { key: 'app_key', label: 'App key', control: 'hex', secret: true, help: 'The key used to join the network.' },
        ],
      },
      {
        group: 'Messaging',
        help: 'Retries for messages sent from the Messenger card.',
        fields: [
          { key: 'lr_messaging_retry_interval', label: 'Retry interval', control: 'duration', unit: 's', help: 'How long the device waits between messaging retry attempts.' },
          { key: 'lr_messaging_retry_count', label: 'Retries', help: 'Number of retry attempts for messages sent from the Messenger card.' },
        ],
      },
      {
        group: 'Advanced',
        advanced: true,
        fields: [
          { key: 'lr_max_confirm_fail', label: 'Maximum confirmed-message failures', help: 'Maximum number of failed confirmed messages.' },
          { key: 'lr_confirm_flag', label: 'Send as confirmed messages', control: 'ports', help: 'Message types sent as confirmed uplinks.' },
          { key: 'lr_join_flag', label: 'Join before sending', control: 'ports', help: 'Message types for which the device attempts to join first when it is not joined.' },
        ],
      },
    ],
  };

  const device = {
    id: 'device',
    title: 'Device and security',
    icon: 'locked',
    connectAppSection: 'Security',
    description: 'Name, Bluetooth access, and how often the tracker reports its status.',
    summary: 'device',
    fields: [
      { key: 'device_name', label: 'Device name', control: 'text', help: 'Name shown in Bluetooth scans (up to 8 characters).' },
      { key: 'device_pin', label: 'Bluetooth PIN', control: 'pin', help: 'Four digits required to connect over Bluetooth. 0000 means no PIN is checked.' },
      { key: 'led_enabled', label: 'Status LED', control: 'toggle', help: 'Enable the status LED.' },
      { key: 'status_send_interval', label: 'Status report interval', control: 'duration', unit: 's', help: 'How often the device sends a status update.' },
      {
        group: 'Advanced',
        advanced: true,
        fields: [
          { key: 'check_error_interval', label: 'Error check interval', control: 'duration', unit: 's', help: 'How often the device checks for error conditions.' },
          { key: 'tracker_type', label: 'Tracker type', control: 'select', help: 'Tracker model type.' },
        ],
      },
      {
        group: 'Diagnostics',
        advanced: true,
        fields: [
          { key: 'memfault_send_interval', label: 'Memfault diagnostics', control: 'duration', unit: 's', zeroMeansOff: true, onDefault: 86400, help: 'How often Memfault data is sent.' },
        ],
      },
    ],
  };

  function scheduleTypeField(multipleKey, interval1Key, interval2Key, dependsOn) {
    return {
      control: 'choice',
      label: 'Schedule type',
      keys: [multipleKey],
      dependsOn,
      options: [
        { id: 'fixed', label: 'Fixed interval', help: 'One interval, all day.',
          when: { key: multipleKey, truthy: false }, set: { [multipleKey]: false } },
        { id: 'day-night', label: 'Day and night schedule', help: 'Two intervals: one from the day start hour, another from the night start hour (UTC).',
          when: { key: multipleKey, truthy: true }, set: { [multipleKey]: true },
          ensure: { [interval1Key]: 3600, [interval2Key]: 86400 } },
      ],
    };
  }

  const satelliteOn = { key: 'satellite_enabled', truthy: true };
  const satelliteDayNight = { key: 'satellite_multiple_intervals', truthy: true };
  const satelliteDayNightReason = 'Only used with the day and night schedule.';

  const satellite = {
    id: 'satellite',
    title: 'Iridium satellite',
    icon: 'square-caret-up',
    connectAppSection: 'Satellite',
    description: 'When the tracker sends data over the Iridium satellite modem. Which message types go over satellite is set in Data sending and storing.',
    summary: { type: 'schedule', enabledKey: 'satellite_enabled', interval1Key: 'satellite_send_interval', multipleKey: 'satellite_multiple_intervals',
      start1Key: 'satellite_interval1_start', interval2Key: 'satellite_send_interval2', start2Key: 'satellite_send_interval2_start', verb: 'Send', subject: 'Satellite sending' },
    fields: [
      { key: 'satellite_enabled', label: 'Satellite sending', control: 'toggle', help: 'Send queued messages over the Iridium satellite modem.' },
      // What the device reports about its RockBLOCK modem (status message, features bit 0). The
      // firmware only tests the modem at boot with satellite on and when satellite is switched on.
      { control: 'status', status: 'satellite-modem', label: 'Satellite modem' },
      scheduleTypeField('satellite_multiple_intervals', 'satellite_send_interval', 'satellite_send_interval2', satelliteOn),
      { key: 'satellite_send_interval', label: 'Send interval', control: 'duration', unit: 's', dependsOn: satelliteOn,
        help: 'Time between satellite send attempts. With the day and night schedule this is the daytime interval.' },
      { key: 'satellite_interval1_start', label: 'Day window starts', control: 'utc-hour', enabledWhen: satelliteDayNight, reason: satelliteDayNightReason, dependsOn: satelliteOn,
        help: 'UTC hour when the daytime interval starts.' },
      { key: 'satellite_send_interval2', label: 'Night interval', control: 'duration', unit: 's', zeroMeansOff: true, onDefault: 86400, offLabel: 'No sending at night',
        enabledWhen: satelliteDayNight, reason: satelliteDayNightReason, dependsOn: satelliteOn,
        help: 'Time between send attempts from the night start hour until the day start hour.' },
      { key: 'satellite_send_interval2_start', label: 'Night window starts', control: 'utc-hour', enabledWhen: satelliteDayNight, reason: satelliteDayNightReason, dependsOn: satelliteOn,
        help: 'UTC hour when the night interval starts.' },
      {
        group: 'Advanced',
        advanced: true,
        fields: [
          { key: 'satellite_retry', label: 'Send retries', dependsOn: satelliteOn, help: 'Send attempts per satellite session. The delay between retries is random: 1 to 5 s for the first 3, 5 to 20 s up to the 6th, 20 to 40 s after that.' },
        ],
      },
    ],
  };

  // S-Band is a LoRa link on a separate radio, not the Iridium modem, so it gets its own panel.
  const sBandOn = { key: 's_band_send_interval', gt: 0 };

  const sBand = {
    id: 'sband',
    title: 'S-Band satellite',
    icon: 'square-caret-up',
    description: 'Sending the status and short position message over the S-Band LoRa radio. This is separate from the Iridium satellite modem.',
    fields: [
      { key: 's_band_send_interval', label: 'S-Band sending', control: 'duration', unit: 's', zeroMeansOff: true, onDefault: 3600, offLabel: 'S-Band sending off',
        help: 'How often the status and short position message is sent over S-Band. Off means no S-Band sending.' },
      { key: 's_band_send_mode', label: 'Send mode', control: 'select', dependsOn: sBandOn,
        help: 'Send without frequency hopping (FHSS), with it, or both.' },
      { key: 's_band_rf_frequency_hz', label: 'Frequency', unit: 'Hz', dependsOn: sBandOn, help: 'Frequency on which S-Band LoRa operates.' },
      {
        group: 'Credentials',
        help: 'Keys used to encode S-Band messages. Credentials are only exported when the export option is ticked.',
        fields: [
          { key: 's_band_dev_adr', label: 'Device address', control: 'hex', help: 'Device address (4 bytes) used to encode S-Band messages.' },
          { key: 's_band_network_key', label: 'Network key', control: 'hex', secret: true, help: 'NwkSKey (16 bytes) used to encode S-Band messages.' },
          { key: 's_band_app_key', label: 'App key', control: 'hex', secret: true, help: 'AppSKey (16 bytes) used to encode S-Band messages.' },
        ],
      },
    ],
  };

  const vhfOn = { key: 'vhf_enabled', truthy: true };
  const vhfDayNight = { key: 'vhf_multiple_intervals', truthy: true };
  const vhfDayNightReason = 'Only used with the day and night schedule.';

  const vhf = {
    id: 'vhf',
    title: 'VHF beacon',
    icon: 'bars',
    description: 'When the tracker transmits VHF beacon pulses for directional tracking.',
    summary: { type: 'schedule', enabledKey: 'vhf_enabled', interval1Key: 'vhf_interval1', multipleKey: 'vhf_multiple_intervals',
      start1Key: 'vhf_interval1_start', interval2Key: 'vhf_interval2', start2Key: 'vhf_interval2_start', verb: 'Transmit', subject: 'The VHF beacon' },
    fields: [
      { key: 'vhf_enabled', label: 'VHF beacon', control: 'toggle', help: 'Transmit VHF beacon pulses on the schedule below.' },
      scheduleTypeField('vhf_multiple_intervals', 'vhf_interval1', 'vhf_interval2', vhfOn),
      { key: 'vhf_interval1', label: 'Transmit interval', control: 'duration', unit: 's', dependsOn: vhfOn,
        help: 'Time between beacon bursts. With the day and night schedule this is the daytime interval.' },
      { key: 'vhf_interval1_start', label: 'Day window starts', control: 'utc-hour', enabledWhen: vhfDayNight, reason: vhfDayNightReason, dependsOn: vhfOn,
        help: 'UTC hour when the daytime interval starts.' },
      { key: 'vhf_interval2', label: 'Night interval', control: 'duration', unit: 's', zeroMeansOff: true, onDefault: 60, offLabel: 'No beacon at night',
        enabledWhen: vhfDayNight, reason: vhfDayNightReason, dependsOn: vhfOn,
        help: 'Time between bursts from the night start hour until the day start hour.' },
      { key: 'vhf_interval2_start', label: 'Night window starts', control: 'utc-hour', enabledWhen: vhfDayNight, reason: vhfDayNightReason, dependsOn: vhfOn,
        help: 'UTC hour when the night interval starts.' },
      { control: 'vhf-preview', label: 'Beacon sound',
        help: 'One burst as the collar sends it: pulse length, spacing and count from the Transmitter settings below. Play repeats bursts at the real interval when it is 10 s or less. The pitch depends on how the receiver is tuned, so a 1 kHz tone stands in for it. Other work on the collar (GPS fixes, LoRaWAN sends) can delay a burst by seconds to minutes.' },
      {
        group: 'Transmitter',
        advanced: true,
        help: 'Radio parameters of the beacon. Match them to the receiver in use.',
        fields: [
          { key: 'vhf_tx_frequency_khz', label: 'Frequency', unit: 'kHz', help: 'VHF transmit frequency.' },
          { key: 'vhf_num_of_packets_per_burst', label: 'Pulses per burst', help: 'Number of beeps (pulses) per burst.' },
          { key: 'vhf_time_between_packets_ms', label: 'Time between pulses', unit: 'ms', help: 'Time between beeps within a burst. Only applies when more than one pulse is sent per burst.' },
          { key: 'vhf_single_pulse_duration_ms', label: 'Pulse duration', unit: 'ms', help: 'Duration of each pulse inside a burst.' },
          { key: 'vhf_external_path', label: 'External antenna path', control: 'toggle', help: 'Transmit over the external VHF antenna connector instead of the on-board LoRaWAN antenna. Rhino Edge Cube, Puck50 and Puck35 have no VHF connector, so this changes nothing there.' },
        ],
      },
    ],
  };

  const fenceAndSwitchWarning = {
    when: { all: [{ key: 'fence_enabled', truthy: true }, { key: 'external_switch_detection_enabled', truthy: true }] },
    text: 'Fence monitoring and external switch detection must not be enabled together; the firmware disables the switch function when both are on.',
  };

  const wifiOn = { key: 'wifi_scan_interval', gt: 0 };
  const wifiScanning = {
    id: 'wifi-scanning',
    title: 'WiFi scanning',
    icon: 'wifi-scan',
    description: 'Periodic scans for nearby WiFi networks. Results are sent as their own message types (see Data sending and storing).',
    fields: [
      { key: 'wifi_scan_interval', label: 'Scan', control: 'duration', unit: 's', zeroMeansOff: true, onDefault: 3600, help: 'How often a WiFi scan runs.' },
      { key: 'wifi_scan_aggregated_interval', label: 'Aggregated results', control: 'duration', unit: 's', zeroMeansOff: true, onDefault: 86400,
        dependsOn: wifiOn, help: 'How often aggregated WiFi scan results are produced.' },
      { key: 'wifi_scan_report_zero_connections_found', label: 'Report empty scans', control: 'toggle', dependsOn: wifiOn,
        help: 'Also send a result when no networks were found.' },
    ],
  };

  const bleOn = { key: 'ble_scan_interval', gt: 0 };
  const bleScanning = {
    id: 'ble-scanning',
    title: 'BLE scanning',
    icon: 'ble-scan',
    description: 'Periodic scans for nearby Bluetooth devices. Results are sent as their own message types (see Data sending and storing).',
    fields: [
      { key: 'ble_scan_interval', label: 'Scan', control: 'duration', unit: 's', zeroMeansOff: true, onDefault: 3600, help: 'How often a BLE scan runs.' },
      { key: 'ble_scan_aggregated_interval', label: 'Aggregated results', control: 'duration', unit: 's', zeroMeansOff: true, onDefault: 86400,
        dependsOn: bleOn, help: 'How often aggregated BLE scan results are produced.' },
      { key: 'ble_scan_duration', label: 'Scan duration', unit: 'ms', dependsOn: bleOn, help: 'Scan duration in milliseconds.' },
      { key: 'ble_scan_filter', label: 'Filter', control: 'select', dependsOn: bleOn,
        help: 'Filtering applied to scanned data before storing or sending. The options depend on the firmware version.' },
      { key: 'ble_scan_manufacturer_id', label: 'Manufacturer ID', control: 'hex-number', enabledWhen: { key: 'ble_scan_filter', in: [1, 2, 4] }, reason: 'Only used with a manufacturer ID filter.', dependsOn: bleOn,
        help: 'Bluetooth manufacturer ID, in hex (Smart Parks is 0x0A61).' },
      { key: 'ble_scan_report_zero_connections_found', label: 'Report empty scans', control: 'toggle', dependsOn: bleOn,
        help: 'Also send a result when no devices were found.' },
    ],
  };

  const cmdqOn = { key: 'cmdq_enabled', truthy: true };
  const cmdq = {
    id: 'cmdq',
    title: 'CMDQ',
    icon: 'bluetooth',
    description: 'Search for one specific Bluetooth device nearby and report when it is detected.',
    fields: [
      { key: 'cmdq_enabled', label: 'CMDQ', control: 'toggle',
        help: 'Scan for the device below on the search interval and report detections.',
        warnings: [{ when: cmdqOn,
          // The firmware's first scan after switching on lasts the search interval (bt_cmdq.c,
          // SCAN_IMMEDIATE); Bluetooth advertising is off and the app is disconnected meanwhile.
          text: (getValue, engine) => `Switching CMDQ on disconnects this app at once: the collar then scans for up to ${engine.formatDurationWords(getValue('cmdq_search_interval') || 300)} (the search interval) and cannot be reached over Bluetooth until that scan ends. Later scans drop the connection too.` }] },
      { key: 'cmdq_searched_mac_address', label: 'Device to search for', control: 'mac', dependsOn: cmdqOn, help: 'Bluetooth MAC address of the device to search for.' },
      { key: 'cmdq_search_interval', label: 'Search interval', control: 'duration', unit: 's', dependsOn: cmdqOn,
        help: 'Seconds between scans. For immediate and long scans this is the active scan duration; set it near the searched device\'s advertisement interval.' },
      { key: 'cmdq_scan_duration', label: 'Short scan duration', unit: 'ms', dependsOn: cmdqOn, help: 'Milliseconds spent actively scanning during a short scan.' },
      { key: 'cmdq_reporting_interval', label: 'Report detections every', control: 'duration', unit: 's', dependsOn: cmdqOn,
        help: 'Seconds between composing and sending detection reports.' },
      { key: 'cmdq_on_no_detection_wait_duration', label: 'Wait after a failed long scan', control: 'duration', unit: 's', dependsOn: cmdqOn,
        help: 'Seconds to wait after a long scan finds nothing before trying again.' },
      {
        group: 'Advanced',
        advanced: true,
        fields: [
          { key: 'cmdq_report_zero_messages_to_be_sent', label: 'Report when nothing was detected', control: 'toggle', dependsOn: cmdqOn, help: 'Send an empty report when no detection was made between two reporting intervals.' },
        ],
      },
    ],
  };

  const fenceOn = { key: 'fence_enabled', truthy: true };
  const fence = {
    id: 'fence',
    title: 'Fence monitor',
    icon: 'electric-fence',
    description: 'Measure the voltage of an electric fence (requires supported hardware). Measurements and calibration are in the FenceEdge card.',
    fields: [
      { key: 'fence_enabled', label: 'Fence monitoring', control: 'toggle', help: 'Enable fence measurements (requires supported hardware).', warnings: [fenceAndSwitchWarning] },
      { key: 'fence_interval', label: 'Measure', control: 'duration', unit: 's', zeroMeansOff: true, onDefault: 60, dependsOn: fenceOn,
        help: 'Seconds between fence measurements.' },
      { key: 'fence_sampling_length', label: 'Measurement length', control: 'duration', unit: 's', dependsOn: fenceOn, help: 'Measurement length in seconds (1 to 60).' },
      { key: 'fence_led_blink', label: 'Blink LED on measurement', control: 'toggle', dependsOn: fenceOn, help: 'Blink the LED during fence measurements.' },
      {
        group: 'Advanced',
        advanced: true,
        fields: [
          { key: 'fence_mv_scaling_factor', label: 'Voltage scaling factor', dependsOn: fenceOn, help: 'Scaling factor applied to the measured millivolts (1000 mV measured -> 10 kV at 10000).' },
        ],
      },
    ],
  };

  const switchOn = { key: 'external_switch_detection_enabled', truthy: true };
  const externalSwitch = {
    id: 'switch',
    title: 'External switch',
    icon: 'power-off',
    description: 'Detect activity on the external switch input, or count its pulses, and report it over LoRa.',
    fields: [
      { key: 'external_switch_detection_enabled', label: 'Switch detection', control: 'toggle', help: 'Turns on external switch detection.', warnings: [fenceAndSwitchWarning] },
      { key: 'external_switch_counter_enabled', label: 'Count pulses instead of detecting activity', control: 'toggle', dependsOn: switchOn,
        help: 'When on, the device counts transitions from inactivity to activity (respecting the debounce) within the reporting interval.' },
      { key: 'external_switch_detection_reporting_interval', label: 'Periodic report', control: 'duration', unit: 's', zeroMeansOff: true, onDefault: 3600, dependsOn: switchOn,
        help: 'Interval for periodic status reports over LoRa. Activity and inactivity transitions are still sent immediately.' },
      { key: 'external_switch_send_inactivity_report', label: 'Report inactivity too', control: 'toggle',
        enabledWhen: { key: 'external_switch_detection_reporting_interval', gt: 0 }, reason: 'Only used with a periodic report.', dependsOn: switchOn,
        help: 'Send an inactivity report when the reporting interval expires without activity.' },
      {
        group: 'Input wiring',
        advanced: true,
        help: 'How the AN (GPIO) input is read. Match these to the connected switch.',
        fields: [
          { key: 'external_switch_detection_trigger_type', label: 'Active level', control: 'select', dependsOn: switchOn, help: 'Which logic level counts as activity.' },
          { key: 'external_switch_input_pull', label: 'Input pull', control: 'select', dependsOn: switchOn,
            help: 'Pull of the input line. If the switch provides its own pull, a wrong setting can raise power use or cause undefined behaviour.' },
          { key: 'external_switch_detection_gpio_pin_power_enabled', label: 'Power the switch from the GPIO pin', control: 'toggle', dependsOn: switchOn, help: 'Use the GPIO output of the fence port to enable (power) the external switch.' },
          { key: 'external_switch_detection_trigger_debounce_ms', label: 'Debounce', unit: 'ms', dependsOn: switchOn,
            help: 'Time after a state change during which further changes are ignored; the input is then re-read to confirm. 0 disables debouncing (not recommended).' },
          { key: 'external_switch_minimal_report_duration_ms', label: 'Minimum activity to report', unit: 'ms', dependsOn: switchOn,
            help: 'Minimum activity duration before a report is sent, to avoid flooding the LoRa queue with short detections.' },
        ],
      },
    ],
  };

  const airQuality = {
    id: 'air-quality',
    title: 'Air quality',
    icon: 'temperature',
    description: 'The BME690 and BMV080 air quality sensors, only on rangeredge boards running the air quality firmware.',
    fields: [
      { key: 'air_quality_enabled', label: 'Air quality sensor', control: 'toggle', help: 'Enable the BME690 and BMV080 air quality sensors. Only available on rangeredge boards running the air quality firmware.' },
      { key: 'air_quality_interval', label: 'Measure', control: 'duration', unit: 's', dependsOn: { key: 'air_quality_enabled', truthy: true },
        help: 'How often the tracker checks for new air quality data and packs it into a message. The sensors sample on a fixed 5-minute duty cycle.' },
    ],
  };

  // LP0 offload clusters (firmware 8.2, beta): a tracker sends its saved
  // records over plain LoRa to an offload station that stores them on a microSD card. The
  // role, slot, count, channel span and discovery interval are the five bytes of
  // lp0_node_params; the radio parameters are the four bytes of lp0_communication_params;
  // the signal checks are the six bytes of lp0_signal_checks (docs/lp0-offload/README.md and
  // app/src/lp0/README.md in the firmware repository).
  const lp0Role = { key: 'lp0_node_params', byte: 0 };
  const lp0Station = { ...lp0Role, equals: 2 };
  const lp0Tracker = { ...lp0Role, equals: 1 };
  const lp0RoleOn = { ...lp0Role, in: [1, 2] };
  const lp0NotTracker = { not: lp0Tracker };
  const lp0NotStation = { not: lp0Station };
  const lp0ChecksOn = { key: 'lp0_signal_checks', byte: 0, equals: 1 };
  const onOff = [{ value: 0, label: 'Off' }, { value: 1, label: 'On' }];
  const lp0Offload = {
    id: 'lp0',
    title: 'LP0 offload',
    icon: 'file-arrow-up',
    beta: true,
    minFirmware: { major: 8, minor: 1 },
    requires: ['lp0_master_key', 'lp0_node_params', 'lp0_signal_checks'],
    description: 'Beta, firmware 8.2 pre-release builds only. A tracker sends its saved records over LoRa to an offload station, which stores them on a microSD card. Every tracker and station in a cluster needs the same master key, radio parameters, station count and channel span. Which message types go over LP0 is set in Data sending and storing; manual offloads, log cleanup and the station status are in the LP0 offload card.',
    summary: 'lp0',
    fields: [
      { key: 'lp0_node_params', byte: 0, control: 'byte', label: 'Role',
        options: [{ value: 0, label: 'Off (no offloading)' }, { value: 1, label: 'Tracker (sends its saved records)' }, { value: 2, label: 'Offload station (stores records on its SD card)' }],
        help: 'Off still allows ordinary sending over LP0. The station role needs RangerEdge firmware with SD card support; air quality builds have no LP0 offloading.' },
      { key: 'lp0_node_params', byte: 1, control: 'byte', label: 'Station ID', min: 0, max: 254, enabledWhen: lp0NotTracker, reason: 'Only used by an offload station.', dependsOn: lp0RoleOn,
        help: 'Response slot of this station: 0 up to the station count minus one. Nearby stations need different IDs or their replies collide. Trackers leave it at 0.' },
      { key: 'lp0_node_params', byte: 2, control: 'byte', label: 'Station count', min: 1, max: 255, dependsOn: lp0RoleOn,
        help: 'Number of discovery response slots for nearby stations, 10 by default. Every tracker and station in the cluster must use the same count; it is capacity for stations, not for trackers.' },
      { key: 'lp0_node_params', byte: 4, control: 'byte', label: 'Discovery interval', unit: 's', min: 0, max: 255, enabledWhen: lp0NotStation, reason: 'Only used by a tracker.', dependsOn: lp0RoleOn,
        help: 'How often a tracker looks for a station, 60 s by default. 0 means as soon as LP0 is idle. Scheduling, random delays and retry backoff make the real wait longer.' },
      { key: 'lp0_discovery_retry_count', label: 'Discovery retries', unit: 'per interval', min: 0, max: 255, enabledWhen: lp0NotStation, reason: 'Only used by a tracker.', dependsOn: lp0RoleOn,
        help: 'Extra attempts a tracker may make within one discovery interval after a failed attempt, 0 by default: one attempt per interval, then wait for the next. Retries follow a short randomised delay that doubles up to eight times the listen window. Added in the 2026-10-28 schema.' },
      { key: 'lp0_master_key', control: 'hex', secret: true, generate: true, copy: true, label: 'Cluster master key',
        help: 'One random 16-byte key shared by every tracker and station in the cluster. Generate it once, write the same key to every device and store it safely; a device with another key cannot join. Exported only when credentials are included.',
        warnings: [{ when: { key: 'lp0_master_key', in: ['00000000000000000000000000000000', ''] },
          text: 'All zeros is the public default key. Generate a random key for a real deployment and write it to every device in the cluster.' }] },
      { key: 'lp0_focus_offloading', control: 'toggle', label: 'Focus on offloading',
        help: 'When on, routine GPS fixes, scans and scheduled radio sends wait while an offload is prepared and running. Turn it on on both the tracker and the station for a dedicated offload session; the defaults are enough for ordinary use.' },
      { key: 'lp0_gps_before_start', control: 'toggle', label: 'GPS fix before offloading',
        help: 'Take a u-blox GPS fix before an offload session starts so the clock is set from the receiver. Meant for offload stations, which timestamp the records they store on the SD card; off by default.' },
      { key: 'lp0_statistics_interval', control: 'duration', unit: 's', zeroMeansOff: true, onDefault: 3600, label: 'Station statistics report', enabledWhen: lp0NotTracker, reason: 'Only an offload station sends statistics.', dependsOn: lp0RoleOn,
        help: 'How often the station reports its counters and SD card state on port 23, 1 hour by default. Tick port 23 under Data sending and storing to send or store the report; a device updated from 8.0 keeps its old masks.',
        warnings: [{ when: { all: [{ key: 'lp0_statistics_interval', gt: 0 }, { key: 'lp0_statistics_interval', lt: 60 }] }, text: 'The firmware rejects intervals under 60 seconds.' }] },
      {
        group: 'Radio',
        advanced: true,
        help: 'Must match on every device in the cluster. The defaults are the EU868 setup: SF7, 250 kHz, coding rate 4/5, 1 second, 869.150 MHz.',
        fields: [
          { key: 'lp0_tx_frequency_hz', label: 'Transmit frequency', unit: 'Hz', help: 'Discovery and ordinary LP0 messages. During an offload the devices switch by themselves to a channel derived from the station ID.' },
          { key: 'lp0_rx_frequency_hz', label: 'Receive frequency', unit: 'Hz', help: 'Discovery and ordinary LP0 messages; usually the same as the transmit frequency.' },
          { key: 'lp0_communication_params', byte: 0, control: 'byte', label: 'Spreading factor',
            options: [5, 6, 7, 8, 9, 10, 11, 12].map(sf => ({ value: sf, label: `SF${sf}` })) },
          { key: 'lp0_communication_params', byte: 1, control: 'byte', label: 'Bandwidth',
            options: [{ value: 0x08, label: '10.42 kHz' }, { value: 0x01, label: '15.63 kHz' }, { value: 0x09, label: '20.83 kHz' }, { value: 0x02, label: '31.25 kHz' },
              { value: 0x0A, label: '41.67 kHz' }, { value: 0x03, label: '62.5 kHz' }, { value: 0x04, label: '125 kHz' }, { value: 0x05, label: '250 kHz' }, { value: 0x06, label: '500 kHz' },
              { value: 0x0D, label: '203 kHz (2.4 GHz chips only)' }, { value: 0x0E, label: '406 kHz (2.4 GHz chips only)' }, { value: 0x0F, label: '812 kHz (2.4 GHz chips only)' }] },
          { key: 'lp0_communication_params', byte: 2, control: 'byte', label: 'Coding rate',
            options: [{ value: 0, label: 'None' }, { value: 1, label: '4/5' }, { value: 2, label: '4/6' }, { value: 3, label: '4/7' }, { value: 4, label: '4/8' },
              { value: 5, label: '4/5 long interleaver' }, { value: 6, label: '4/6 long interleaver' }, { value: 7, label: '4/8 long interleaver' }] },
          { key: 'lp0_communication_params', byte: 3, control: 'byte', label: 'Listen window after a transmit', unit: 's', min: 0, max: 255,
            help: 'How long a device listens for replies after it has sent. Station offers are spread over this window, so it must be the same on every device.' },
          { key: 'lp0_node_params', byte: 3, control: 'byte', label: 'Offload channel span',
            options: [{ value: 1, label: 'Frequency span of the LoRaWAN region' }, { value: 0, label: 'Full 863 to 923 MHz span' }],
            help: 'Which band the offload channels are spread over. Every device in the cluster must match.' },
        ],
      },
      {
        group: 'Signal checks',
        advanced: true,
        help: 'Radio checks a device runs before it takes part in an offload. A change applies to the next offload visit.',
        fields: [
          { key: 'lp0_signal_checks', byte: 0, control: 'byte', label: 'All signal checks', options: onOff, help: 'Off bypasses the three checks below but keeps their values.' },
          { key: 'lp0_signal_checks', byte: 1, control: 'byte', label: 'Channel activity (CAD) veto', options: onOff, dependsOn: lp0ChecksOn, help: 'Do not transmit while the channel is in use.' },
          { key: 'lp0_signal_checks', byte: 2, control: 'byte', label: 'Minimum RSSI check', options: onOff, dependsOn: lp0ChecksOn,
            help: 'Ignore discovery packets weaker than the minimum below, and stop after three consecutive weak packets.' },
          { key: 'lp0_signal_checks', byte: 3, control: 'byte', label: 'Minimum RSSI', unit: 'dBm below zero', min: 0, max: 125,
            dependsOn: { all: [lp0ChecksOn, { key: 'lp0_signal_checks', byte: 2, equals: 1 }] },
            help: 'Entered as a positive number: 100 means -100 dBm. A larger number admits weaker packets; 0 is a real threshold of 0 dBm, not off.' },
          { key: 'lp0_signal_checks', byte: 4, control: 'byte', label: 'Background margin check', options: onOff, dependsOn: lp0ChecksOn,
            help: 'Require a packet to be stronger than the background noise by the margin below. Off by default since the 2026-11-03 schema; the threshold stays stored.' },
          { key: 'lp0_signal_checks', byte: 5, control: 'byte', label: 'Minimum margin', unit: 'dB', min: 0, max: 127,
            dependsOn: { all: [lp0ChecksOn, { key: 'lp0_signal_checks', byte: 4, equals: 1 }] },
            help: 'Packet strength above the background, 20 dB by default.' },
        ],
      },
      {
        group: 'Device payload keys',
        advanced: true,
        help: 'Keys this device uses for its own LP0 payloads. A station stores payloads encrypted and never needs them. Keep the provisioned values and record them with the device EUI in the backend, since the archives are decoded with them. Exported only when credentials are included.',
        fields: [
          { key: 'lp0_dev_addr', control: 'hex', copy: true, label: 'LP0 device address', help: '4 bytes that identify this device in its payload frames.' },
          { key: 'lp0_app_key', control: 'hex', secret: true, copy: true, label: 'LP0 app key', help: '16 bytes; encrypts this device\'s payloads.' },
          { key: 'lp0_network_key', control: 'hex', secret: true, copy: true, label: 'LP0 network key', help: '16 bytes; protects the integrity of this device\'s payloads.' },
        ],
      },
    ],
  };

  const sensors = {
    id: 'sensors',
    title: 'Sensors',
    icon: 'accelerometer',
    description: 'Accelerometer settings.',
    fields: [
      {
        group: 'Accelerometer',
        fields: [
          { key: 'accel_odr_hz', label: 'Sample rate', unit: 'Hz', help: 'Output data rate in Hertz.' },
          { key: 'accel_g_scale', label: 'Range', unit: 'g', help: 'Accelerometer measurement range.' },
          { key: 'accel_movement_data_fifo_enabled', label: 'Movement data FIFO', control: 'toggle', help: 'Enable the accelerometer movement data FIFO.' },
        ],
      },
    ],
  };

  return {
    version: 5,
    panels: [positioning, dataSending, network, device, satellite, sBand, lp0Offload, vhf, wifiScanning, bleScanning, cmdq, fence, externalSwitch, airQuality, sensors],
    portLabels,
    // Settings blocks inside the older feature cards that a panel now covers.
    supersededSections: [
      { elementId: 'cmdq-settings-section', key: 'cmdq_enabled' },
      { elementId: 'fence-settings-section', key: 'fence_enabled' },
      { elementId: 'wifi-scan-settings-section', key: 'wifi_scan_interval' },
      { elementId: 'ble-scan-settings-section', key: 'ble_scan_interval' },
    ],
  };
}));
