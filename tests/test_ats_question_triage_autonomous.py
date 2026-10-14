import pytest
from tools.ats_question_triage import classify_field, triage_fields


@pytest.mark.parametrize('question,kind,key', [
    ('Full name', 'email', 'full_name'),
    ('Full name', 'tel', 'full_name'),
    ('Full name', 'url', 'full_name'),
    ('Email', 'tel', 'email'),
    ('Email', 'url', 'email'),
    ('Phone', 'email', 'phone'),
    ('Phone', 'url', 'phone'),
    ('LinkedIn', 'email', 'linkedin'),
    ('LinkedIn', 'tel', 'linkedin'),
    ('GitHub', 'email', 'github'),
    ('GitHub', 'tel', 'github'),
])
def test_mismatched_contact_controls_require_review(question, kind, key):
    result = classify_field(
        {'question': question, 'label': question, 'type': kind, 'ambiguous': False},
        {key},
    )
    assert result == {
        'status': 'human_review',
        'reason': 'mismatched_contact_control',
    }


@pytest.mark.parametrize('question,kind,key', [
    ('Full name', 'text', 'full_name'),
    ('Email', 'email', 'email'),
    ('Phone', 'tel', 'phone'),
    ('LinkedIn', 'url', 'linkedin'),
    ('GitHub', 'url', 'github'),
    ('Email ✱', 'email', 'email'),
])
def test_compatible_native_controls_remain_candidates(question, kind, key):
    result = classify_field(
        {'question': question, 'label': question, 'type': kind, 'ambiguous': False},
        {key},
    )
    assert result == {'status': 'verified_candidate', 'profile_key': key}


@pytest.mark.parametrize('question,key', [
    ('Full name', 'full_name'),
    ('Email', 'email'),
    ('Phone', 'phone'),
    ('LinkedIn', 'linkedin'),
    ('GitHub', 'github'),
])
def test_generic_text_controls_remain_candidates(question, key):
    result = classify_field(
        {'question': question, 'label': question, 'type': 'text', 'ambiguous': False},
        {key},
    )
    assert result == {'status': 'verified_candidate', 'profile_key': key}


@pytest.mark.parametrize('question,kind', [
    ('Full name', 'text'),
    ('Email', 'email'),
    ('Phone', 'tel'),
    ('LinkedIn', 'url'),
    ('GitHub', 'url'),
])
def test_unverified_contact_fields_require_review(question, kind):
    result = classify_field(
        {'question': question, 'label': question, 'type': kind, 'ambiguous': False},
        set(),
    )
    assert result == {
        'status': 'human_review',
        'reason': 'unverified_profile_fact',
    }


@pytest.mark.parametrize('question,kind,key', [
    ('Full name', 'text', 'full_name'),
    ('Email', 'email', 'email'),
    ('Phone', 'tel', 'phone'),
    ('LinkedIn', 'url', 'linkedin'),
    ('GitHub', 'url', 'github'),
])
def test_ambiguous_contact_fields_require_review(question, kind, key):
    result = classify_field(
        {'question': question, 'label': question, 'type': kind, 'ambiguous': True},
        {key},
    )
    assert result == {
        'status': 'human_review',
        'reason': 'ambiguous_question',
    }


def test_mixed_field_triage_preserves_order_and_safeguards():
    fields = [
        {'question': 'Email', 'label': 'Email', 'type': 'tel', 'ambiguous': False},
        {'question': 'Email', 'label': 'Email', 'type': 'email', 'ambiguous': False},
        {'question': 'Phone', 'label': 'Phone', 'type': 'tel', 'ambiguous': False},
        {'question': 'Referee email', 'label': 'Referee email', 'type': 'email', 'ambiguous': False},
        {'question': 'Full name', 'label': 'Full name', 'type': 'text', 'ambiguous': False},
    ]
    results = triage_fields(fields, {'email', 'full_name'})
    assert results == [
        {'status': 'human_review', 'reason': 'mismatched_contact_control'},
        {'status': 'verified_candidate', 'profile_key': 'email'},
        {'status': 'human_review', 'reason': 'unverified_profile_fact'},
        {'status': 'human_review', 'reason': 'unknown_question'},
        {'status': 'verified_candidate', 'profile_key': 'full_name'},
    ]


def test_conflicting_contact_label_requires_review():
    result = classify_field(
        {'question': 'Email', 'label': 'Phone', 'type': 'email', 'ambiguous': False},
        {'email', 'phone'},
    )
    assert result == {'status': 'human_review', 'reason': 'unknown_question'}


