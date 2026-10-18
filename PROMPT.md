================================================================================
MASTER SYSTEM SPECIFICATION FOR GITHUB COPILOT
PROJECT: HIL (Hardware-in-the-Loop) Testbench Discovery & Smart Scheduler
ARCHITECTURE: Clean Architecture + Repository Pattern + Tool-Calling LLM Agent
TECH STACK: Python 3.10+, Streamlit, Pandas, Pydantic v2, Google GenAI SDK (gemini-2.5-flash)
=============================================================================================

ROLE & OBJECTIVE:
You are a Principal Python Software Architect and Senior AI Engineer. Your task is to build a complete, modular, production-grade "HIL Testbench Discovery & Smart Scheduler" application.

You must implement EVERY file, class, method, docstring, type hint, and UI component specified in this document without skipping a single rule, formula, or edge case. Do NOT use placeholders, "TODO" comments, or stubbed logic for Phase 1 components.

Do NOT write scripts to generate dummy CSV files. Assume the 4 ground-truth CSV files already exist inside `data/raw/`.

================================================================================

1. # EXACT REPOSITORY DIRECTORY STRUCTURE

Create and populate the following modular directory structure:

hil-smart-scheduler/
│
├── data/
│ ├── raw/ # Existing ground-truth CSV files
│ │ ├── vehicle_program_ecus.csv
│ │ ├── rig_capabilities.csv
│ │ ├── feature_requirements.csv
│ │ └── ciara_bookings.csv
│ ├── knowledge_base/ # Phase 2 placeholder for PDFs/DBCs/ARXMLs
│ └── vector_store/ # Phase 2 placeholder for ChromaDB
│
├── src/
│ ├── **init**.py
│ ├── config/
│ │ ├── **init**.py
│ │ ├── settings.py # Environment & path configuration
│ │ └── constants.py # Enums (SlotType, Platform) & thresholds
│ │
│ ├── domain/
│ │ ├── **init**.py
│ │ ├── models.py # Pydantic data models for Rigs, Slots, Bookings
│ │ └── state.py # Session state & Booking Cart schemas
│ │
│ ├── repositories/
│ │ ├── **init**.py
│ │ ├── base.py # Abstract Base Classes for data access
│ │ ├── csv_repository.py # Phase 1 Pandas CSV implementation
│ │ └── ciara_api_repository.py # Phase 2 stub for live CIARA REST API JSON
│ │
│ ├── services/
│ │ ├── **init**.py
│ │ ├── capability_matcher.py # Deterministic hardware/sim scoring engine
│ │ ├── slot_scheduler.py # Deterministic interval math & slot finder
│ │ └── booking_service.py # Slot boundary validation & booking writer
│ │
│ ├── agent/
│ │ ├── **init**.py
│ │ ├── orchestrator.py # Gemini 2.5 Flash tool-calling agent loop
│ │ ├── prompts/
│ │ │ ├── system_coordinator.md # System prompt, CoT rules, follow-up templates
│ │ │ └── gatekeeper_rules.md # Two-Stage Gatekeeper instructions
│ │ └── tools/
│ │ ├── **init**.py
│ │ ├── registry.py # @register_tool decorator & tool collector
│ │ ├── discovery_tools.py # Phase 1: Topology, Feature & Rig matching tools
│ │ ├── scheduling_tools.py # Phase 1: Slot finder, conflict check, UI staging
│ │ └── future_phase2_tools.py # Phase 2 stubs (Confluence RAG, DBC parser, Log triage)
│ │
│ ├── ui/
│ │ ├── **init**.py
│ │ ├── state_manager.py # Streamlit session_state initializer
│ │ └── components/
│ │ ├── **init**.py
│ │ ├── sidebar.py # Browser timezone auto-detect & shift settings
│ │ ├── chat_panel.py # Chat history & expandable Agent Tool Trace
│ │ └── slot_picker_table.py # Interactive st.data_editor & Stage 2 Booking Bar
│ │
│ └── utils/
│ ├── **init**.py
│ ├── time_utils.py # Date/time parsing, ISO Friday math, interval helpers
│ └── parsers.py # Pipe-delimited string ("ECU1|ECU2") parser
│
├── app.py # Main Streamlit entry point
├── requirements.txt # Dependencies
└── .env.example # Environment variable template

================================================================================ 2. EXACT DATA SCHEMAS (THE 4 CSV FILES IN `data/raw/`)
===========================================

All multi-value columns use the pipe character (`|`) as a separator (e.g., `ECU1|ECU2|ECU7`).
If a multi-value cell has no items, it contains the literal string `NONE` (or empty/NaN).
Write a helper function `parse_pipe_list(val: Any) -> List[str]` in `src/utils/parsers.py` that returns `[]` if `pd.isna(val)` or `str(val).strip().upper() in ("", "NONE", "NAN")`, and otherwise splits by `"|"` and strips whitespace.

