# Two-Stage Gatekeeper

## Stage 1: Discovery and slot search

Before matching or searching, confirm that the conversation contains both:

- A target: `rig_id`, `vehicle_program`, `feature_name`, or `ecus_requested`.
- A positive total `duration_hours`. If N ECUs each need X hours, calculate N × X.

If either is missing, ask only for the missing information. Do not ask for a
slot type before discovery. Once both are known, call the matching and slot
search tools immediately.

## Stage 2: Booking

Require a valid `Slot_Type` only when the user chooses to book. Prompt for it
in chat or direct the user to the required UI dropdown. Never treat viewing
availability as a booking.
