import base64
from graphql import GraphQLResolveInfo, GraphQLError

import frappe
from frappe.model.db_query import DatabaseQuery


def list_resolver(obj, info: GraphQLResolveInfo, **kwargs):
    doctype = kwargs["doctype"]
    frappe.has_permission(doctype=doctype, throw=True)

    has_next_page = False
    has_previous_page = False
    before = kwargs.get("before")
    after = kwargs.get("after")
    first = kwargs.get("first")
    last = kwargs.get("last")
    filters = kwargs.get("filter") or []
    sort_key, sort_dir = get_sort_args(kwargs.get("sortBy"))
    _validate_connection_args(kwargs)

    original_sort_dir = sort_dir
    if last and sort_dir == "asc":
        # to get LAST, we swap the sort order
        # data will be reversed after fetch
        sort_dir = "desc"
    if last and sort_dir == "desc":
        sort_dir = "asc"

    cursor = after or before
    limit = (first or last) + 1
    requested_count = first or last

    filters = process_filters(filters)
    count = get_count(doctype, filters)

    if cursor:
        # Cursor filter should be applied after taking count
        has_previous_page = True
        cursor = from_cursor(cursor)
        filters.append([
            sort_key,
            ">" if sort_dir == "asc" else "<",
            cursor[0]
        ])

    data = get_data(doctype, filters, sort_key, sort_dir, limit)
    matched_count = len(data)
    if matched_count > requested_count:
        has_next_page = True
        data.pop()
    if sort_dir != original_sort_dir:
        data = reversed(data)

    edges = [frappe._dict(
        cursor=to_cursor(x, sort_key=sort_key), node=x
    ) for x in data]

    return frappe._dict(
        totalCount=count,
        pageInfo=frappe._dict(
            hasNextPage=has_next_page,
            hasPreviousPage=has_previous_page,
            startCursor=edges[0].cursor if len(edges) else None,
            endCursor=edges[-1].cursor if len(edges) else None
        ),
        edges=edges
    )


def _validate_connection_args(args):
    first = args.get("first")
    last = args.get("last")

    if not first and not last:
        raise GraphQLError("Argument `first` or `last` should be specified")
    if first and not (isinstance(first, int) and first > 0):
        raise GraphQLError("Argument `first` must be a non-negative integer.")
    if last and not (isinstance(last, int) and last > 0):
        raise GraphQLError("Argument `last` must be a non-negative integer.")
    if first and last:
        raise GraphQLError("Argument `last` cannot be combined with `first`.")
    if first and args.get("before"):
        raise GraphQLError("Argument `first` cannot be combined with `before`.")
    if last and args.get("after"):
        raise GraphQLError("Argument `last` cannot be combined with `after`.")


def process_filters(input_filters):
    filters = []
    operator_map = frappe._dict(
        EQ="=", NEQ="!=", LT="<", GT=">", LTE="<=", GTE=">=",
        LIKE="like", NOT_LIKE="not like"
    )
    for f in input_filters:
        filters.append([
            f.get("fieldname"),
            operator_map[f.get("operator")],
            f.get("value")
        ])

    return filters


def get_count(doctype, filters):
    return frappe.get_list(
        doctype,
        fields=["COUNT(*) as total_count"],
        filters=filters
    )[0].total_count


def get_data(doctype, filters, sort_key, sort_dir, limit):
    return frappe.get_list(
        doctype,
        fields=["name", f"\"{doctype}\" as doctype", sort_key],
        filters=filters,
        order_by=f"{sort_key} {sort_dir}",
        limit_page_length=limit
    )


def get_db_filter(doctype, filter):
    return DatabaseQuery(doctype=doctype).prepare_filter_condition(filter)


def get_sort_args(sorting_input=None):
    sort_key = "modified"
    sort_dir = "desc"
    if sorting_input and sorting_input.get("field"):
        sort_key = sorting_input.get("field").lower()
        sort_dir = sorting_input.get("direction").lower() \
            if sorting_input.get("direction") else "desc"

    return sort_key, sort_dir


def to_cursor(row, sort_key):
    _json = frappe.as_json([row.get(sort_key)])
    return frappe.safe_decode(base64.b64encode(_json.encode("utf-8")))


def from_cursor(cursor):
    return frappe.parse_json(frappe.safe_decode(base64.b64decode(cursor)))
