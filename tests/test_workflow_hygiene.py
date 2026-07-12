from scripts import check_workflow_hygiene


def test_all_workflows_follow_security_hygiene() -> None:
    assert check_workflow_hygiene.main() == 0


def test_shell_input_interpolation_is_rejected() -> None:
    job = {"steps": [{"run": 'echo "${{ inputs.value }}"'}]}
    assert check_workflow_hygiene._has_direct_input_interpolation(job)
