from graphql import GraphQLError, validate, parse
from typing import List

import frappe
from frappe.utils import cint
from . import get_schema
from .graphql import execute
from .utils.depth_limit_validator import depth_limit_validator

from .utils.http import get_masked_variables, get_operation_name


@frappe.whitelist(allow_guest=True)
def execute_gql_query():
    query, variables, operation_name = get_query()
    validation_errors = validate(
        schema=get_schema(),
        document_ast=parse(query),
        rules=(
            depth_limit_validator(
                max_depth=cint(frappe.local.conf.get("frappe_graphql_depth_limit")) or 10
            ),
        )
    )
    if validation_errors:
        output = frappe._dict(errors=validation_errors)
    else:
        output = execute(
            query=query,
            variables=variables,
            operation_name=operation_name
        )

    frappe.clear_messages()
    frappe.local.response = output
    if len(output.get("errors", [])):
        frappe.db.rollback()
        log_error(query, variables, operation_name, output)
        frappe.local.response["http_status_code"] = get_max_http_status_code(output.get("errors"))
        errors = []
        for err in output.errors:
            if isinstance(err, GraphQLError):
                err = err.formatted
            errors.append(err)
        output.errors = errors


def get_query():
    """
    Gets Query details as per the specs in https://graphql.org/learn/serving-over-http/
    """

    query = None
    variables = None
    operation_name = None
    if not hasattr(frappe.local, "request"):
        return query, variables, operation_name

    from werkzeug.wrappers import Request
    request: Request = frappe.local.request
    content_type = request.content_type or ""

    if request.method == "GET":
        query = frappe.safe_decode(request.args["query"])
        variables = frappe.safe_decode(request.args["variables"])
        operation_name = frappe.safe_decode(request.args["operation_name"])
    elif request.method == "POST":
        # raise Exception("Please send in application/json")
        if "application/json" in content_type:
            graphql_request = frappe.parse_json(request.get_data(as_text=True))
            query = graphql_request.query
            variables = graphql_request.variables
            operation_name = graphql_request.operationName

        elif "multipart/form-data" in content_type:
            # Follows the spec here: https://github.com/jaydenseric/graphql-multipart-request-spec
            # This could be used for file uploads, single / multiple
            operations = frappe.parse_json(request.form.get("operations"))
            query = operations.get("query")
            variables = operations.get("variables")
            operation_name = operations.get("operationName")

            files_map = frappe.parse_json(request.form.get("map"))
            for file_key in files_map:
                file_instances = files_map[file_key]
                for file_instance in file_instances:
                    path = file_instance.split(".")
                    obj = operations[path.pop(0)]
                    while len(path) > 1:
                        obj = obj[path.pop(0)]

                    obj[path.pop(0)] = file_key

    return query, variables, operation_name


def get_max_http_status_code(errors: List[GraphQLError]):
    http_status_code = 400
    for error in errors:
        exc = error.original_error

        if not exc:
            continue

        exc_status = getattr(exc, "http_status_code", 400)
        if exc_status > http_status_code:
            http_status_code = exc_status

    return http_status_code


def log_error(query, variables, operation_name, output):
    import traceback as tb
    tracebacks = []
    for idx, err in enumerate(output.errors):
        if not isinstance(err, GraphQLError):
            continue

        exc = err.original_error
        if not exc:
            continue
        tracebacks.append(
            f"GQLError #{idx}\n"
            + f"Http Status Code: {getattr(exc, 'http_status_code', 500)}\n"
            + f"{str(err)}\n\n"
            + f"{''.join(tb.format_exception(exc, exc, exc.__traceback__))}"
        )

    tracebacks.append(f"Frappe Traceback: \n{frappe.get_traceback()}")
    if frappe.conf.get("developer_mode"):
        frappe.errprint(tracebacks)

    tracebacks = "\n==========================================\n".join(tracebacks)
    if frappe.conf.get("developer_mode"):
        print(tracebacks)
    error_log = frappe.new_doc("GraphQL Error Log")
    error_log.update(frappe._dict(
        title="GraphQL API Error",
        operation_name=get_operation_name(query, operation_name),
        query=query,
        variables=frappe.as_json(get_masked_variables(query, variables)) if variables else None,
        output=frappe.as_json(output),
        traceback=tracebacks
    ))
    error_log.insert(ignore_permissions=True)
