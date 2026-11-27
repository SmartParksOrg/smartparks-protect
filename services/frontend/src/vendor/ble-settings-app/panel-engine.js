// Panel engine: a draft of pending setting changes, condition evaluation for
// panel definitions, dependency-aware write ordering, and an apply runner that
// writes each setting and reads it back. Pure logic, no DOM: loaded as a classic
// script in the browser (window.PanelEngine) and required directly in Node tests.
(function (root, factory) {
  const api = factory();
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  } else {
    root.PanelEngine = api;
  }
}(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  function toBool(value) {
    if (value === true || value === false) return value;
    if (value === null || value === undefined) return false;
    if (typeof value === 'number') return value !== 0;
    const text = String(value).trim().toLowerCase();
    if (text === '' || text === 'false' || text === '0' || text === 'off' || text === 'no') return false;
    if (text === 'true' || text === 'on' || text === 'yes') return true;
    const number = Number(text);
    return Number.isFinite(number) ? number !== 0 : true;
  }

  function toNumber(value) {
    if (typeof value === 'number') return value;
    if (value === true) return 1;
    if (value === false) return 0;
    const number = Number(String(value ?? '').trim());
    return Number.isFinite(number) ? number : NaN;
  }

  function sameValue(actual, expected) {
    if (typeof expected === 'boolean') return toBool(actual) === expected;
    if (typeof expected === 'number') return toNumber(actual) === expected;
    return String(actual ?? '') === String(expected ?? '');
  }

  // Byte-array settings are hex strings ("07050101", or "{0x07,0x05,...}" straight from a
  // schema default). byteAt reads one byte of such a value; setByte writes one back and
  // returns the full upper-case hex string, padded or cut to `length` bytes.
  function hexDigits(value) {
    return String(value ?? '').replace(/0x/gi, '').replace(/[^0-9a-fA-F]/g, '').toUpperCase();
  }

  function byteAt(value, index) {
    const hex = hexDigits(value);
    if (!Number.isInteger(index) || index < 0 || hex.length < (index + 1) * 2) return NaN;
    return parseInt(hex.substr(index * 2, 2), 16);
  }

  function setByte(value, index, byte, length) {
    const size = Number.isInteger(length) && length > 0 ? length : Math.max(index + 1, hexDigits(value).length / 2);
    const current = hexDigits(value).padEnd(size * 2, '0').slice(0, size * 2);
    const clamped = Math.min(255, Math.max(0, Math.round(toNumber(byte)) || 0));
    const text = clamped.toString(16).padStart(2, '0').toUpperCase();
    return current.slice(0, index * 2) + text + current.slice(index * 2 + 2);
  }

  // Condition forms: true/false, { key, equals | notEquals | in | truthy | gt | gte | lt | lte },
  // optionally with `byte: n` to test one byte of a byte-array setting instead of the whole value,
  // { all: [...] }, { any: [...] }, { not: condition }. getValue(key) returns the effective value.
  function evaluateCondition(condition, getValue) {
    if (condition === null || condition === undefined) return true;
    if (typeof condition === 'boolean') return condition;
    if (Array.isArray(condition.all)) return condition.all.every(item => evaluateCondition(item, getValue));
    if (Array.isArray(condition.any)) return condition.any.some(item => evaluateCondition(item, getValue));
    if (condition.not !== undefined) return !evaluateCondition(condition.not, getValue);
    if (!condition.key) return true;
    const value = Number.isInteger(condition.byte) ? byteAt(getValue(condition.key), condition.byte) : getValue(condition.key);
    if ('equals' in condition) return sameValue(value, condition.equals);
    if ('notEquals' in condition) return !sameValue(value, condition.notEquals);
    if (Array.isArray(condition.in)) return condition.in.some(candidate => sameValue(value, candidate));
    if ('truthy' in condition) return toBool(value) === Boolean(condition.truthy);
    if ('gt' in condition) return toNumber(value) > condition.gt;
    if ('gte' in condition) return toNumber(value) >= condition.gte;
    if ('lt' in condition) return toNumber(value) < condition.lt;
    if ('lte' in condition) return toNumber(value) <= condition.lte;
    return true;
  }

  function conditionKeys(condition, into = new Set()) {
    if (!condition || typeof condition !== 'object') return into;
    if (condition.key) into.add(condition.key);
    (condition.all || []).forEach(item => conditionKeys(item, into));
    (condition.any || []).forEach(item => conditionKeys(item, into));
    if (condition.not) conditionKeys(condition.not, into);
    return into;
  }

  // Walk a panel definition's fields, including nested groups, yielding leaf fields.
  function walkFields(fields, visit, context = {}) {
    (fields || []).forEach(field => {
      if (Array.isArray(field.fields)) {
        walkFields(field.fields, visit, { group: field, inherited: mergeConditions(context.inherited, field.enabledWhen, field.visibleWhen, field.dependsOn) });
        return;
      }
      visit(field, context);
    });
  }

  function mergeConditions(...conditions) {
    const present = conditions.filter(condition => condition !== undefined && condition !== null);
    if (!present.length) return null;
    return present.length === 1 ? present[0] : { all: present };
  }

  function fieldKeys(field) {
    if (Array.isArray(field.keys)) return field.keys.slice();
    return field.key ? [field.key] : [];
  }

  // For each setting key: the keys that gate it (from enabledWhen/visibleWhen/dependsOn,
  // including enclosing groups) and the keys it must be written after. dependsOn only orders
  // writes; it never disables a field (a feature's settings can be prepared while it is off).
  function collectFieldRules(definitions) {
    const rules = new Map();
    const ensure = key => {
      if (!rules.has(key)) rules.set(key, { gates: new Set(), writeAfter: new Set() });
      return rules.get(key);
    };
    const panels = Array.isArray(definitions) ? definitions : (definitions && definitions.panels) || [];
    panels.forEach(panel => {
      walkFields(panel.fields, (field, context) => {
        const gating = conditionKeys(mergeConditions(context.inherited, field.enabledWhen, field.visibleWhen, field.dependsOn));
        fieldKeys(field).forEach(key => {
          const rule = ensure(key);
          gating.forEach(gate => { if (gate !== key) rule.gates.add(gate); });
          (field.writeAfter || []).forEach(after => { if (after !== key) rule.writeAfter.add(after); });
        });
      });
    });
    return rules;
  }

  // Order changes so that dependents are written before a gate that turns on, and after a
  // gate that turns off, plus any explicit writeAfter. Stable for unrelated keys. Falls back
  // to the given order if the constraints form a cycle.
  function planWriteOrder(changes, definitions) {
    const list = (changes || []).map((change, index) => ({ ...change, __index: index }));
    const rules = collectFieldRules(definitions);
    const byKey = new Map(list.map(change => [change.key, change]));
    const precedes = new Map(list.map(change => [change.key, new Set()])); // key -> keys that must come before it
    list.forEach(change => {
      const rule = rules.get(change.key);
      if (!rule) return;
      rule.gates.forEach(gate => {
        if (!byKey.has(gate)) return;
        if (toBool(byKey.get(gate).value)) {
          precedes.get(gate).add(change.key); // dependent first, then the gate that enables it
        } else {
          precedes.get(change.key).add(gate); // gate off first, then the dependent
        }
      });
      rule.writeAfter.forEach(after => {
        if (byKey.has(after)) precedes.get(change.key).add(after);
      });
    });
    const remaining = new Set(list.map(change => change.key));
    const ordered = [];
    while (remaining.size) {
      const ready = list
        .filter(change => remaining.has(change.key))
        .filter(change => Array.from(precedes.get(change.key)).every(dep => !remaining.has(dep)));
      if (!ready.length) {
        return list.map(({ __index, ...change }) => change); // cycle: keep the original order
      }
      ready.sort((a, b) => a.__index - b.__index);
      const next = ready[0];
      remaining.delete(next.key);
      ordered.push(next);
    }
    return ordered.map(({ __index, ...change }) => change);
  }

  function createDraft() {
    const entries = new Map();
    const listeners = new Set();
    const draft = {
      set(key, entry) {
        entries.set(key, { ...(entries.get(key) || {}), ...entry, key });
        notify();
      },
      clear(key) {
        if (entries.delete(key)) notify();
      },
      reset() {
        if (!entries.size) return;
        entries.clear();
        notify();
      },
      get(key) { return entries.get(key) || null; },
      has(key) { return entries.has(key); },
      get size() { return entries.size; },
      keys() { return Array.from(entries.keys()); },
      entries() { return Array.from(entries.values()); },
      invalidCount() { return Array.from(entries.values()).filter(entry => entry.valid === false).length; },
      subscribe(listener) {
        listeners.add(listener);
        return () => listeners.delete(listener);
      },
    };
    function notify() { listeners.forEach(listener => listener(draft)); }
    return draft;
  }

  // Write each item, then read it back and compare. Statuses: verified, mismatch,
  // unverified (no read-back available), failed (write or read threw).
  async function runApply({ items, write, read, isEqual, onItem, settleMs = 150 }) {
    const summary = { total: items.length, verified: 0, mismatch: 0, unverified: 0, failed: 0, results: [] };
    for (let index = 0; index < items.length; index += 1) {
      const item = items[index];
      let status = 'failed';
      let readValue = null;
      let error = null;
      try {
        await write(item);
        if (settleMs > 0) await new Promise(resolve => setTimeout(resolve, settleMs));
        if (typeof read === 'function') {
          readValue = await read(item);
          if (readValue === null || readValue === undefined) {
            status = 'unverified';
          } else {
            status = isEqual(item, readValue) ? 'verified' : 'mismatch';
          }
        } else {
          status = 'unverified';
        }
      } catch (caught) {
        error = caught;
        status = 'failed';
      }
      summary[status] += 1;
      summary.results.push({ item, status, readValue, error });
      if (typeof onItem === 'function') {
        await onItem({ index, item, status, readValue, error });
      }
    }
    return summary;
  }

  // Which option of a mode/choice field matches the effective values; null when none does.
  function resolveOption(field, getValue) {
    const options = Array.isArray(field.options) ? field.options : [];
    return options.find(option => evaluateCondition(option.when, getValue)) || null;
  }

  // Values to write when an option is chosen: its `set` values, plus `ensure` values for
  // keys whose current value is empty or zero (so "Fixed interval" never leaves 0 = off).
  function optionWrites(option, getValue) {
    const writes = [];
    Object.entries(option.set || {}).forEach(([key, value]) => writes.push({ key, value }));
    Object.entries(option.ensure || {}).forEach(([key, value]) => {
      const current = getValue(key);
      const number = toNumber(current);
      if (current === null || current === undefined || String(current).trim() === '' || number === 0) {
        writes.push({ key, value });
      }
    });
    return writes;
  }

  // A "switch" field turns a feature on or off by writing several settings.
  //   { control: 'switch', keys, on: <condition>, turnOff: { key: value }, turnOn: { ensure: { key: value } } }
  // Turning off writes turnOff. Turning on restores the values remembered when it was
  // turned off (for the turnOff keys), then applies turnOn.ensure where a value is still
  // empty or zero.
  function isSwitchOn(field, getValue) {
    return evaluateCondition(field.on, getValue);
  }

  function switchWrites(field, turnOn, getValue, remembered) {
    if (!turnOn) {
      return Object.entries(field.turnOff || {}).map(([key, value]) => ({ key, value }));
    }
    const writes = [];
    const restored = {};
    Object.keys(field.turnOff || {}).forEach(key => {
      const previous = remembered ? remembered[key] : undefined;
      if (previous !== undefined && previous !== null && String(previous) !== '') {
        writes.push({ key, value: previous });
        restored[key] = previous;
      }
    });
    const ensure = (field.turnOn && field.turnOn.ensure) || {};
    Object.entries(ensure).forEach(([key, value]) => {
      const current = key in restored ? restored[key] : getValue(key);
      const number = toNumber(current);
      if (current === null || current === undefined || String(current).trim() === '' || number === 0 || current === false || current === 'false') {
        if (!(key in restored) || number === 0) {
          writes.push({ key, value });
        }
      }
    });
    return writes;
  }

  function formatDurationWords(totalSeconds) {
    const seconds = Math.round(toNumber(totalSeconds));
    if (!Number.isFinite(seconds) || seconds <= 0) return 'off';
    const units = [
      { size: 86400, singular: 'day', plural: 'days' },
      { size: 3600, singular: 'hour', plural: 'hours' },
      { size: 60, singular: 'minute', plural: 'minutes' },
      { size: 1, singular: 'second', plural: 'seconds' },
    ];
    const parts = [];
    let remaining = seconds;
    units.forEach(unit => {
      const count = Math.floor(remaining / unit.size);
      if (count > 0 && parts.length < 2) {
        parts.push(`${count} ${count === 1 ? unit.singular : unit.plural}`);
        remaining -= count * unit.size;
      }
    });
    return parts.join(' ');
  }

  function formatUtcHour(hour) {
    const value = Math.max(0, Math.min(23, Math.trunc(toNumber(hour)) || 0));
    return `${String(value).padStart(2, '0')}:00`;
  }

  // Segments (in percent of a 24 h bar) covered by the day window [start1, start2).
  function daySegments(start1, start2) {
    const a = Math.max(0, Math.min(23, Math.trunc(toNumber(start1)) || 0));
    const b = Math.max(0, Math.min(23, Math.trunc(toNumber(start2)) || 0));
    if (a === b) return [{ left: 0, width: 100 }];
    if (a < b) return [{ left: (a / 24) * 100, width: ((b - a) / 24) * 100 }];
    return [
      { left: (a / 24) * 100, width: ((24 - a) / 24) * 100 },
      { left: 0, width: (b / 24) * 100 },
    ];
  }

  // One or two plain sentences describing the positioning behaviour.
  // fmt.localTime(hour) may return a local clock time for a UTC hour, or null.
  function describePositioning(getValue, fmt = {}) {
    const has = key => getValue(key) !== null && getValue(key) !== undefined;
    const num = key => toNumber(getValue(key));
    const bool = key => toBool(getValue(key));
    const duration = fmt.duration || formatDurationWords;
    const hourLabel = hour => {
      const utc = `${formatUtcHour(hour)} UTC`;
      const local = fmt.localTime ? fmt.localTime(hour) : null;
      return local ? `${utc} (${local} local)` : utc;
    };
    const sentences = [];
    const multiple = has('ublox_multiple_intervals') && bool('ublox_multiple_intervals');
    const interval1 = has('ublox_send_interval') ? num('ublox_send_interval') : 0;
    const interval2 = has('ublox_send_interval_2') ? num('ublox_send_interval_2') : 0;
    const outdoorOn = has('outdoor_detection_enabled') && bool('outdoor_detection_enabled');
    const motionOn = has('enable_motion_trig_gps') && bool('enable_motion_trig_gps');
    if (multiple) {
      const first = interval1 > 0 ? `every ${duration(interval1)}` : 'no fixes';
      const second = interval2 > 0 ? `every ${duration(interval2)}` : 'no fixes';
      sentences.push(`Fix ${first} from ${hourLabel(getValue('ublox_interval1_start'))} to ${hourLabel(getValue('ublox_interval2_start'))}, and ${second} the rest of the day.`);
    } else if (interval1 > 0) {
      sentences.push(`Fix every ${duration(interval1)}, all day.`);
    } else {
      sentences.push('Scheduled fixes are off.');
      if (outdoorOn || motionOn) {
        sentences.push('Motion-triggered and outdoor detection have no effect while scheduled fixes are off.');
      }
      if (has('gps_resend_interval') && num('gps_resend_interval') > 0) {
        sentences.push(`The last position is resent every ${duration(num('gps_resend_interval'))}.`);
      }
      return sentences.join(' ');
    }
    if (outdoorOn) {
      sentences.push('Fixes are only attempted when the tracker is probably outdoors.');
    }
    if (motionOn) {
      const windowSeconds = has('gps_triggered_interval') ? num('gps_triggered_interval') : 0;
      const needed = has('gps_motion_triggered_min_num_of_triggers_per_interval') ? num('gps_motion_triggered_min_num_of_triggers_per_interval') : 0;
      if (windowSeconds > 0 && needed > 0) {
        sentences.push(`A fix is taken after ${needed} movement${needed === 1 ? '' : 's'} within ${duration(windowSeconds)}; scheduled fixes are not taken in this mode.`);
      } else {
        const skips = has('gps_skipped_triggered_interval') ? num('gps_skipped_triggered_interval') : 0;
        sentences.push(skips > 0
          ? `While the tracker is still, up to ${skips} scheduled fix${skips === 1 ? ' is' : 'es are'} skipped.`
          : 'While the tracker is still, scheduled fixes are still taken.');
      }
    }
    if (has('ublox_active_tracking') && bool('ublox_active_tracking')) {
      sentences.push('The receiver stays on between fixes and reports heading and speed.');
    }
    if (has('gps_resend_interval') && num('gps_resend_interval') > 0) {
      sentences.push(`The last position is resent every ${duration(num('gps_resend_interval'))}.`);
    }
    return sentences.join(' ');
  }

  // Generic day/night schedule summary shared by satellite and VHF panels.
  // cfg: { enabledKey, interval1Key, multipleKey, start1Key, interval2Key, start2Key, verb, subject }
  function describeSchedule(getValue, cfg, fmt = {}) {
    const has = key => key && getValue(key) !== null && getValue(key) !== undefined;
    const num = key => toNumber(getValue(key));
    const duration = fmt.duration || formatDurationWords;
    const hourLabel = hour => {
      const utc = `${formatUtcHour(hour)} UTC`;
      const local = fmt.localTime ? fmt.localTime(hour) : null;
      return local ? `${utc} (${local} local)` : utc;
    };
    const verb = cfg.verb || 'Send';
    const subject = cfg.subject || 'This feature';
    if (has(cfg.enabledKey) && !toBool(getValue(cfg.enabledKey))) {
      return `${subject} is off.`;
    }
    const interval1 = has(cfg.interval1Key) ? num(cfg.interval1Key) : 0;
    const multiple = has(cfg.multipleKey) && toBool(getValue(cfg.multipleKey));
    if (multiple) {
      const interval2 = has(cfg.interval2Key) ? num(cfg.interval2Key) : 0;
      const first = interval1 > 0 ? `every ${duration(interval1)}` : 'nothing';
      const second = interval2 > 0 ? `every ${duration(interval2)}` : 'nothing';
      return `${verb} ${first} from ${hourLabel(getValue(cfg.start1Key))} to ${hourLabel(getValue(cfg.start2Key))}, and ${second} the rest of the day.`;
    }
    if (interval1 > 0) {
      return `${verb} every ${duration(interval1)}, all day.`;
    }
    return has(cfg.enabledKey) ? `${subject} is on but its interval is 0, so nothing is sent.` : `${subject} is off.`;
  }

  // The VHF beacon's timing as the firmware runs it (v8.0.3 lorawan.c, LORAWAN_EVENT_VHF_BURST,
  // and vhf.c): a burst is `vhf_num_of_packets_per_burst` continuous-wave pulses of
  // `vhf_single_pulse_duration_ms`, and after every pulse, the last one included, the radio is
  // quiet for `vhf_time_between_packets_ms`. Bursts start every `vhf_interval1` seconds (or
  // `vhf_interval2` in the night window); an interval under 1 s sends nothing. Only one burst is
  // queued at a time, so a burst that outlasts the interval pushes the next one back.
  // Values that are missing or not numbers fall back to the firmware defaults.
  const VHF_DEFAULTS = { count: 1, pulseMs: 18, gapMs: 250 };

  function vhfBeaconPattern(getValue) {
    const read = (key, fallback, min, max) => {
      const raw = getValue(key);
      if (raw === null || raw === undefined || String(raw).trim() === '') return fallback;
      const value = Math.round(toNumber(raw));
      if (!Number.isFinite(value)) return fallback;
      return Math.min(max, Math.max(min, value));
    };
    const count = read('vhf_num_of_packets_per_burst', VHF_DEFAULTS.count, 1, 255);
    const pulseMs = read('vhf_single_pulse_duration_ms', VHF_DEFAULTS.pulseMs, 1, 10000);
    const gapMs = read('vhf_time_between_packets_ms', VHF_DEFAULTS.gapMs, 0, 10000);
    const pulses = [];
    for (let i = 0; i < count; i += 1) pulses.push({ start: i * (pulseMs + gapMs), duration: pulseMs });
    const audibleMs = count * pulseMs + (count - 1) * gapMs; // first pulse start to last pulse end
    const busyMs = count * (pulseMs + gapMs); // the firmware also waits after the last pulse
    const periodFor = seconds => {
      const value = toNumber(seconds);
      if (!Number.isFinite(value) || value < 1) return null;
      return Math.max(value * 1000, busyMs);
    };
    const multiple = toBool(getValue('vhf_multiple_intervals'));
    const outlasts = seconds => {
      const value = toNumber(seconds);
      return Number.isFinite(value) && value >= 1 && value * 1000 < busyMs;
    };
    return {
      burstOutlastsInterval: outlasts(getValue('vhf_interval1')) || (multiple && outlasts(getValue('vhf_interval2'))),
      count,
      pulseMs,
      gapMs,
      pulses,
      audibleMs,
      busyMs,
      enabled: toBool(getValue('vhf_enabled')),
      multiple,
      periodMs: periodFor(getValue('vhf_interval1')),
      nightPeriodMs: multiple ? periodFor(getValue('vhf_interval2')) : null,
    };
  }

  function formatMilliseconds(ms) {
    if (ms < 1000) return `${Math.round(ms)} ms`;
    const seconds = ms / 1000;
    if (seconds < 60) return `${Number(seconds.toFixed(seconds < 10 ? 2 : 1))} s`;
    return formatDurationWords(seconds);
  }

  // "3 pulses of 18 ms, 250 ms apart (0.54 s), every 2 seconds."
  function describeVhfBeacon(pattern) {
    const p = pattern;
    const pulses = p.count === 1
      ? `1 pulse of ${formatMilliseconds(p.pulseMs)}`
      : `${p.count} pulses of ${formatMilliseconds(p.pulseMs)}, ${formatMilliseconds(p.gapMs)} apart (${formatMilliseconds(p.audibleMs)})`;
    const every = ms => (ms === null ? 'none' : `every ${formatDurationWords(Math.round(ms / 1000))}`);
    const when = p.multiple
      ? `day window ${every(p.periodMs)}, night ${every(p.nightPeriodMs)}`
      : (p.periodMs === null ? 'no bursts (interval 0)' : every(p.periodMs));
    const late = p.burstOutlastsInterval
      ? ' The burst lasts longer than the interval, so the next burst starts when this one ends.' : '';
    return `${pulses}; ${when}.${late}`;
  }

  // One or two sentences about how a fix attempt runs, from the fix-quality settings.
  function describeFixQuality(getValue, fmt = {}) {
    const has = key => getValue(key) !== null && getValue(key) !== undefined;
    const num = key => toNumber(getValue(key));
    const duration = fmt.duration || formatDurationWords;
    const sentences = [];
    if (has('cold_fix_timeout') || has('cold_fix_retry')) {
      const parts = [];
      if (has('cold_fix_timeout')) parts.push(`up to ${duration(num('cold_fix_timeout'))} per attempt`);
      if (has('cold_fix_retry')) parts.push(`${num('cold_fix_retry')} retr${num('cold_fix_retry') === 1 ? 'y' : 'ies'}`);
      sentences.push(`Cold fix: ${parts.join(', ')}.`);
    }
    if (has('hot_fix_timeout') || has('hot_fix_retry')) {
      const parts = [];
      if (has('hot_fix_timeout')) parts.push(`up to ${duration(num('hot_fix_timeout'))} per attempt`);
      if (has('hot_fix_retry')) parts.push(`${num('hot_fix_retry')} retr${num('hot_fix_retry') === 1 ? 'y' : 'ies'}`);
      sentences.push(`Hot fix: ${parts.join(', ')}.`);
    }
    if (has('ublox_min_satellites')) {
      const minimum = num('ublox_min_satellites');
      if (minimum > 0) {
        const timer = has('ublox_min_satellites_timer') ? num('ublox_min_satellites_timer') : null;
        if (timer !== null && timer < 5) {
          sentences.push(`Warning: the satellite check runs every second (timer ${timer} s, below the firmware minimum of 5 s) and can stop attempts before ${minimum} satellites are found.`);
        } else {
          const after = timer !== null ? ` after ${duration(timer)}` : '';
          sentences.push(`An attempt is abandoned${after} if fewer than ${minimum} satellites are visible.`);
        }
      } else {
        sentences.push('Attempts are not abandoned early for too few satellites.');
      }
    }
    if (has('horizontal_accuracy')) {
      sentences.push(`Accuracy target ${num('horizontal_accuracy')} m.`);
    }
    return sentences.join(' ');
  }

  // ---- GPS day timeline and hot/cold fixes ----------------------------------------------
  // A model of how the firmware schedules and runs GPS fixes (v8.0.3 gps.c: gps_send_interval,
  // gps_get_fix; communication.c: handle_ublox_gps), used by the Positioning panel's "Show the
  // day" and "Hot and cold fixes" views. What it follows:
  // - One attempt per interval. The interval counts from the END of an attempt
  //   (gps_update_last_fix_time runs after the fix); a non-zero interval under 30 s is 30 s.
  // - The first attempt after a restart, after a day/night window change (gps_reset_fix_state),
  //   after more than `hot_fix_retry` failed hot fixes in a row, and every
  //   `ublox_cold_fix_hour_interval` hours is a cold fix; the others are hot.
  // - A cold fix searches up to `cold_fix_timeout` and stays on `ublox_leave_on` after the fix;
  //   a hot fix searches up to `hot_fix_timeout` and runs at least `ublox_min_fix_time`.
  // - The retry settings count retries AFTER the first attempt (`retry > setting`), so 4 means
  //   5 failed hot fixes before a cold one.
  // - The satellite check runs every `ublox_min_satellites_timer` + 1 s and stops the attempt.
  // - Skip mode: a fix is skipped while nothing moved, at most `gps_skipped_triggered_interval`
  //   - 1 times in a row. Window mode (window and count both above 0): gps_send_interval returns
  //   before every scheduled fix, so only movement starts one.
  // - Active tracking keeps the receiver on; each interval reads a position, no hot/cold logic.
  // Open-sky search times are assumptions for drawing, not settings.
  const GPS_OPEN_SKY = { cold: 35, hot: 5, warm: 1.5 }; // seconds; warm = power on + buffer flush
  const GPS_MIN_INTERVAL = 30;
  const GPS_MAX_INTERVAL = 172800;

  function gpsSettings(getValue) {
    const present = key => { const v = getValue(key); return v !== null && v !== undefined && String(v).trim() !== ''; };
    const num = (key, fallback) => { if (!present(key)) return fallback; const v = toNumber(getValue(key)); return Number.isFinite(v) ? v : fallback; };
    const bool = key => present(key) && toBool(getValue(key));
    const hour = (key, fallback) => Math.min(23, Math.max(0, Math.round(num(key, fallback))));
    const motion = bool('enable_motion_trig_gps');
    const win = Math.max(0, num('gps_triggered_interval', 0));
    const need = Math.max(0, num('gps_motion_triggered_min_num_of_triggers_per_interval', 0));
    return {
      int1: Math.max(0, num('ublox_send_interval', 0)),
      int2: Math.max(0, num('ublox_send_interval_2', 0)),
      multi: bool('ublox_multiple_intervals'),
      start1: hour('ublox_interval1_start', 11),
      start2: hour('ublox_interval2_start', 19),
      active: bool('ublox_active_tracking'),
      outdoor: bool('outdoor_detection_enabled'),
      resend: Math.max(0, num('gps_resend_interval', 0)),
      motion,
      windowMode: motion && win > 0 && need > 0,
      win,
      need,
      maxSkip: Math.max(0, Math.round(num('gps_skipped_triggered_interval', 5))),
      coldT: Math.max(1, num('cold_fix_timeout', 200)),
      hotT: Math.max(1, num('hot_fix_timeout', 65)),
      leaveOn: Math.max(0, num('ublox_leave_on', 15)),
      minFix: Math.max(0, num('ublox_min_fix_time', 5)),
      coldH: Math.max(0, num('ublox_cold_fix_hour_interval', 0)),
      hotR: Math.max(0, Math.round(num('hot_fix_retry', 4))),
      coldR: Math.max(0, Math.round(num('cold_fix_retry', 200))),
      backoff: Math.max(10, num('gps_backoff_factor', 10)),
      minSats: Math.max(0, Math.round(num('ublox_min_satellites', 3))),
      satT: Math.max(0, Math.round(num('ublox_min_satellites_timer', 30))),
    };
  }

  // gps_check_time_interval_type: 1 = day interval, 2 = night interval, at UTC second t.
  function gpsIntervalType(S, t) {
    if (!S.multi) return 1;
    const h = Math.floor((((t % 86400) + 86400) % 86400) / 3600), a = S.start1, b = S.start2;
    let type = 1;
    if (h === b) type = 2;
    if (h === a) return 1;
    if ((h < a && h < b) || (h > a && h > b)) return a > b ? 1 : 2;
    if (h > a && h < b) type = 1;
    if (h < a && h > b) type = 2;
    return type;
  }

  function gpsInterval(S, type) {
    const v = type === 1 ? S.int1 : S.int2;
    return v > 0 && v < GPS_MIN_INTERVAL ? GPS_MIN_INTERVAL : v;
  }

  function gpsScheduled(S) {
    return S.int1 > 0 || (S.multi && S.int2 > 0);
  }

  // Seconds the receiver is on for one fix: with open sky, at most, and with no sky at all.
  function gpsFixTimes(S, kind) {
    const limit = kind === 'cold' ? S.coldT : S.hotT;
    const found = Math.min(limit, GPS_OPEN_SKY.warm + GPS_OPEN_SKY[kind]);
    const on = kind === 'cold' ? found + S.leaveOn : Math.min(limit, Math.max(found, S.minFix));
    const most = kind === 'cold' ? limit + S.leaveOn : limit;
    const noSky = S.minSats > 0 ? Math.min(limit, S.satT + 1) : limit;
    return { limit, warm: GPS_OPEN_SKY.warm, found, on, most, noSky };
  }

  // One local day (midnight to midnight, seconds) of fixes with every fix succeeding. The run
  // starts at a restart three days long and the middle day is returned, so it is an ordinary
  // day. utcOffsetSeconds: local time minus UTC. Skips are drawn for a collar that never moves.
  function gpsDayPlan(S, utcOffsetSeconds = 0) {
    const offset = Number.isFinite(utcOffsetSeconds) ? utcOffsetSeconds : 0;
    const horizon = 3 * 86400;
    const fixes = [], skips = [], resends = [];
    const scheduled = gpsScheduled(S) && !S.outdoor;
    let t = 0, lastTry = 0, first = false, coldDone = false, lastCold = -1e12, skipped = 0;
    let type = gpsIntervalType(S, 0);
    let nextResend = S.resend > 0 ? S.resend + 1 : Infinity;
    while (t < horizon) {
      if (t >= nextResend) { resends.push(t); nextResend = t + S.resend + 1; }
      if (!scheduled) { // nothing but resends: jump to the next one
        if (nextResend === Infinity) break;
        t = nextResend;
        continue;
      }
      let go = false;
      const nextType = gpsIntervalType(S, t);
      if (nextType !== type) { type = nextType; coldDone = false; skipped = 0; }
      const interval = gpsInterval(S, type);
      if (interval > 0) {
        if (!first) go = t > GPS_MIN_INTERVAL;
        else if (t - lastTry > interval) {
          if (S.windowMode) go = false;
          else if (S.motion) {
            if (skipped + 1 >= S.maxSkip) { skipped = 0; go = true; }
            else { skipped += 1; skips.push(t); lastTry = t; }
          } else go = true;
        }
      }
      if (go) {
        if (!S.active && coldDone && S.coldH > 0 && (t - lastCold) / 3600 >= S.coldH) coldDone = false;
        const kind = S.active ? 'read' : coldDone ? 'hot' : 'cold';
        const length = kind === 'read' ? 2 : gpsFixTimes(S, kind).on;
        if (kind === 'cold') { coldDone = true; lastCold = t; }
        fixes.push({ start: t, end: t + length, kind });
        first = true;
        lastTry = t + length;
        t = Math.ceil(t + length);
        continue;
      }
      t += 1;
    }
    const from = 86400 - offset, to = from + 86400;
    const shift = value => value - from;
    const windows = [];
    for (let m = 0; m < 1440; m += 15) {
      const windowType = gpsIntervalType(S, from + m * 60);
      const last = windows[windows.length - 1];
      if (last && last.type === windowType) last.to = (m + 15) * 60;
      else windows.push({ from: m * 60, to: (m + 15) * 60, type: windowType });
    }
    const dayFixes = fixes.filter(f => f.end > from && f.start < to).map(f => ({ start: shift(f.start), end: shift(f.end), kind: f.kind }));
    return {
      fixes: dayFixes,
      skips: skips.filter(v => v >= from && v < to).map(shift),
      resends: resends.filter(v => v >= from && v < to).map(shift),
      windows,
      onSeconds: S.active ? 86400 : dayFixes.reduce((sum, f) => sum + (f.end - f.start), 0),
    };
  }

  // Compact durations for the timeline: "45 s", "15 min", "1 h 30 min".
  function formatDurationShort(totalSeconds) {
    const sec = Math.round(toNumber(totalSeconds));
    if (!Number.isFinite(sec)) return '';
    if (sec < 60) return `${sec} s`;
    if (sec < 3600) { const m = Math.floor(sec / 60), s = sec % 60; return s ? `${m} min ${s} s` : `${m} min`; }
    const h = Math.floor(sec / 3600), m = Math.round((sec % 3600) / 60);
    return m ? `${h} h ${m} min` : `${h} h`;
  }

  // "59 fixes a day, GPS on about 7 min 54 s." Empty when the day cannot be drawn.
  function describeGpsDay(S, plan) {
    if (!gpsScheduled(S) || S.outdoor || S.windowMode) return '';
    if (S.active) return 'The GPS stays on all day.';
    const count = S.motion && S.maxSkip > 1 && plan.skips.length
      ? `${plan.fixes.length} to ${plan.fixes.length + plan.skips.length} fixes a day, depending on movement`
      : `${plan.fixes.length} fix${plan.fixes.length === 1 ? '' : 'es'} a day`;
    return `${count}, GPS on about ${formatDurationShort(plan.onSeconds)}.`;
  }

  // When the next fix is cold: [{ id, ... }] for the renderer to word (it knows local time).
  function gpsColdReasons(S) {
    const reasons = [{ id: 'restart' }];
    if (S.multi) reasons.push({ id: 'window', start1: S.start1, start2: S.start2 });
    reasons.push({ id: 'hot-failed', count: S.hotR + 1 });
    if (S.coldH > 0) reasons.push({ id: 'every', hours: S.coldH });
    reasons.push({ id: 'manual' });
    return reasons;
  }

  // What happens when the sky disappears: hot fixes fail one per interval, then a cold one
  // fails (backoff stretches the next wait), then the sky is back. null without a schedule.
  function gpsNoSkySequence(S) {
    const interval = gpsInterval(S, 1) || (S.multi ? gpsInterval(S, 2) : 0);
    if (S.active || S.windowMode || S.outdoor || !interval) return null;
    const hot = gpsFixTimes(S, 'hot'), cold = gpsFixTimes(S, 'cold');
    const steps = [];
    for (let i = 0; i <= S.hotR; i += 1) steps.push({ kind: 'hot', ok: false, wait: interval, seconds: hot.noSky });
    steps.push({ kind: 'cold', ok: false, wait: interval, seconds: cold.noSky });
    const grown = Math.min(GPS_MAX_INTERVAL, Math.floor(interval * S.backoff / 10));
    steps.push({ kind: 'cold', ok: true, wait: grown, seconds: cold.on, skyBack: true });
    steps.push({ kind: 'hot', ok: true, wait: interval, seconds: hot.on });
    return { interval, steps };
  }

  function optionLabel(fmt, key, value) {
    const options = fmt.options ? fmt.options(key) : null;
    if (Array.isArray(options)) {
      const match = options.find(option => String(option.value) === String(value));
      if (match) return match.label;
    }
    return value === null || value === undefined ? null : String(value);
  }

  // LoRaWAN data rate (DR0..DR15) to spreading factor and bandwidth per region, from the
  // LoRaWAN Regional Parameters RP002-1.0.4 uplink tables; region numbers are the firmware's
  // lr_region values. Entries the specification leaves undefined (RFU) are absent.
  const LORA = (sf, bw) => ({ sf, bw, label: `SF${sf} / ${bw} kHz` });
  const FSK50 = { label: 'FSK 50 kbps' };
  const LRFHSS = cr => ({ label: `LR-FHSS ${cr}` });
  const SF12_TO_7_125 = [LORA(12, 125), LORA(11, 125), LORA(10, 125), LORA(9, 125), LORA(8, 125), LORA(7, 125)];
  const SF12_TO_7_500 = [LORA(12, 500), LORA(11, 500), LORA(10, 500), LORA(9, 500), LORA(8, 500), LORA(7, 500)];
  const EU_LIKE = [...SF12_TO_7_125, LORA(7, 250), FSK50];
  const LORAWAN_DATA_RATES = {
    1: EU_LIKE,                                                     // EU 868
    2: EU_LIKE, 7: EU_LIKE, 8: EU_LIKE, 13: EU_LIKE,                // AS 923 groups 1-4
    3: [LORA(10, 125), LORA(9, 125), LORA(8, 125), LORA(7, 125), LORA(8, 500),
      LRFHSS('CR 1/3'), LRFHSS('CR 2/3'), undefined, ...SF12_TO_7_500], // US 915 (DR8-13 downlink)
    4: [...SF12_TO_7_125, LORA(8, 500), LRFHSS('CR 1/3'), ...SF12_TO_7_500], // AU 915 (DR8-13 downlink)
    5: [...SF12_TO_7_125, LORA(7, 500), FSK50],                     // CN 470
    12: [...SF12_TO_7_125],                                         // CN 470 RP 1.0
    6: [LORA(12, 812), LORA(11, 812), LORA(10, 812), LORA(9, 812), LORA(8, 812), LORA(7, 812)], // WW 2.4 GHz
    9: [...SF12_TO_7_125, undefined, FSK50],                        // IN 865
    10: [...SF12_TO_7_125],                                         // KR 920
    11: [...SF12_TO_7_125, LORA(7, 250), FSK50],                    // RU 864
  };
  const DOWNLINK_ONLY = { 3: [8, 9, 10, 11, 12, 13], 4: [8, 9, 10, 11, 12, 13] };

  // "SF9 / 125 kHz" for a region and data rate number, or null when the region is unknown
  // or the data rate is not defined there.
  function describeDataRate(region, dataRate) {
    const table = LORAWAN_DATA_RATES[toNumber(region)];
    const dr = toNumber(dataRate);
    if (!table || !Number.isInteger(dr) || dr < 0) return null;
    const entry = table[dr];
    if (!entry) return null;
    const downlink = (DOWNLINK_ONLY[toNumber(region)] || []).includes(dr);
    return downlink ? `${entry.label}, downlink only` : entry.label;
  }

  // Options for a data rate picker: every data rate the region defines, DR0 first.
  function dataRateOptions(region, maxDataRate = 15) {
    const table = LORAWAN_DATA_RATES[toNumber(region)] || [];
    const options = [];
    for (let dr = 0; dr <= maxDataRate && dr < table.length; dr += 1) {
      const text = describeDataRate(region, dr);
      if (text) options.push({ value: dr, label: `DR${dr} = ${text}` });
    }
    return options;
  }

  function describeNetwork(getValue, fmt = {}) {
    const has = key => getValue(key) !== null && getValue(key) !== undefined;
    const duration = fmt.duration || formatDurationWords;
    const sentences = [];
    if (has('lr_region')) sentences.push(`Region ${optionLabel(fmt, 'lr_region', getValue('lr_region'))}.`);
    if (has('lr_adr_profile')) {
      const profile = toNumber(getValue('lr_adr_profile'));
      const label = optionLabel(fmt, 'lr_adr_profile', getValue('lr_adr_profile'));
      if (profile === 3 && has('lr_adr')) {
        const dr = toNumber(getValue('lr_adr'));
        const sf = has('lr_region') ? describeDataRate(getValue('lr_region'), dr) : null;
        sentences.push(`Adaptive data rate: custom, DR${dr}${sf ? ` (${sf})` : ' (not defined for this region)'}.`);
      } else {
        sentences.push(`Adaptive data rate: ${label}.`);
      }
    }
    if (has('rejoin_interval')) sentences.push(`Rejoin attempts every ${duration(toNumber(getValue('rejoin_interval')))}.`);
    return sentences.join(' ');
  }

  function describeDevice(getValue, fmt = {}) {
    const has = key => getValue(key) !== null && getValue(key) !== undefined;
    const duration = fmt.duration || formatDurationWords;
    const sentences = [];
    if (has('device_name') && String(getValue('device_name')).trim()) sentences.push(`${String(getValue('device_name')).trim()}.`);
    if (has('device_pin')) {
      const digits = fmt.pinDigits ? fmt.pinDigits(getValue('device_pin')) : '';
      sentences.push(digits && digits !== '0000' ? 'Bluetooth PIN set.' : 'No Bluetooth PIN.');
    }
    if (has('led_enabled')) sentences.push(toBool(getValue('led_enabled')) ? 'Status LED on.' : 'Status LED off.');
    if (has('status_send_interval')) sentences.push(`Status report every ${duration(toNumber(getValue('status_send_interval')))}.`);
    return sentences.join(' ');
  }

  function portBit(portNumber) {
    return (1 << (portNumber - 1)) >>> 0;
  }

  function isPortSet(mask, portNumber) {
    return ((toNumber(mask) >>> 0) & portBit(portNumber)) !== 0;
  }

  function setPort(mask, portNumber, on) {
    const current = toNumber(mask) >>> 0;
    return (on ? (current | portBit(portNumber)) : (current & ~portBit(portNumber))) >>> 0;
  }

  // LP0 offload (firmware 8.2 beta): role and station slot from
  // lp0_node_params, master key presence, focus mode and the statistics interval.
  function describeLp0(getValue, fmt = {}) {
    const has = key => getValue(key) !== null && getValue(key) !== undefined;
    const duration = fmt.duration || formatDurationWords;
    if (!has('lp0_node_params')) return '';
    const node = getValue('lp0_node_params');
    const role = byteAt(node, 0);
    const slot = byteAt(node, 1);
    const count = byteAt(node, 2);
    const ping = byteAt(node, 4);
    const sentences = [];
    if (role === 1) {
      const retries = has('lp0_discovery_retry_count') ? toNumber(getValue('lp0_discovery_retry_count')) : 0;
      const retryText = retries > 0 ? `, up to ${retries} retr${retries === 1 ? 'y' : 'ies'} per interval` : '';
      sentences.push(`Tracker: looks for a station ${ping > 0 ? `every ${duration(ping)}` : 'as soon as LP0 is idle'}${retryText}, ${count} station slot${count === 1 ? '' : 's'}.`);
    } else if (role === 2) {
      sentences.push(`Offload station, ID ${slot} of ${count} slot${count === 1 ? '' : 's'}.`);
    } else {
      sentences.push('Offloading off.');
    }
    if (has('lp0_master_key')) {
      const key = hexDigits(getValue('lp0_master_key'));
      sentences.push(key && !/^0+$/.test(key) ? 'Cluster master key set.' : 'Cluster master key is the all-zero default.');
    }
    if (has('lp0_focus_offloading') && toBool(getValue('lp0_focus_offloading'))) sentences.push('Focus on offloading.');
    if (has('lp0_gps_before_start') && toBool(getValue('lp0_gps_before_start'))) sentences.push('GPS fix before offloading.');
    if (role === 2 && has('lp0_statistics_interval')) {
      const seconds = toNumber(getValue('lp0_statistics_interval'));
      sentences.push(seconds > 0 ? `Statistics every ${duration(seconds)}.` : 'Statistics off.');
    }
    return sentences.join(' ');
  }

  // ports: [{ name, number, label }]; columns: [{ key, label }]
  function describeDataFlags(getValue, ports, columns) {
    const parts = [];
    (columns || []).forEach(column => {
      const mask = getValue(column.key);
      if (mask === null || mask === undefined) return;
      const count = (ports || []).filter(port => isPortSet(mask, port.number)).length;
      parts.push(`${count} ${column.summaryLabel || column.label.toLowerCase()}`);
    });
    if (!parts.length) return '';
    return `Of ${(ports || []).length} message types: ${parts.join(', ')}.`;
  }

  return {
    toBool,
    toNumber,
    evaluateCondition,
    conditionKeys,
    walkFields,
    fieldKeys,
    collectFieldRules,
    planWriteOrder,
    createDraft,
    runApply,
    resolveOption,
    optionWrites,
    isSwitchOn,
    switchWrites,
    formatDurationWords,
    formatUtcHour,
    daySegments,
    describePositioning,
    describeSchedule,
    vhfBeaconPattern,
    describeVhfBeacon,
    formatMilliseconds,
    describeFixQuality,
    gpsSettings,
    gpsIntervalType,
    gpsInterval,
    gpsScheduled,
    gpsFixTimes,
    gpsDayPlan,
    describeGpsDay,
    gpsColdReasons,
    gpsNoSkySequence,
    formatDurationShort,
    describeNetwork,
    describeDataRate,
    dataRateOptions,
    describeDevice,
    describeDataFlags,
    describeLp0,
    hexDigits,
    byteAt,
    setByte,
    portBit,
    isPortSet,
    setPort,
  };
}));