1. `data/raw/vehicle_program_ecus.csv`
   - Primary Key: `Vehicle_Program`
   - Columns:
     - `Vehicle_Program` (str): `VEHICLE_PROGRAM_1` through `VEHICLE_PROGRAM_10`
     - `Applicable_ECUs` (str): Pipe-separated list of ECUs belonging to that program (covers `ECU1` through `ECU80`). Note: `ECU1`–`ECU6` are global core ECUs shared across almost all programs; `ECU7`–`ECU20` are shared across 2–4 programs; `ECU21`–`ECU80` are program-specific.

2. `data/raw/rig_capabilities.csv`
   - Primary Key: `Rig_ID`
   - Columns:
     - `Rig_ID` (str): `RIG_1` through `RIG_30`
     - `Vehicle_Program` (str): Single value (e.g., `VEHICLE_PROGRAM_1`)
     - `Rig_Domain` (str): `DOMAIN_1` through `DOMAIN_5`
     - `Rig_Platform` (str): Strictly `dSPACE`, `Vector`, or `NI` (Never `NI_RT`)
     - `Rig_Engineer` (str): Unique engineer owner ID per rig (`ENG_1` through `ENG_30`)
     - `Real_Connected_Components` (str): Pipe-separated list of physically wired Real ECUs
     - `CAN_Sim_ECUs` (str): Pipe-separated list of ECUs simulated via CAN restbus
     - `Eth_Sim_ECUs` (str): Pipe-separated list of ECUs simulated via Ethernet restbus

3. `data/raw/feature_requirements.csv`
   - Composite Primary Key: `(Feature_Name, Vehicle_Program)`
   - Columns:
     - `Feature_Name` (str): `FEATURE_1` through `FEATURE_8`
     - `Vehicle_Program` (str): `VEHICLE_PROGRAM_1` through `VEHICLE_PROGRAM_10`
     - `Real_ECUs_Required` (str): Pipe-separated list of ECUs required as Real hardware
     - `CAN_Sim_Needed` (str): Pipe-separated list of ECUs required as CAN Simulation
     - `Eth_Sim_Needed` (str): Pipe-separated list of ECUs required as Ethernet Simulation

4. `data/raw/ciara_bookings.csv`
   - Primary Key: `Booking_ID` (Format: `BK_1`, `BK_2`, ..., `BK_45`)
   - Foreign Key: `Rig_ID`
   - Columns:
     - `Booking_ID` (str): Sequential ID `BK_<number>`
     - `Rig_ID` (str): `RIG_1` through `RIG_30`
     - `Date` (str): `YYYY-MM-DD` (Base test dates start at `2026-10-15`)
     - `Slot_Start_Time` (str): 24-hour `HH:MM` (e.g., `09:00`, `11:30`)
     - `Slot_End_Time` (str): 24-hour `HH:MM` (e.g., `10:00`, `18:00`)
     - `Slot_Type` (str): One of the 6 valid SlotType enums:
       - `MANUAL_TESTING`
       - `TEST_PROVEOUT`
       - `AUTOMATED_END_TO_END_EXECUTION`
       - `RIG_MAINTENANCE`
       - `DEBUGGING`
       - `TRIAGING`
     - `Booked_By_User` (str): User identifier (e.g., `USER_1` through `USER_10`)

================================================================================ 3. TWO-STAGE MANDATORY INPUT GATEKEEPER (CRITICAL WORKFLOW RULE)
================================================================

Do NOT block initial rig discovery and slot viewing if the user has not provided `Slot_Type` yet. Instead, enforce a Two-Stage Gatekeeper:

STAGE 1: DISCOVERY & SLOT SEARCH GATEKEEPER (Required before calling matching/slot tools)
To search for compatible rigs and display available time slots, ONLY 2 pillars are mandatory:

1. TARGET CRITERION: At least one of:
   - `rig_id` (e.g., "RIG_1")
   - `vehicle_program` (e.g., "VEHICLE_PROGRAM_1")
   - `feature_name` (e.g., "FEATURE_1")
   - `ecus_requested` (e.g., ["ECU1", "ECU2", "ECU3"])
2. DURATION (`duration_hours`): Total booking hours needed (float > 0).
   - MULTI-ECU SEQUENTIAL DURATION RULE: If a user asks to test N ECUs for X hours each (e.g., "I want to test ECU1, ECU2, ECU3 for 1 hour for each ECU"), the total `duration_hours` MUST be calculated as N \* X = 3.0 hours (even if all 3 ECUs are mounted on the same rig, because tests run sequentially).

_Stage 1 Behavior:_

- If either Target or Duration is missing from the conversation, the Agent must pause and ask the user for the missing Target or Duration.
- As soon as BOTH Target and Duration are known, the Agent MUST immediately call the matching and slot-finding tools and present the ranked rigs and available slots—even if `slot_type` is not yet provided!

STAGE 2: BOOKING EXECUTION GATEKEEPER (Required to finalize/book slots)

