# neopool (Home Assistant core bd8b1bc) — bug candidates

Library: neopool-modbus==4.13.0 (manifest). Local checkout upstream/lib/neopool-modbus is tag v4.13.0
(02e3258) — same version. Reference: devices/sugarvalley/neopool.yaml and the Sugar Valley
"NeoPool Control System – MODBUS Register description" (2015-03-23, 44 pp., local copy
959a6e40…pdf). Page numbers below are the PDF's "Page n of 44" footers.

## 1. Chlorine flow binary sensor is inverted — medium-high
- Where: python-neopool-modbus src/neopool_modbus/status_mask.py:98
  (`"{unit} flow sensor problem": bool(status & 0x0008)`); HA binary_sensor.py:167-173
  ("Chlorine flow sensor problem", device_class PROBLEM, name "Chlorine flow sensor").
- Does: reports PROBLEM (on) when MBF_CL_STATUS (0x0109) bit 3 is set.
- Right: bit 3 is the chlorine probe's flow sensor; the document says that when it is 0 there is
  no water through the probe and the chlorine reading is invalid. So bit set = flow OK; bit clear = problem.
- Evidence: doc p.6, MBF_CL_STATUS bit 3 (0x0008); ModbusSpec neopool.yaml:278
  (cl_status '3': flow sensor, 0 = no flow, measurement invalid).
- Effect: "Chlorine flow sensor" shows Problem while water flows normally and OK when flow stops
  (exactly when the chlorine value is invalid). Alerts on it fire the wrong way round.

## 2. Timer / relay-mode writes that fail are reported as success — high (code bug)
- Where: library client.py `_perform_write_timer` returns False (lines 2281, 2323, 2340, 2354) on a
  Modbus exception for the block read, block write, EEPROM save or EXEC instead of raising;
  callers ignore the return: client.py:1929 (`async_set_relay_mode` -> returns optimistic dict anyway),
  HA time.py:336 (timer start/stop), HA select.py:186 (`_write_timer_period`), select.py relay mode
  via async_set_relay_mode.
- Effect: a rejected write (device busy, exception response, EEPROM-save failure) leaves HA showing
  the new start/stop time, period or relay mode as if applied; no error is raised to the user,
  and the next poll silently reverts it (or, if only EEPROM/EXEC failed, the change is lost at power-off).
- Evidence: code only.

## 3. Heating / Intelligent filtration modes offered without MBF_PAR_HEATING_MODE — medium
- Where: HA select.py:83-100 `_filt_mode_options` (gates heating=2/intelligent=4 only on
  has_heating_relay + is_temperature_active); same gate for heating/intelligent setpoint numbers
  (number.py:73-74, 180-205), clima switch (switch.py:202), intelligent selects/sensors
  (select.py:408, sensor.py:191, 203).
- Right: doc p.15 (MBF_PAR_FILT_MODE table): HEATING and INTELLIGENT are available only if
  MBF_PAR_HEATING_MODE (0x0414) = 1 **and** a heating relay is assigned. Doc p.18: heating relay
  defaults to relay 7, so has_heating_relay() is true on most units even without heating.
  The library's own `capabilities.available_filtration_modes` / `is_heating_mode_enabled` does check
  0x0414; HA doesn't use it.
- Effect: units without heating get Heating/Intelligent filtration modes, heating setpoints and
  climate switch; selecting them writes a mode the controller is not configured for.

## 4. Filtration mode 14 (chlorination shock) unknown — medium-low
- Where: library decoders.py:182-189 FILTRATION_MODE_LABELS (0-4, 13 only); HA sensor.py:136-142 and
  select.py:313-319 use it.
- Right: doc p.15-16 lists 14 = CHLORINATION SHOCK (started when the shock operation is activated).
  ModbusSpec neopool.yaml:261.
- Effect: during a chlorine shock the Filtration mode sensor and select show "unknown"
  (decode returns None).

