from mist.api.exceptions import BadRequestError
from mist.api.exceptions import ServiceUnavailableError

class TemplateParseError(BadRequestError):
    msg = "Failed to parse template"


class WorkflowExecutionError(ServiceUnavailableError):
    msg = "Failed to execute workflow"
