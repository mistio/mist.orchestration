from mist.api.exceptions import BadRequestError


class TemplateParseError(BadRequestError):
    msg = "Failed to parse template"
