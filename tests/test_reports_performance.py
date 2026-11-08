import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.reports import definitions

pytestmark = pytest.mark.django_db

BUILDERS = {
    "cases": (definitions.build_cases, {}),
    "debtors": (definitions.build_debtors, {"include_zero": True}),
    "clients": (definitions.build_clients, {}),
}


def measure(builder, params, user):
    with CaptureQueriesContext(connection) as captured:
        result = builder(params, user)
    return len(captured), len(result.rows)


@pytest.mark.parametrize("name", BUILDERS)
def test_report_query_count_does_not_grow_with_rows(name, admin_user, case_factory):
    builder, params = BUILDERS[name]
    for _ in range(2):
        case_factory()
    measure(builder, params, admin_user)  # önbellekleri ısıtır
    few_queries, few_rows = measure(builder, params, admin_user)
    for _ in range(10):
        case_factory()
    many_queries, many_rows = measure(builder, params, admin_user)
    assert many_rows > few_rows
    assert many_queries == few_queries