1. `Slot_Type` (`MANUAL_TESTING`, `TEST_PROVEOUT`, `AUTOMATED_END_TO_END_EXECUTION`, `RIG_MAINTENANCE`, `DEBUGGING`, or `TRIAGING`) is STRICTLY MANDATORY when the user decides to lock in and book their selected slots.
2. In the Streamlit UI (`slot_picker_table.py`), display a `Select Slot Type for Booking` dropdown right above the "Confirm & Book Selected Slots" button:
   - Pre-select the dropdown value if the user already mentioned a `Slot_Type` in the chat.
   - Otherwise, default the dropdown to `"-- Select Slot Type (Required to Book) --"` and keep the "Confirm & Book Selected Slots" button disabled (or show a validation warning) until a valid `Slot_Type` is selected and at least one slot checkbox is checked.
3. If the user asks the Agent in chat to book a specific slot without having specified `Slot_Type`, the Agent must prompt them to specify the `Slot_Type` or select it in the UI dropdown.

AUTOMATIC TIMEZONE & WORKING HOURS RULE:

- NEVER ask the user for their timezone or standard working hours in the chat.
- Auto-detect the browser timezone in `src/ui/components/sidebar.py` using `getattr(st.context, "timezone", None) or "Asia/Kolkata"`.
- Default working hours in the sidebar to `09:00` (Shift Start) and `18:00` (Shift End).
- Default Simulated Current Date in the sidebar to `2026-10-15` (Thursday).

================================================================================ 4. DETAILED MODULE-BY-MODULE IMPLEMENTATION SPECIFICATIONS
==========================================================

---

## MODULE A: `src/config/constants.py` & `src/config/settings.py`

In `constants.py`, define:

- `SlotType(str, Enum)`: `MANUAL_TESTING`, `TEST_PROVEOUT`, `AUTOMATED_END_TO_END_EXECUTION`, `RIG_MAINTENANCE`, `DEBUGGING`, `TRIAGING`.
- `PlatformType(str, Enum)`: `DSPACE = "dSPACE"`, `VECTOR = "Vector"`, `NI = "NI"`.
- `MIN_SLOT_DURATION_HOURS = 0.5` (30 minutes minimum usable block).
- `COMPATIBILITY_CUTOFF_PERCENT = 50.0` (50% threshold).
- `FALLBACK_TOP_K_RIGS = 4` (Return top 4 rigs if fewer than 4 rigs exceed 50%).
- `EXTENDED_SHIFT_DELTA_HOURS = 2` (+-2 hours outside standard working window).

---

## MODULE B: `src/repositories/` (Repository Pattern)

1. `base.py`: Define abstract base class `AbstractHILRepository` with methods:
   - `get_all_rigs() -> pd.DataFrame`
   - `get_feature_requirements() -> pd.DataFrame`
   - `get_vehicle_program_ecus() -> pd.DataFrame`
   - `get_bookings() -> pd.DataFrame`
   - `append_bookings(new_bookings: List[Dict[str, Any]]) -> List[str]`
2. `csv_repository.py`: Implement `CSVHILRepository(AbstractHILRepository)` reading and writing the 4 CSVs in `data/raw/`.
   - In `append_bookings`, reload `ciara_bookings.csv`, find the maximum integer `N` among existing `BK_<N>` IDs, generate sequential IDs `BK_<N+1>`, `BK_<N+2>`, ..., append the rows to the DataFrame, save back to `data/raw/ciara_bookings.csv`, and return the list of newly created `Booking_ID`s.
3. `ciara_api_repository.py`: Create a clean class `CiaraAPIRepository(AbstractHILRepository)` with documented methods explaining where the live CIARA REST API JSON endpoints (`GET /api/v1/bookings`, `POST /api/v1/bookings`) plug in during Phase 2.

---

## MODULE C: `src/services/capability_matcher.py` (Deterministic Matching Engine)

Implement `CapabilityMatcherService` initialized with `AbstractHILRepository`.

Method: `match_rigs(...) -> Dict[str, Any]`
Parameters:

- `rig_id: Optional[str] = None`
- `feature_name: Optional[str] = None`
- `vehicle_program: Optional[str] = None`
- `ecus_requested: Optional[List[str]] = None`
- `platform: Optional[str] = None`
- `domain: Optional[str] = None`
- `ecu_config_pref: Optional[Dict[str, str]] = None` (e.g., `{"ECU1": "Real", "ECU2": "CAN_Sim"}`)

Exact Filtering & Scoring Rules:

1. Optional Pre-Filters:
   - If `platform` is provided, filter rigs where `Rig_Platform.lower() == platform.lower()`.
   - If `domain` is provided, filter rigs where `Rig_Domain.lower() == domain.lower()`.

2. CASE 1: Direct `rig_id` Request (when `rig_id` is set and no `feature_name` or `ecus_requested`):
   - Return the matching rig with `match_score = 100.0`, `match_type = "Direct Rig Request"`, and full hardware metadata.

