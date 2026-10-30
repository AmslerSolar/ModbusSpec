# u5e findings: varta.yaml, victron-energy.yaml, victron-gx.yaml (evcc bf5c276)

No bugs found.

## victron-energy.yaml (checked against Victron dbus_modbustcp attributes.csv, commit 744e228, 2026-10-13; cross-checked in CCGX-Modbus-TCP-register-list 3.81)
- grid 820/821/822 int16 W unit 100: matches (attributes.csv l.341-343; list says + = import, so no inversion is right). ModbusSpec gx-system.yaml:83-85.
- grid currents 2617/2619/2621 int16 /10 on the grid meter unit: matches (attributes.csv l.467-471; gx-grid.yaml:72).
- pv 808-813 uint16 W + 850 uint16 W: matches (attributes.csv l.329-334, 361; gx-system.yaml:71-76, 101).
  Version note: u16 per phase caps at 65 535 W; 32-bit copies at 884-895 exist. PvOnGenset (814-816) not summed (not read, not a bug).
- battery 842 int16 W, Victron + = charge, evcc scale -1 -> + = discharge: right (attributes.csv l.354; gx-system.yaml:95).
- soc 843 uint16 %: matches (l.355).
- limitsoc write 2901 /Settings/CGwacs/BatteryLife/MinimumSocLimit uint16 scale 10, writable: matches (attributes.csv l.9; gx-settings.yaml:70).
- evcc reads with FC4 (input), ModbusSpec lists holding; the GX serves the same map on both, not a bug.

## victron-gx.yaml (com.victronenergy.acload)
- voltages 3910/3912/3914 uint16 /10, currents 3911/3913/3915 int16 /10, energy forward 3916/3918/3920 uint32 /100 kWh, power 3924/3926/3928 int32 W: all match (attributes.csv l.700-713; gx-acload.yaml:59-69). Block 3910 count 12 covers 3910-3921 correctly.

## varta.yaml
- 1066 int16 battery power (scale -1), 1068 SoC int16, 1078 grid power int16 (scale -1), 1102 PV sensor uint16, write 1074 max discharge (negative int16; 0 = hold).
- No VARTA manufacturer document in modbus-docs index or ModbusSpecArchive; ModbusSpec devices/varta/pulse.yaml:39-43 comes only from evcc + openWB. openWB (bat_modbus.py, counter.py, inverter.py) agrees on all addresses, types and signs (grid *-1; 1074 written -4000 / 0, u16 vs s16 is the same bit pattern). No independent reference.