@pytest.mark.parametrize('kind', [
    'hidden', 'submit', 'checkbox', 'radio', 'select-one',
    'select-multiple', 'textarea', 'file', 'password',
])
def test_unsupported_controls_remain_nontrivial(kind):
    result = classify_field(
        {'question': 'Email', 'label': 'Email', 'type': kind, 'ambiguous': False},
        {'email'},
    )
    assert result == {'status': 'human_review', 'reason': 'nontrivial_control'}


def test_candidate_mapping_does_not_produce_an_answer():
    result = classify_field(
        {'question': 'Email', 'label': 'Email', 'type': 'email', 'ambiguous': False},
        {'email'},
    )
    assert result == {'status': 'verified_candidate', 'profile_key': 'email'}
    assert 'answer' not in result
    assert 'value' not in result


def test_unknown_non_contact_question_requires_review():
    result = classify_field(
        {'question': 'Will you require sponsorship?', 'label': 'Will you require sponsorship?', 'type': 'text', 'ambiguous': False},
        {'full_name', 'email', 'phone'},
    )
    assert result == {'status': 'human_review', 'reason': 'unknown_question'}


@pytest.mark.parametrize('ambiguous', [
    None,
    0,
    0.0,
    '',
    [],
    {},
    (),
    'false',
    'False',
    '0',
    'no',
    1,
    True,
])
def test_nonboolean_ambiguity_metadata_requires_review(ambiguous):
    result = classify_field(
        {
            'question': 'Email',
            'label': 'Email',
            'type': 'email',
            'ambiguous': ambiguous,
        },
        {'email'},
    )
    assert result == {
        'status': 'human_review',
        'reason': 'ambiguous_question',
    }


@pytest.mark.parametrize('question,kind,key', [
    ('Full name', 'text', 'full_name'),
    ('Email', 'email', 'email'),
    ('Phone', 'tel', 'phone'),
    ('LinkedIn', 'url', 'linkedin'),
    ('GitHub', 'url', 'github'),
])
@pytest.mark.parametrize('include_flag', [False, True])
def test_false_or_missing_ambiguity_preserves_candidates(
    question, kind, key, include_flag
):
    field = {
        'question': question,
        'label': question,
        'type': kind,
    }
    if include_flag:
        field['ambiguous'] = False
    result = classify_field(field, {key})
    assert result == {
        'status': 'verified_candidate',
        'profile_key': key,
    }


def test_malformed_ambiguity_remains_review_even_without_verified_fact():
    result = classify_field(
        {
            'question': 'Email',
            'label': 'Email',
            'type': 'email',
            'ambiguous': None,
        },
        set(),
    )
    assert result == {
        'status': 'human_review',
        'reason': 'ambiguous_question',
    }


def test_mixed_ambiguity_metadata_preserves_triage_order():
    fields = [
        {
            'question': 'Email',
            'label': 'Email',
            'type': 'email',
            'ambiguous': False,
        },
        {
            'question': 'Email',
            'label': 'Email',
            'type': 'email',
            'ambiguous': None,
        },
        {
            'question': 'Phone',
            'label': 'Phone',
            'type': 'tel',
            'ambiguous': [],
        },
        {
            'question': 'GitHub',
            'label': 'GitHub',
            'type': 'url',
        },
        {
            'question': 'LinkedIn',
            'label': 'LinkedIn',
            'type': 'email',
            'ambiguous': False,
        },
    ]
    results = triage_fields(fields, {'email', 'phone', 'github', 'linkedin'})
    assert results == [
        {'status': 'verified_candidate', 'profile_key': 'email'},
        {'status': 'human_review', 'reason': 'ambiguous_question'},
        {'status': 'human_review', 'reason': 'ambiguous_question'},
        {'status': 'verified_candidate', 'profile_key': 'github'},
        {'status': 'human_review', 'reason': 'mismatched_contact_control'},
    ]


def test_malformed_ambiguity_never_returns_candidate_data():
    result = classify_field(
        {
            'question': 'Full name',
            'label': 'Full name',
            'type': 'text',
            'ambiguous': {},
        },
        {'full_name'},
    )
    assert result == {
        'status': 'human_review',
        'reason': 'ambiguous_question',
    }
    assert 'profile_key' not in result
    assert 'answer' not in result
    assert 'value' not in result


@pytest.mark.parametrize('bad_value', [
    None,
    False,
    True,
    0,
    1,
    0.0,
    [],
    {},
    (),
    ['Email'],
    {'value': 'Email'},
])
@pytest.mark.parametrize('metadata_key', ['question', 'label'])
def test_malformed_contact_metadata_requires_review(metadata_key, bad_value):
    field = {
        'question': 'Email',
        'label': 'Email',
        'type': 'email',
        'ambiguous': False,
    }
    field[metadata_key] = bad_value
    result = classify_field(field, {'email'})
    assert result == {
        'status': 'human_review',
        'reason': 'invalid_field_metadata',
    }