3. CASE 2: `feature_name` Request (`_match_by_feature`):
   - Look up `feature_name` in `feature_requirements.csv`.
   - If `vehicle_program` is specified by the user, select the feature requirement row for `(feature_name, vehicle_program)`. If not specified, evaluate against the requirement row matching each rig's `Vehicle_Program` (or the first matching row for that feature).
   - Let `target_vp` be the user-requested `vehicle_program` (or if None, the `Vehicle_Program` of the primary requirement row).
   - Evaluate ALL candidate rigs (across all 10 vehicle programs):
     - Flag `is_cross_program = (rig["Vehicle_Program"].upper() != target_vp.upper())` if `vehicle_program` was specified.
     - Let `req_real`, `req_can`, `req_eth` be the sets of required Real, CAN Sim, and Eth Sim ECUs for the feature.
     - `total_req = len(req_real) + len(req_can) + len(req_eth)`.
     - Let `rig_real`, `rig_can`, `rig_eth` be the sets of ECUs on the rig.
     - Initialize `earned_points = 0.0`, `smart_upgrades = []`, `downgrades = []`, `missing = []`.
     - Check `req_real` (for each `ecu` in sorted `req_real`):
       - If `ecu in rig_real`: `earned_points += 1.0`
       - Else if `ecu in rig_can` or `ecu in rig_eth`:
         `earned_points += 0.5`
         `sim_label = "CAN Sim" if ecu in rig_can else "Eth Sim"`
         `downgrades.append(f"{ecu} (Real required, only {sim_label} available)")`
       - Else:
         `missing.append(f"{ecu} (Real missing)")`
     - Check `req_can` (for each `ecu` in sorted `req_can`):
       - If `ecu in rig_can`: `earned_points += 1.0`
       - Else if `ecu in rig_real` (SMART UPGRADE RULE):
         `earned_points += 1.0`
         `smart_upgrades.append(f"{ecu} CAN simulation missing, but Real {ecu} variant is physically connected")`
       - Else:
         `missing.append(f"{ecu} (CAN Sim missing)")`
     - Check `req_eth` (for each `ecu` in sorted `req_eth`):
       - If `ecu in rig_eth`: `earned_points += 1.0`
       - Else if `ecu in rig_real` (SMART UPGRADE RULE):
         `earned_points += 1.0`
         `smart_upgrades.append(f"{ecu} Eth simulation missing, but Real {ecu} variant is physically connected")`
       - Else:
         `missing.append(f"{ecu} (Eth Sim missing)")`
     - Calculate `match_score = round((earned_points / total_req) * 100.0, 1) if total_req > 0 else 100.0`.
     - Apply the Cutoff & Sorting Rule (defined below).

4. CASE 3: Direct `ecus_requested` Query (`_match_by_ecus`):
   - Normalize `req_ecus = [e.strip().upper() for e in ecus_requested]`.
   - For each candidate rig:
     - Check where each `ecu` in `req_ecus` appears on the rig (`Real`, `CAN_Sim`, `Eth_Sim`).
     - If `ecu_config_pref` is NOT provided (initial query):
       - Award `+1.0` point for every requested ECU present on the rig in ANY configuration (Real, CAN_Sim, or Eth_Sim).
       - Record the exact configuration string per ECU: e.g., `"ECU1 (Real), ECU2 (CAN_Sim), ECU24 (Eth_Sim)"`.
     - If `ecu_config_pref` IS provided (user specified e.g. `{"ECU1": "Real", "ECU2": "CAN_Sim"}`):
       - Award `+1.0` for exact match, `+1.0` + Smart Upgrade note if Real is present when Sim was requested, `+0.5` + Downgrade note if Sim is present when Real was requested, `0.0` if missing.
     - Compute `match_score = round((earned_points / len(req_ecus)) * 100.0, 1)`.
   - MULTI-RIG ECU SUBSET COMBINATION FINDER:
     - In addition to ranking individual rigs, compute `ecu_split_combinations`: if a user asked for multiple ECUs (e.g., `ECU1, ECU2, ECU25`) and they want alternatives or contiguous time is scarce, identify pairs of rigs that together cover 100% of `req_ecus` (e.g., `"ECU1 + ECU2 on RIG_1 (Real) AND ECU25 on RIG_3 (Real)"`). Return these combinations in the response dictionary so the Agent can offer them!

5. CASE 4: `vehicle_program` Only Request:
   - Return all rigs supporting `vehicle_program` with `match_score = 100.0`. Also check `vehicle_program_ecus.csv` to list which shared ECUs exist on cross-program rigs if primary rigs are full.

6. CUTOFF & SORTING RULE (`_apply_cutoff_and_sort`):
   - Filter out rigs with `match_score == 0.0`.
   - Sort remaining rigs by:
     1. `not r["is_cross_program"]` (True comes before False, so Primary Vehicle Program rigs always rank above Cross-Program rigs with equal score),
     2. `r["match_score"]` descending.
   - Let `above_50 = [r for r in results if r["match_score"] > 50.0]`.
   - If `len(above_50) >= 4`: return `above_50`.
   - Else (fewer than 4 rigs exceed 50% compatibility): return `results[:4]` (the Top 4 highest-scoring rigs overall).

