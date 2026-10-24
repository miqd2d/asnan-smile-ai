# Data quality report

Raw rows: schedule=2238, appointments=198, visit types=243

- Doctors found in appointments but missing from the schedule: ['Asst Dr Khaled']
- Staff marked NOT bookable (assistants/equipment): 15 of 57
- Schedule rows: 2238 (2026-10-20 to 2026-12-31)
- Visit types: 243 total, 8 inactive, 23 duplicate names (after trimming spaces)
- Duplicate appointment IDs collapsed: 8 (full history kept in appointment_history)
- Block (time-holder) rows: 6
- Patients: 163. Source phone columns were 100% empty, so DUMMY phones were generated (never real numbers).
- Live appointments with NO matching schedule day: 3
- Appointments whose patient is missing from patients: 0
- table `units`: 10 rows
- table `doctors`: 57 rows
- table `schedules`: 2238 rows
- table `visit_types`: 243 rows
- table `statuses`: 11 rows
- table `patients`: 163 rows
- table `appointments`: 190 rows
- table `appointment_history`: 198 rows