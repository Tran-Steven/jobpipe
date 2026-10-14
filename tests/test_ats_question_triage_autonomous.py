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