## 5. Relay timer mode 5 (countdown) shows unknown — low
- Where: HA select.py relay_mode current_option/options (~720-745): handles 0, 2, 3, 4, else
  options_map {1,4}; value 5 -> None. Doc p.27 timer modes: 5 = CTIMER_COUNTDOWN.
- Effect: aux/light relay mode select shows unknown when the relay runs a countdown
  (library decode_aux_mode knows "countdown" but HA doesn't use it).

## 6. pH pump status: acid-only branch reads the other bit — low
- Where: library decoders.py:754-777 `decode_ph_pump_status`. Acid+base: bit 11 = acid, bit 12 = base.
  Acid-only (MBF_PAR_RELAY_PH = 1): reports "acid" from bit 12 (`pH pump active`).
- Doc p.5 (MBF_PH_STATUS): bit 11 = low-pH pump relay on, bit 12 = high-pH pump relay on; ModbusSpec
  neopool.yaml:276 reads 11 = acid, 12 = base. Whatever the document's wording means, the two branches
  contradict each other; one of them is wrong unless the firmware remaps bits in single-pump mode
  (not documented).
- Effect: "pH pump status" (diagnostic enum) may show idle while the acid pump runs in acid-only setups.

## Low / notes (not clear bugs)
- Ionization level (MBF_ION_CURRENT 0x0100) is labelled %, sensor.py:69-75. Doc p.3: value is scaled
  to MBF_PAR_ION_NOM (maximum ionization current), unit not given; % holds only if ION_NOM = 100. Low.
- Device sw_version uses MBF_PAR_VERSION (0x0300) — entity.py:34. Doc p.30: "No se utiliza" (not used).
  Cosmetic.
- Library reads MBF_PAR_HIDRO_MAX_VOLTAGE (0x0322) raw (client.py:1103); doc p.32 says tenths of V
  (default 80 = 8 V). HA doesn't expose it; only diagnostics/library users affected.
- Library timer write rewrites the whole 15-register block (incl. countdown +9 and work time +13
  read moments earlier, and writes 0 to undocumented +12); a running countdown / work-time counter
  can be set back by the write latency. Low.
- get_timer_interval (decoders.py:515-521) assumes OFFMB_TIMER_ON < 86400. Doc p.26 calls it a
  "timestamp"; if a unit stores an absolute epoch value there, editing only the stop time yields a
  negative interval. HA time.py reads `% 86400`, so it anticipates large values. Unverified, low.
- Relay activation delay (+10 s on read, -10 on write) matches doc p.25; ModbusSpec conflict is a
  representation difference only. Conductivity "%" — doc gives no unit; not a bug.

## Checked and matching the document
pH (0x0102 /100), redox (0x0103 raw mV; doc text says 1/100 ppm, ModbusSpec assumes mV — setpoint range
0-1000 fits mV), chlorine (0x0104 /100), temperature (0x0106 /10), pH alarm 0-5 (bits 0-3), RX/CL/CD status
bits 12-15, ION/HIDRO status bits, relay state bits 0-6 and AUX1-4 = relays 4-7, notification bits and clear,
FC04 for 0x01xx only, 31-register limit, time 0x0408/0x0409 low word first + 0x04F0 copy-to-RTC, GPIO
registers, filter-valve registers 0x04E8-0x04EF and modes 1/3/4, timer block layout and function codes
(light 2, AUX1-4 0x0800-0x4000), setpoint scaling/ranges PH1/PH2 (x100), RX1 0-1000, CL1 x100 0-1000,
cover reduction/shutdown temperature byte packing (0x042D), cover/temperature-shutdown bits (0x042C),
UV mode, clima, smart anti-freeze, intelligent min time (minutes), machine names 0-11, hydrolysis
%/g-h unit rule (0x0607 bits 13-15 + 0x0600), EEPROM save 0x02F0 / exec 0x02F5.
