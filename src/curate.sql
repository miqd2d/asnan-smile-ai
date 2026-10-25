UPDATE visit_types SET patient_bookable = 0;

UPDATE visit_types SET patient_bookable = 1
WHERE active = 1
  AND rov_id IN (39, 5, 50, 1055, 1059, 48, 1074, 2, 20, 1147, 49, 1099, 1242, 51, 1108);

-- Check: should return exactly 15 rows
SELECT rov_id, name, duration_min FROM visit_types WHERE patient_bookable = 1 ORDER BY name;