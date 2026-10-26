"""El motor Python debe dar exactamente los mismos resultados que quote-engine.ts."""
import json
from pathlib import Path
from urllib.parse import parse_qs

import pytest

from angside_ai import quote

pytestmark = pytest.mark.django_db  # la configuración comercial vive en la base de datos (se siembra con los valores por defecto)

CASES = json.loads((Path(__file__).parent / 'fixtures' / 'quote_cases.json').read_text(encoding='utf-8'))


def _pay(p):
    """Misma proyección compacta que tests/export-contract.test.ts."""
    return p and {
        'modeId': p['modeId'], 'available': p['available'], 'originalCents': p['originalCents'], 'discountCents': p['discountCents'],
        'surchargeCents': p['surchargeCents'], 'totalCents': p['totalCents'], 'initialCents': p['initialCents'],
        'installmentCents': p['installmentCents'], 'schedule': [s['amountCents'] for s in p['schedule']],
    }


@pytest.mark.parametrize('case', CASES, ids=[c['query'] or 'vacio' for c in CASES])
def test_python_matches_typescript(case):
    q = quote.compute_quote(quote.decode_state(case['query']))
    e = case['expected']
    assert q['developmentTotal'] == e['developmentTotal']
    assert q['payments'] == e['payments']
    assert q['hostingMonthly'] == e['hostingMonthly']
    assert q['billingMonthly'] == e['billingMonthly']
    assert q['maintenanceMonthly'] == e['maintenanceMonthly']
    assert q['monthlyTotal'] == e['monthlyTotal']
    assert q['developmentFrom'] == e['developmentFrom']
    assert q['monthlyFrom'] == e['monthlyFrom']
    assert q['complete'] == e['complete']
    assert q['missingBillingPlan'] == e['missingBillingPlan']
    assert [p['id'] for p in q['pending']] == e['pending']
    assert [f"{l['kind']}:{l['id']}:{l['price']}" for l in q['lines']] == e['lines']
    assert [_pay(p) for p in q['paymentOptions']] == e['paymentOptions']
    assert _pay(q['payment']) == e['payment']
    assert q['hasChatbot'] == e['hasChatbot']
    assert q['usage'] == e['usage']


@pytest.mark.parametrize('case', CASES[::7])
def test_encode_roundtrip_matches_ts(case):
    state = quote.decode_state(case['query'])
    assert quote.decode_state(quote.encode_state(state)) == state
    # Misma serialización que encodeState (comparada como parámetros, no como texto).
    assert parse_qs(quote.encode_state(state)) == parse_qs(case['query'])


def test_validate_state_rejects_invalid_combinations():
    s = quote.initial_state()
    assert quote.validate_state({**s, 'moduleIds': ['bcv']})
    assert quote.validate_state({**s, 'baseId': 'landing', 'moduleIds': ['crm']})
    assert quote.validate_state({**s, 'baseId': 'sistema', 'moduleIds': ['panel']})
    assert quote.validate_state({**s, 'baseId': 'landing', 'moduleIds': ['bcv', 'bcv']})
    assert quote.validate_state({**s, 'baseId': 'sistema', 'billingPlanId': 'pymes'})
    assert quote.validate_state({**s, 'baseId': 'landing'}) == []
