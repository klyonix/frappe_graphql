import inflect

import frappe
from frappe.utils import cint
from frappe.model import default_fields, display_fieldtypes, table_fields
from frappe.model.meta import Meta


def get_doctype_sdl(doctype, ignore_custom_fields=False):
    meta = frappe.get_meta(doctype)
    sdl, defined_fieldnames = get_basic_doctype_sdl(meta)

    # Extend Doctype with Custom Fields
    if not ignore_custom_fields and len(meta.get_custom_fields()):
        sdl += get_custom_field_sdl(meta, defined_fieldnames)

    # DocTypeSortingInput
    if not meta.issingle:
        sdl += get_sorting_input(meta)
        sdl += get_connection_type(meta)

    # Extend QueryType
    sdl += get_query_type_extension(meta)

    return sdl


def get_basic_doctype_sdl(meta: Meta):
    dt = format_doctype(meta.name)
    sdl = f"type {dt} implements BaseDocType {{"

    defined_fieldnames = [] + list(default_fields)

    for field in default_fields:
        if field in ("idx", "docstatus"):
            fieldtype = "Int"
        elif field in ("owner", "modified_by"):
            fieldtype = "User!"
        elif field == "parent":
            fieldtype = "BaseDocType"
        else:
            fieldtype = "String"
        sdl += f"\n  {field}: {fieldtype}"
    sdl += "\n  owner__name: String!"
    sdl += "\n  modified_by__name: String!"
    sdl += "\n  parent__name: String"

    for field in meta.fields:
        if field.fieldtype in display_fieldtypes:
            continue
        if field.fieldname in defined_fieldnames:
            continue
        if cint(field.get("is_custom_field")):
            continue
        defined_fieldnames.append(field.fieldname)
        sdl += f"\n  {get_field_sdl(field)}"
        if field.fieldtype in ("Link", "Dynamic Link"):
            sdl += f"\n  {get_link_field_name_sdl(field)}"

    sdl += "\n}"

    return sdl, defined_fieldnames


def get_custom_field_sdl(meta, defined_fieldnames):
    sdl = f"\n\nextend type {format_doctype(meta.name)} {{"
    for field in meta.get_custom_fields():
        if field.fieldtype in display_fieldtypes:
            continue
        if field.fieldname in defined_fieldnames:
            continue
        defined_fieldnames.append(field.fieldname)
        sdl += f"\n  {get_field_sdl(field)}"
        if field.fieldtype in ("Link", "Dynamic Link"):
            sdl += f"\n  {get_link_field_name_sdl(field)}"
    sdl += "\n}"

    return sdl


def get_sorting_input(meta):
    dt = format_doctype(meta.name)

    sdl = f"\n\nenum {dt}SortField {{"
    sdl += "\n  NAME"
    sdl += "\n  CREATION"
    sdl += "\n  MODIFIED"
    for field in meta.fields:
        if not field.search_index and not field.unique:
            continue
        sdl += f"\n  {field.fieldname.upper()}"
    sdl += "\n}"

    sdl += f"\n\ninput {dt}SortingInput {{"
    sdl += "\n  direction: SortDirection!"
    sdl += f"\n  field: {dt}SortField!"
    sdl += "\n}"
    return sdl


def get_connection_type(meta):
    dt = format_doctype(meta.name)
    sdl = f"\n\ntype {dt}CountableEdge {{"
    sdl += "\n  cursor: String!"
    sdl += f"\n  node: {dt}!"
    sdl += "\n}"

    sdl += f"\n\ntype {dt}CountableConnection {{"
    sdl += "\n  pageInfo: PageInfo!"
    sdl += "\n  totalCount: Int"
    sdl += f"\n  edges: [{dt}CountableEdge!]!"
    sdl += "\n}"

    return sdl


def get_query_type_extension(meta: Meta):
    dt = format_doctype(meta.name)
    sdl = "\n\nextend type Query {"
    if meta.issingle:
        sdl += f"\n  {dt}: {dt}!"
    else:
        plural = get_plural(meta.name)
        if plural == meta.name:
            prefix = "A"
            if dt[0].lower() in ("a", "e", "i", "o", "u"):
                prefix = "An"

            sdl += f"\n  {prefix}{dt}(name: String!): {dt}!"
        else:
            sdl += f"\n  {dt}(name: String!): {dt}!"

        plural_dt = format_doctype(plural)
        sdl += f"\n  {plural_dt}(filter: [DBFilterInput], sortBy: {dt}SortingInput, "
        sdl += "before: String, after: String, "
        sdl += f"first: Int, last: Int): {dt}CountableConnection!"

    sdl += "\n}\n"
    return sdl


def get_field_sdl(docfield):
    return f"{docfield.fieldname}: {get_graphql_type(docfield)}"


def get_link_field_name_sdl(docfield):
    return f"{docfield.fieldname}__name: String"


def get_graphql_type(docfield):
    string_fieldtypes = [
        "Small Text", "Long Text", "Code", "Text Editor", "Markdown Editor", "HTML Editor",
        "Date", "Datetime", "Time", "Text", "Data", "Select", "Rating", "Read Only",
        "Attach", "Attach Image", "Signature", "Color", "Barcode", "Geolocation", "Duration"
    ]
    int_fieldtypes = ["Int", "Long Int", "Check"]
    float_fieldtypes = ["Currency", "Float", "Percent"]

    graphql_type = None
    if docfield.fieldtype in string_fieldtypes:
        graphql_type = "String"
    elif docfield.fieldtype in int_fieldtypes:
        graphql_type = "Int"
    elif docfield.fieldtype in float_fieldtypes:
        graphql_type = "Float"
    elif docfield.fieldtype == "Link":
        graphql_type = f"{docfield.options.replace(' ', '')}"
    elif docfield.fieldtype == "Dynamic Link":
        graphql_type = "BaseDocType"
    elif docfield.fieldtype in table_fields:
        graphql_type = f"[{docfield.options.replace(' ', '')}!]!"
    elif docfield.fieldtype == "Password":
        graphql_type = "Password"
    else:
        frappe.throw(f"Invalid fieldtype: {docfield.fieldtype}")

    if docfield.reqd and graphql_type[-1] != "!":
        graphql_type += "!"

    return graphql_type


def get_plural(doctype):
    p = inflect.engine()
    return p.plural(doctype)


def format_doctype(doctype):
    return doctype.replace(" ", "")
