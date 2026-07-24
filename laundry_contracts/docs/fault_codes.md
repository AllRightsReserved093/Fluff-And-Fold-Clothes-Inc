# Laundry Equipment Diagnostic Code Reference

| Document status | Prototype |
|---|---|
| Applies to | Fluff & Fold washer and dryer monitoring system |
| Code format | `^[WFSD][0-9]{4}$` |

This reference defines the diagnostic codes displayed by the device and operator console. Prototype thresholds are for demonstration only and are not manufacturer specifications.

> Server analytics provide monitoring and diagnosis. Device safety interlocks and protective shutdowns must operate locally without depending on the server.

## Code Format

```text
PCNNN
```

| Position | Meaning |
|---|---|
| `P` | Diagnostic class: `W`, `F`, `S`, or `D` |
| `C` | Equipment category |
| `NNN` | Stable sequence number within the category |

| Prefix | Class | Meaning |
|---|---|---|
| `W` | Warning | Operation may continue, but attention is required |
| `F` | Fault | Equipment protection or repair action is required |
| `S` | System condition | Communication or server monitoring is impaired |
| `D` | Data event | Immutable data-quality or sequence record |

| Category | Applies to |
|---|---|
| `1` | Shared washer and dryer conditions |
| `2` | Washer conditions |
| `3` | Dryer conditions |
| `8` | Communication and monitoring |
| `9` | Data consistency |

## Quick Reference

| Code | Name | Class / Severity | Detected by | Equipment action | Reset |
|---|---|---|---|---|---|
| `W1001` | Excessive vibration | Warning / Medium | Server | None | Automatic |
| `F1101` | Door interlock lost | Fault / Critical | Device | Controlled stop | Manual |
| `W2101` | Washer water temperature high | Warning / Medium | Server | None | Automatic |
| `W3101` | Dryer air temperature high | Warning / High | Server | None | Automatic |
| `W3201` | Dryer air flow low | Warning / Medium | Server | None | Automatic |
| `F3102` | Dryer overtemperature trip | Fault / Critical | Device | Heating off and stop | Manual |
| `S8001` | Device communication lost | System condition / High | Server | None | Automatic |
| `D9001` | State report gap detected | Data event / Low | Server | None | Not applicable |
| `D9002` | State sequence mismatch | Data event / Medium | Server | None | Not applicable |

## Code Details

### W1001 — Excessive Vibration

- **Condition:** Reported vibration exceeds `10.0 m/s²`.
- **Effect:** Warning only; no server-initiated machine action.
- **Operator action:** Check load balance, mounting, and abnormal mechanical movement.
- **Clear:** Automatically after a later analyzed report returns to `10.0 m/s²` or below.

### F1101 — Door Interlock Lost

- **Condition:** The device reports loss of the door interlock during operation.
- **Effect:** Device performs a controlled stop and latches the fault.
- **Operator action:** Stop use and inspect the door, latch, switch, and wiring.
- **Clear:** Restore the safe condition, complete inspection, and manually reset the device.

### W2101 — Washer Water Temperature High

- **Condition:** Reported washer water temperature exceeds `80.0°C`.
- **Effect:** Warning only; no server-initiated machine action.
- **Operator action:** Check the selected cycle, water supply, heater control, and temperature sensor.
- **Clear:** Automatically after a later analyzed report returns to `80.0°C` or below.

### W3101 — Dryer Air Temperature High

- **Condition:** Reported dryer air temperature exceeds `90.0°C`.
- **Effect:** Warning only; no server-initiated machine action.
- **Operator action:** Check lint accumulation, exhaust airflow, fan operation, heater control, and temperature sensing.
- **Clear:** Automatically after a later analyzed report returns to `90.0°C` or below.

### W3201 — Dryer Air Flow Low

- **Condition:** Airflow is below `0.5 m/s` while the dryer reports `RUNNING`.
- **Effect:** Warning only; no server-initiated machine action.
- **Operator action:** Check the lint filter, exhaust path, ducting, and fan.
- **Clear:** Automatically when the condition is no longer present in a later analyzed report.

### F3102 — Dryer Overtemperature Trip

- **Condition:** The device reports an overtemperature protective trip; the simulator trips at `110.0°C`.
- **Effect:** Device disables heating, stops the cycle, and latches the fault.
- **Operator action:** Stop use and inspect airflow, fan operation, temperature sensing, and heater control.
- **Clear:** Complete repair and device reset after safe temperature and airflow are restored.

### S8001 — Device Communication Lost

- **Condition:** No accepted report is received for `16 seconds`.
- **Effect:** Server marks the machine offline without changing its reported physical operating state.
- **Operator action:** Check machine power, Ethernet connection, network configuration, and the reporting process.
- **Clear:** Automatically after the next accepted device report.

### D9001 — State Report Gap Detected

- **Condition:** A periodic report contains a state that differs from the stored snapshot.
- **Effect:** Server records an immutable data event and reconciles the current snapshot.
- **Operator action:** Review possible missing state reports or communication interruptions.
- **Clear:** Not applicable; the historical event remains recorded.

### D9002 — State Sequence Mismatch

- **Condition:** A state-change report names a previous state that differs from the stored snapshot.
- **Effect:** Server records an immutable data event with the expected and reported states.
- **Operator action:** Review report order, missing reports, and device state-transition logic.
- **Clear:** Not applicable; the historical event remains recorded.

## Diagnostic Lifecycle

- **Acknowledge** records that an operator has seen a warning, fault, or system condition; it does not resolve it.
- Server warnings and communication conditions resolve automatically after a later valid report clears the condition.
- Device faults remain active until the device sends a resolution report or an operator resolves the record manually.
- Data events are immutable historical records and do not have an active or resolved lifecycle.

## Implementation Notes

- The executable catalog is defined in `laundry_contracts/fault_codes.py`.
- Only codes in this document are generated by the built-in backend and simulator.
- The simulator's `blocked-vent` command is a test input; `F3102` reports the observed protective trip, not a confirmed root cause.