@pytest.mark.parametrize('label', [
    ' ',
    '   ',
    '\t',
    '\n',
    ' \t \n ',
])
def test_whitespace_only_contact_label_requires_review(label):
    result = classify_field(
        {
            'question': 'Email',
            'label': label,
            'type': 'email',
            'ambiguous': False,
        },
        {'email'},
    )
    assert result == {
        'status': 'human_review',
        'reason': 'invalid_field_metadata',
    }


@pytest.mark.parametrize('question,kind,key', [
    ('Full name', 'text', 'full_name'),
    ('Email', 'email', 'email'),
    ('Phone', 'tel', 'phone'),
    ('LinkedIn', 'url', 'linkedin'),
    ('GitHub', 'url', 'github'),
])
def test_missing_label_preserves_verified_candidate(question, kind, key):
    result = classify_field(
        {'question': question, 'type': kind, 'ambiguous': False},
        {key},
    )
    assert result == {'status': 'verified_candidate', 'profile_key': key}


@pytest.mark.parametrize('question,kind,key', [
    ('Full name', 'text', 'full_name'),
    ('Email', 'email', 'email'),
    ('Phone', 'tel', 'phone'),
    ('LinkedIn', 'url', 'linkedin'),
    ('GitHub', 'url', 'github'),
])
def test_empty_string_label_preserves_verified_candidate(question, kind, key):
    result = classify_field(
        {
            'question': question,
            'label': '',
            'type': kind,
            'ambiguous': False,
        },
        {key},
    )
    assert result == {'status': 'verified_candidate', 'profile_key': key}


@pytest.mark.parametrize('question_value', ['', None])
def test_missing_or_empty_question_fallback_is_distinguished(question_value):
    field = {
        'label': 'Email',
        'type': 'email',
        'ambiguous': False,
    }
    if question_value is not None:
        field['question'] = question_value
    result = classify_field(field, {'email'})
    assert result == {'status': 'verified_candidate', 'profile_key': 'email'}


def test_explicit_null_question_does_not_fallback_to_verified_label():
    result = classify_field(
        {
            'question': None,
            'label': 'Email',
            'type': 'email',
            'ambiguous': False,
        },
        {'email'},
    )
    assert result == {
        'status': 'human_review',
        'reason': 'invalid_field_metadata',
    }


def test_valid_contact_label_whitespace_normalization_is_preserved():
    result = classify_field(
        {
            'question': 'Email',
            'label': '  Email  ',
            'type': 'email',
            'ambiguous': False,
        },
        {'email'},
    )
    assert result == {'status': 'verified_candidate', 'profile_key': 'email'}


def test_mixed_metadata_validation_preserves_triage_order():
    fields = [
        {'question': 'Email', 'label': 'Email', 'type': 'email', 'ambiguous': False},
        {'question': None, 'label': 'Email', 'type': 'email', 'ambiguous': False},
        {'question': 'Phone', 'label': '   ', 'type': 'tel', 'ambiguous': False},
        {'question': 'GitHub', 'type': 'url', 'ambiguous': False},
        {'question': 'LinkedIn', 'label': 'LinkedIn', 'type': 'email', 'ambiguous': False},
        {'question': 'Email', 'label': 'Email', 'type': 'email', 'ambiguous': None},
        {'question': 'Referee email', 'label': 'Referee email', 'type': 'email', 'ambiguous': False},
    ]
    results = triage_fields(fields, {'email', 'phone', 'github', 'linkedin'})
    assert results == [
        {'status': 'verified_candidate', 'profile_key': 'email'},
        {'status': 'human_review', 'reason': 'invalid_field_metadata'},
        {'status': 'human_review', 'reason': 'invalid_field_metadata'},
        {'status': 'verified_candidate', 'profile_key': 'github'},
        {'status': 'human_review', 'reason': 'mismatched_contact_control'},
        {'status': 'human_review', 'reason': 'ambiguous_question'},
        {'status': 'human_review', 'reason': 'unknown_question'},
    ]


def test_malformed_metadata_never_exposes_candidate_or_answer():
    result = classify_field(
        {
            'question': 'Full name',
            'label': False,
            'type': 'text',
            'ambiguous': False,
        },
        {'full_name'},
    )
    assert result == {
        'status': 'human_review',
        'reason': 'invalid_field_metadata',
    }
    assert 'profile_key' not in result
    assert 'answer' not in result
    assert 'value' not in result


