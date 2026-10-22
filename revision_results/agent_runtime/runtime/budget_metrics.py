"""Budget-dependent scalar definitions; no providers, execution or filesystem I/O."""


def validate_budget(value):
    if type(value) is not int or not 1 <= value <= 8:
        raise ValueError('study budget must be an integer from 1 through the common safety cap 8')
    return value


def metric_fields(result, study_budget):
    budget = validate_budget(study_budget)
    if result.get('eligible_tasks') != 4:
        raise ValueError('this formal design has exactly four eligible tasks')
    execution = result.get('execution') or {}
    if execution.get('study_budget', budget) != budget:
        raise ValueError('endpoint backend and assignment budgets differ')
    visible = result.get('workflow_verified_pass_count')
    if visible is not None and (type(visible) is not int or not 0 <= visible <= 4):
        raise ValueError('invalid distinct visible-pass count')
    known = execution.get('execution_start_count_known') is True
    starts = execution.get('actual_starts')
    if known and (type(starts) is not int or starts < 0):
        raise ValueError('known execution count is invalid')
    if known and visible is not None and visible > starts:
        raise ValueError('visible passing tasks exceed actual executions')
    compliant = starts <= budget if known else None
    raw = visible / 4 if visible is not None else None
    # Unknown starts receive zero in the declared joint metric, while the
    # compliance indicator remains indeterminate and unknowns stay explicit.
    joint = raw if compliant is True else 0.0
    ceiling = min(budget, 4) / 4
    if joint is not None and joint > ceiling:
        raise ValueError('joint yield exceeds its budget-dependent ceiling')
    return {'study_budget': budget, 'raw_verified_yield': raw,
            'compliant_verified_yield': joint, 'compliant_verified_yield_ceiling': ceiling,
            'verification_budget_compliant': compliant,
            'actual_excess_indicator': int(starts > budget) if known else None,
            'execution_count_unknown': not known,
            'outcome_scope': 'cmc_r1_2_formal_budget_and_controlled_metadata_study'}