---

## MODULE D: `src/services/slot_scheduler.py` (Deterministic Time-Slot Engine)

Implement `SlotSchedulerService` initialized with `AbstractHILRepository`.

Method: `find_free_slots(...) -> Dict[str, Any]`
Parameters:

- `rig_ids: List[str]`
- `start_date: str = "2026-10-15"`
- `deadline_date: Optional[str] = None`
- `shift_start: str = "09:00"`
- `shift_end: str = "18:00"`
- `include_extended: bool = False`
- `allow_weekends: bool = False`
- `min_slot_hours: float = 0.5`

Exact Scheduling & Interval Rules:

1. CURRENT WEEK FRIDAY HORIZON RULE:
   - Parse `s_date = datetime.strptime(start_date, "%Y-%m-%d").date()`.
   - Calculate Friday of `s_date`'s week:
     `days_until_friday = (4 - s_date.weekday()) % 7` (if `s_date` is Saturday/Sunday and `allow_weekends` is False, advance to next Friday).
     `current_friday = s_date + timedelta(days=days_until_friday)`.
   - If `deadline_date` is None:
     `e_date = current_friday` (STRICT RULE: Do not search beyond Friday of the current week unless the user specifies a deadline past Friday!).
   - If `deadline_date` is provided:
     `e_date = datetime.strptime(deadline_date, "%Y-%m-%d").date()`.

2. STRICT WEEKEND EXCLUSION RULE:
   - Generate the list of dates from `s_date` to `e_date` inclusive.
   - For each date `d`: if `d.weekday() in (5, 6)` (Saturday=5, Sunday=6) and `not allow_weekends`:
     SKIP `d` completely.

3. INTERVAL SUBTRACTION & 30-MINUTE MINIMUM RULE:
   - For each `rig_id` and each valid date `d_str`:
     - Fetch all rows in `ciara_bookings.csv` matching `Rig_ID == rig_id` and `Date == d_str`.
     - Always compute free gaps in the Standard Window `[shift_start, shift_end]` labeled `window_type = "Standard Shift"`.
     - Also compute free gaps in the +-2h Extended Windows:
       - Early Extended Window: `[max("00:00", shift_start - 2h), shift_start]` labeled `window_type = "Extended (-2h Early)"`.
       - Late Extended Window: `[shift_end, min("23:59", shift_end + 2h)]` labeled `window_type = "Extended (+2h Late)"`.
     - To compute free gaps inside any window `[W_start, W_end]`:
       a) Clip each booking interval `[B_start, B_end]` to `[max(W_start, B_start), min(W_end, B_end)]`. Keep if `start < end`.
       b) Sort busy intervals by start time and merge overlapping/adjacent intervals.
       c) Walk from `curr = W_start` to `W_end`, subtracting merged busy intervals to find open gaps `(gap_start, gap_end)`.
       d) Compute `duration_hrs = round((gap_end - gap_start).total_seconds() / 3600.0, 2)`.
       e) ANTI-FRAGMENTATION FILTER: Keep the gap ONLY if `duration_hrs >= min_slot_hours` (`0.5` hours / 30 minutes). Discard any gap `< 0.5` hours!
       f) BOOKING TIME DIVISION RULE: Keep all valid gaps `>= 0.5h` even if an individual gap is smaller than the user's total requested `duration_hours` (e.g., keep a 1.5h gap and a 1.0h gap so the user can combine them to reach 3.0h).

4. CONFLICT & MAINTENANCE METADATA EXTRACTION:
   - Alongside `standard_slots` and `extended_slots`, return `rig_conflicts`: a summary per `rig_id` and `date` listing any existing bookings, specifically highlighting:
     - `maintenance_blocks`: Any booking where `Slot_Type == "RIG_MAINTENANCE"` (with start/end time and `Booked_By_User`).
     - `user_bookings`: Existing bookings (`Booked_By_User`, `Slot_Start_Time`, `Slot_End_Time`, `Slot_Type`) so the Agent can suggest contacting `Booked_By_User` for a slot swap if needed.

---

## MODULE E: `src/services/booking_service.py` (Validation & Execution)

Implement `BookingService` initialized with `AbstractHILRepository`.

Method: `validate_and_book_slots(selected_slots: List[Dict[str, Any]], slot_type: str, user_id: str) -> Dict[str, Any]`

1. Enforce Stage 2 Gatekeeper: Verify `slot_type` is a valid `SlotType` enum value (`MANUAL_TESTING`, `TEST_PROVEOUT`, `AUTOMATED_END_TO_END_EXECUTION`, `RIG_MAINTENANCE`, `DEBUGGING`, `TRIAGING`). If missing or invalid, raise a `ValueError("A valid Slot_Type is mandatory to complete a booking.")`.
2. For each slot in `selected_slots`:
   - Parse `start_time` and `end_time` (user may have custom-trimmed them in the UI table).
   - Verify `start_time >= orig_start_time` and `end_time <= orig_end_time` (must remain within the available free window).
   - Verify `(end_time - start_time) >= 0.5` hours (minimum 30 minutes) and does not overlap with any existing booking in `ciara_bookings.csv`.