@pytest.mark.parametrize('verified_keys', [
    'email',
    'full_name',
    ['email'],
    ('email',),
    {'email': True},
    {'email': False},
    {'email': 'verified'},
    {},
    [],
    (),
    b'email',
    None,
    0,
    1,
    True,
])
def test_invalid_verified_key_containers_require_review(verified_keys):
    result = classify_field(
        {
            'question': 'Email',
            'label': 'Email',
            'type': 'email',
            'ambiguous': False,
        },
        verified_keys,
    )
    assert result == {
        'status': 'human_review',
        'reason': 'invalid_verified_keys',
    }


@pytest.mark.parametrize('verified_keys', [
    {'email', None},
    {'email', 1},
    {'email', False},
    frozenset({'email', None}),
    frozenset({'email', 1}),
    {None},
    {1},
    frozenset({1}),
    {'email', b'phone'},
])
def test_nonstring_verified_key_members_require_review(verified_keys):
    result = classify_field(
        {
            'question': 'Email',
            'label': 'Email',
            'type': 'email',
            'ambiguous': False,
        },
        verified_keys,
    )
    assert result == {
        'status': 'human_review',
        'reason': 'invalid_verified_keys',
    }


@pytest.mark.parametrize('verified_keys', [
    {'email'},
    frozenset({'email'}),
    {'email', 'unused'},
    frozenset({'email', 'unused'}),
])
def test_valid_verified_key_containers_preserve_candidates(verified_keys):
    result = classify_field(
        {
            'question': 'Email',
            'label': 'Email',
            'type': 'email',
            'ambiguous': False,
        },
        verified_keys,
    )
    assert result == {
        'status': 'verified_candidate',
        'profile_key': 'email',
    }


@pytest.mark.parametrize('verified_keys', [set(), frozenset()])
def test_empty_verified_key_containers_preserve_unverified_review(verified_keys):
    result = classify_field(
        {
            'question': 'Email',
            'label': 'Email',
            'type': 'email',
            'ambiguous': False,
        },
        verified_keys,
    )
    assert result == {
        'status': 'human_review',
        'reason': 'unverified_profile_fact',
    }


def test_invalid_verified_keys_never_expose_candidate_or_answer():
    result = classify_field(
        {
            'question': 'Full name',
            'label': 'Full name',
            'type': 'text',
            'ambiguous': False,
        },
        {'full_name': False},
    )
    assert result == {
        'status': 'human_review',
        'reason': 'invalid_verified_keys',
    }
    assert 'profile_key' not in result
    assert 'answer' not in result
    assert 'value' not in result


@pytest.mark.parametrize('verified_keys', [
    {'email'},
    frozenset({'email'}),
])
def test_verified_key_validation_preserves_existing_safeguards(verified_keys):
    fields = [
        {'question': 'Email', 'label': 'Email', 'type': 'email', 'ambiguous': False},
        {'question': 'Email', 'label': 'Email', 'type': 'tel', 'ambiguous': False},
        {'question': 'Email', 'label': 'Email', 'type': 'email', 'ambiguous': None},
        {'question': None, 'label': 'Email', 'type': 'email', 'ambiguous': False},
        {'question': 'Referee email', 'label': 'Referee email', 'type': 'email', 'ambiguous': False},
        {'question': 'Email', 'label': 'Email', 'type': 'select-one', 'ambiguous': False},
        {'question': 'Phone', 'label': 'Phone', 'type': 'tel', 'ambiguous': False},
    ]
    assert triage_fields(fields, verified_keys) == [
        {'status': 'verified_candidate', 'profile_key': 'email'},
        {'status': 'human_review', 'reason': 'mismatched_contact_control'},
        {'status': 'human_review', 'reason': 'ambiguous_question'},
        {'status': 'human_review', 'reason': 'invalid_field_metadata'},
        {'status': 'human_review', 'reason': 'unknown_question'},
        {'status': 'human_review', 'reason': 'nontrivial_control'},
        {'status': 'human_review', 'reason': 'unverified_profile_fact'},
    ]


def test_invalid_verified_container_preserves_triage_result_order():
    fields = [
        {'question': 'Email', 'label': 'Email', 'type': 'email', 'ambiguous': False},
        {'question': 'Phone', 'label': 'Phone', 'type': 'tel', 'ambiguous': False},
        {'question': 'GitHub', 'label': 'GitHub', 'type': 'url', 'ambiguous': False},
    ]
    assert triage_fields(fields, ['email', 'phone', 'github']) == [
        {'status': 'human_review', 'reason': 'invalid_verified_keys'},
        {'status': 'human_review', 'reason': 'invalid_verified_keys'},
        {'status': 'human_review', 'reason': 'invalid_verified_keys'},
    ]
