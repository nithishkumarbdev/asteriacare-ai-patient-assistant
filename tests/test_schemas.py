from asteriacare.schemas import PatientDetails


def test_missing_fields_starts_with_all_required():
    details = PatientDetails()
    assert set(details.missing_fields()) == set(PatientDetails.REQUIRED)
    assert not details.is_complete()


def test_merge_fills_in_fields_incrementally():
    details = PatientDetails()
    details = details.merge({"patient_name": "Jordan Ellis"})
    assert details.patient_name == "Jordan Ellis"
    assert "patient_name" not in details.missing_fields()
    assert "patient_phone" in details.missing_fields()


def test_merge_does_not_overwrite_with_empty_values():
    details = PatientDetails(patient_name="Jordan Ellis")
    details = details.merge({"patient_name": "", "patient_phone": "+1-555-0100"})
    assert details.patient_name == "Jordan Ellis"
    assert details.patient_phone == "+1-555-0100"


def test_is_complete_ignores_optional_doctor_field():
    details = PatientDetails(
        patient_name="Jordan Ellis",
        patient_phone="+1-555-0100",
        patient_email="jordan@example.com",
        reason_for_visit="Annual checkup",
        department="General Medicine",
        patient_location="Riverside Campus",
        appointment_datetime="2026-09-01 10:00",
    )
    assert details.is_complete()