3. Call `repo.append_bookings(...)` to persist to `data/raw/ciara_bookings.csv` and return the created `Booking_ID`s (`BK_46`, etc.).

---

## MODULE F: `src/agent/tools/` (Plugin-Style Tool Registry & Agent Tools)

1. `registry.py`:
   - Implement a clean decorator `@register_tool` that registers functions into a global list `AGENT_TOOLS` and exposes `get_registered_tools() -> List[Callable]`.
2. `discovery_tools.py` & `scheduling_tools.py`:
   - Expose the following deterministic functions decorated with `@register_tool` (with full Python type hints and detailed docstrings so `gemini-2.5-flash` understands every parameter and return value):
     - `inspect_topology_and_features(feature_name: Optional[str] = None, vehicle_program: Optional[str] = None) -> dict`
       Returns the applicable ECUs from `vehicle_program_ecus.csv` and/or required Real/CAN_Sim/Eth_Sim ECUs from `feature_requirements.csv`.
     - `match_rigs_by_criteria(feature_name: Optional[str] = None, vehicle_program: Optional[str] = None, ecus_requested: Optional[List[str]] = None, rig_id: Optional[str] = None, platform: Optional[str] = None, domain: Optional[str] = None, ecu_config_pref: Optional[Dict[str, str]] = None) -> dict`
       Calls `CapabilityMatcherService.match_rigs(...)` and returns the ranked rigs, match percentages, Smart Upgrade notes, Downgrade warnings, Missing ECUs, Cross-Program flags, per-ECU breakdowns, and multi-rig ECU subset combinations.
     - `find_available_slots(rig_ids: List[str], duration_hours: float, start_date: str = "2026-10-15", deadline_date: Optional[str] = None, shift_start: str = "09:00", shift_end: str = "18:00", include_extended: bool = False, allow_weekends: bool = False) -> dict`
       Calls `SlotSchedulerService.find_free_slots(...)`. Returns:
       - `standard_slots`: Free slots >= 0.5h in standard working hours (capped at Friday of current week unless `deadline_date` is past Friday; weekends excluded unless `allow_weekends=True`).
       - `total_standard_hours_available`: Sum of hours in `standard_slots`.
       - `extended_slots_preview`: Additional slots available in the +-2h extended window (`07:00-09:00` and `18:00-20:00`).
       - `total_with_extended_hours`: Sum of standard + extended hours.
       - `rig_conflicts`: Maintenance blocks (`RIG_MAINTENANCE`) and conflicting `Booked_By_User` records.
       - Automatically updates `st.session_state.candidate_slots` with `standard_slots` (or `standard_slots + extended_slots_preview` if `include_extended=True`) and `st.session_state.target_duration_hours = duration_hours` so the interactive UI table renders immediately!
     - `stage_filtered_slots_for_ui(rig_ids: List[str], duration_hours: float, start_date: str = "2026-10-15", deadline_date: Optional[str] = None, include_extended: bool = False, allow_weekends: bool = False, slot_type: Optional[str] = None) -> dict`
       Called when the user answers follow-up questions (e.g., choosing a specific rig from the list, setting a deadline, agreeing to +-2h extended hours, or specifying a `slot_type`). Filters the slots accordingly and updates `st.session_state.candidate_slots` and `st.session_state.selected_slot_type`.
3. `future_phase2_tools.py`:
   - Include clean, documented stub functions (not registered in active Phase 1 tools unless toggled) for:
     - `search_engineering_confluence_and_specs(query: str, vehicle_program: str)`
     - `query_signal_database_dbc_arxml(ecu_id: str, signal_or_message_name: str)`
     - `trigger_automated_test_and_triage_logs(booking_id: str, test_suite_id: str)`

---

## MODULE G: `src/agent/prompts/system_coordinator.md` & `src/agent/orchestrator.py`

In `orchestrator.py`, use the `google-genai` SDK (`client = genai.Client(api_key=...)`) with `model="gemini-2.5-flash"`. Pass the registered tools from `registry.py` into `types.GenerateContentConfig(tools=..., system_instruction=...)` so Gemini executes automatic function calling (ReAct loop) and records tool calls into `st.session_state.tool_trace` for observability.

Write the following complete instruction set into `src/agent/prompts/system_coordinator.md`:

1. PERSONA & CORE MISSION:
   - You are a Senior HIL (Hardware-in-the-Loop) Lab Coordinator & Resource Strategist.
   - Never act like a passive form-filler. You think critically about hardware topologies, Real vs. Restbus Simulation trade-offs, bench maintenance hazards, and schedule fragmentation.

2. TWO-STAGE MANDATORY GATEKEEPER RULES:
   - STAGE 1 (Discovery & Slot Search):
     Before calling `match_rigs_by_criteria` or `find_available_slots`, verify that the user has provided:
     (a) TARGET: `rig_id`, `vehicle_program`, `feature_name`, OR a list of `ecus_requested`.
     (b) DURATION: Total hours required (if user requests N ECUs for X hours each, compute N * X total hours).
     *CRITICAL\*: Do NOT ask for `Slot_Type` before showing matching rigs and available slots! `Slot_Type` is NOT required in Stage 1. If Target and Duration are present, immediately call your tools and display the options.
     If Target or Duration is missing, politely ask ONLY for the missing Target or Duration.
   - STAGE 2 (Booking Confirmation):
     `Slot_Type` (`MANUAL_TESTING`, `TEST_PROVEOUT`, `AUTOMATED_END_TO_END_EXECUTION`, `RIG_MAINTENANCE`, `DEBUGGING`, `TRIAGING`) is mandatory only when the user wants to confirm/book slots. Remind them they can select their desired `Slot_Type` and check their preferred time slots in the interactive booking table below the chat.

3. INTERNAL CHAIN-OF-THOUGHT (CoT) DIAGNOSTIC CHECKLIST:
   Whenever tool results return, silently evaluate:
   - Are there 100% Exact Matches, or do top rigs rely on **Smart Upgrades** (Real ECU wired where CAN/Eth Sim was required), **Downgrades** (Sim where Real was required), **Missing ECUs**, or **Cross-Program Rigs**?
   - If the user asked for raw ECUs (`ECU1, ECU2, ...`), what is the exact Real vs. CAN_Sim vs. Eth_Sim breakdown on each rig?
   - Can the requested `duration_hours` be met within standard working hours before Friday of the current week, or are slots fragmented across multiple rigs/days?
   - Does unlocking the **+-2-hour extended shift (`07:00-09:00` and `18:00-20:00`)** solve a slot shortage?
   - Are any candidate rigs blocked by `RIG_MAINTENANCE` or heavy bookings by another `Booked_By_User`?

4. MANDATORY RESPONSE FORMAT & PROACTIVE FOLLOW-UP QUESTIONS:
   When presenting initial discovery results, always format clearly:
   - List the top matching rigs in order of Match %, explicitly stating:
     - Match %, Platform (`dSPACE`, `Vector`, `NI`), Vehicle Program, and Owner (`Rig_Engineer`).
     - Available free slots (Date, Start Time - End Time, Duration in hours) within the current week (through Friday, excluding weekends).
     - Explicit hardware notes: **Smart Upgrades**, **Downgrades/Missing ECUs**, or **Cross-Program status**.
   - Example output style:
     "The below rigs are your best available options:
     - **RIG_1** (100% Exact Match | dSPACE | Owner: ENG_1): Available for **1.5 hours** from `10:00 to 11:30` on `2026-10-15`, and **1.0 hour** from `10:00 to 11:00` on `2026-10-16`.
     - **RIG_2** (100% Match via Smart Upgrade | Vector | Owner: ENG_2): `ECU5, ECU9, ECU24` Eth simulation missing, but **Real physical variants** are connected. Available for **1.0 hour** from `14:00 to 15:00` on `2026-10-15`, and **1.0 hour** from `09:00 to 10:00` on `2026-10-16`.
     - **RIG_3** (58.3% Partial Match | NI | Owner: ENG_3): Booked on `2026-10-15` for `RIG_MAINTENANCE`, available for **2.0 hours** (`12:00 to 14:00`) on `2026-10-16`.
     - **RIG_4** (83.3% Cross-Program Match | Supports `VEHICLE_PROGRAM_2` | dSPACE | Owner: ENG_4): Has shared ECUs (`ECU1, ECU2, ECU7, ECU3, ECU4, ECU8`) and is available for **5.0 continuous hours** (`11:00 to 16:00`) on `2026-10-15`."

   Then, proactively ask the applicable follow-up questions from these 8 rules:
   - Question Rule 1 (Single Rig vs. Multi-Rig Split):
     "Do you want to stick to a particular rig from the above options, or are you open to splitting your [X] hours across multiple rigs/slots?"
   - Question Rule 2 (Target Deadline & +-2h Extended Shift):
     "Do you have a deadline before which you need all [X] hours completed? (If you need all hours completed before a tight deadline—or if standard shift hours fall short—I can unlock slots from **+-2 hours outside your working hours (`07:00–09:00` and `18:00–20:00`)**, which adds [Y] extra free hours!)"
   - Question Rule 3 (Smart Upgrade Verification - whenever Smart Upgrades exist):
     "On `[RIG_ID]`, `[ECU_LIST]` simulation is missing, but the **Real physical ECUs** are connected. Does having the real hardware in the loop work for your test, or do you need Rig Engineer `[ENG_ID]` to switch them to simulated restbus mode?"
   - Question Rule 4 (Direct ECU Query Probe & Subset Combinations - whenever user queries raw ECUs):
     "I have listed every rig containing `[ECU_LIST]` along with whether each ECU is wired as **Real**, **CAN_Sim**, or **Eth_Sim**. Do you require a specific Real or Simulated configuration? Also, if contiguous hours are tight, would you like to split the ECU combinations across rigs (e.g., `[ecu_split_combinations]`) or work within **+-2 hours** outside your shift?"
   - Question Rule 5 (Cross-Program Fallback - whenever a cross-program rig is recommended):
     "`[RIG_ID]` supports `[RIG_VP]` rather than `[TARGET_VP]`, but it has the desired ECU configuration and [Z] free hours. If you are okay with a cross-program rig, shall we include it?"
   - Question Rule 6 (Partial Match & Rig Engineer Handshake - when <100% match):
     "Since `[RIG_ID]` is missing `[MISSING_ECUS]`, would you like to notify Rig Engineer `[ENG_ID]` to configure them before your slot, or can you run a reduced scope?"
   - Question Rule 7 (Maintenance & Peer Conflict Negotiation):
     If a top rig is blocked by `RIG_MAINTENANCE`, warn the user. If blocked by another engineer (`Booked_By_User`), mention the user ID (e.g., `USER_2`) in case they want to negotiate a slot swap.
   - Question Rule 8 (Stage 2 Booking Prompt):
     Remind the user that candidate slots are now loaded in the **Interactive Slot Selector Table** below, where they can check their desired slots, adjust start/end times, choose their **Slot Type**, and confirm the booking.

---

## MODULE H: `src/ui/` & `app.py` (Streamlit UI & Interactive Slot Selector)

1. `src/ui/components/sidebar.py`:
   - Input for `Gemini API Key` (reads `os.environ.get("GEMINI_API_KEY", "")` or `.env`).
   - Input for `Logged-in User ID` (default `"USER_ENG_01"`).
   - Auto-detected Browser Timezone badge: `tz = getattr(st.context, "timezone", None) or "Asia/Kolkata"`.
   - Two columns for `Shift Start` (default `"09:00"`) and `Shift End` (default `"18:00"`).
   - Input for `Simulated Current Date` (default `"2026-10-15"`).
   - Toggle button `"🔄 Reset Conversation"`.
   - Expandable section `"🔍 Live Agent State & Tool Calls"` showing the latest tool invocations.

2. `src/ui/components/slot_picker_table.py`:
   - Renders whenever `st.session_state.candidate_slots` is non-empty.
   - Builds a DataFrame from `st.session_state.candidate_slots` with columns:
     - `Select` (bool, default `False`, editable checkbox)
     - `rig_id` (str, read-only)
     - `Rig_Details` (str: e.g., `"100.0% Match | dSPACE | VEHICLE_PROGRAM_1 | ENG_1"`, read-only)
     - `date` (str: e.g., `"2026-10-15 (Thu)"`, read-only)
     - `start_time` (str: initialized to slot's free start time, EDITABLE so user can trim a large 5-hour block like `11:00-16:00` down to `11:00-14:00`)
     - `end_time` (str: initialized to slot's free end time, EDITABLE)
     - `duration_hrs` (float: dynamically recalculated from `end_time - start_time`, read-only)
     - `window_type` (str: `"Standard Shift"`, `"Extended (-2h Early)"`, or `"Extended (+2h Late)"`, read-only)
   - Renders `st.data_editor` with `use_container_width=True` and `hide_index=True`.
   - Below the table, display two columns:
     - Column 1: Live progress metric: `Selected Time: X.X hrs / Target Requested: Y.Y hrs` (with a visual indicator when `X.X >= Y.Y`).
     - Column 2 (STAGE 2 GATEKEEPER): A dropdown `st.selectbox("Slot Type (Mandatory for Booking)", options=["-- Select Slot Type --", "MANUAL_TESTING", "TEST_PROVEOUT", "AUTOMATED_END_TO_END_EXECUTION", "DEBUGGING", "TRIAGING", "RIG_MAINTENANCE"])`, pre-populated if `st.session_state.selected_slot_type` was extracted from chat.
   - Primary Button: `"✅ Confirm & Book Selected Slots"`.
     - When clicked:
       - Check that at least one row has `Select == True`.
       - Check that `Slot Type` is not `"-- Select Slot Type --"`. If it is, display `st.error("Please select a mandatory Slot Type before booking.")`.
       - Call `BookingService.validate_and_book_slots(...)`.
       - If any edited `start_time` / `end_time` is outside the original free window or `< 0.5` hours, show a clear `st.error(...)` message.
       - On success, display `st.success(...)` with the new Booking IDs (`BK_46`, etc.), append a confirmation message to `st.session_state.messages`, and refresh the candidate slots so the newly booked interval immediately disappears from free availability!

================================================================================ 5. DELIVERABLES EXPECTATION
===========================

Generate the complete, working code for all files in the repository tree. Ensure all imports across `src/` resolve cleanly from `app.py`, all Pandas operations handle `NONE` / `NaN` values safely, and the Gemini tool-calling loop handles multi-tool turns gracefully.
