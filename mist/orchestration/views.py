import logging
import datetime
import mongoengine as me

from pyramid.response import Response

from mist.api.helpers import trigger_session_update

from mist.api.helpers import view_config
from mist.orchestration import methods
from mist.api.auth.methods import auth_context_from_request
from mist.api.helpers import params_from_request
from mist.api.exceptions import NotFoundError
from mist.api.exceptions import RequiredParameterMissingError
from mist.api.exceptions import BadRequestError
from mist.api.exceptions import BadRequestError
from mist.api.exceptions import ConflictError

from mist.api.tag.models import Tag
from mist.api.tag.methods import add_tags_to_resource

from mist.api.logs.methods import get_stories

from mist.orchestration.models import Template, Stack
from mist.orchestration.exceptions import TemplateParseError

from mist.api import config

log = logging.getLogger(__name__)

OK = Response("OK", 200)

log = logging.getLogger(__name__)


# SEC TODO add required permissions in docstring
@view_config(route_name='api_v1_templates', request_method='POST',
             renderer='json')
def add_template(request):
    """
    Tags: orchestration
    ---
    Add template to user/org templates
    ---
    name:
      type: string
      required: true
    template_url:
      type: string
      required: false
    template_github:
      type: string
      required: false
    template_inline:
      type: string
      required: false
    location_type:
      type: string
      required: true
    entrypoint:
      type: string
    exec_type:
      type: string
      required: true
    description:
      type: string
    """
    # SEC
    auth_context = auth_context_from_request(request)
    # /SEC

    params = params_from_request(request)
    required_params = ('name', 'location_type', 'exec_type')
    optional_params = ('entrypoint', 'description', 'setuid')
    kwargs = {}
    for key in required_params:
        if not params.get(key):
            raise RequiredParameterMissingError(key)
        kwargs[key] = params.get(key)
    for key in optional_params:
        if params.get(key):
            kwargs[key] = params.get(key)

    if kwargs.get('setuid') and not auth_context.is_owner():
        raise BadRequestError('The "Run as Owner" option may not be specified '
                              'by non-Owners')

    if params.get('location_type') == 'github':
        if not params.get('template_github'):
            raise RequiredParameterMissingError('template_github')
        kwargs['template'] = params.get('template_github')

    if params.get('location_type') == 'url':
        if not params.get('template_url'):
            raise RequiredParameterMissingError('template_url')
        kwargs['template'] = params.get('template_url')

    if params.get('location_type') == 'inline':
        if not params.get('template_inline'):
            raise RequiredParameterMissingError('template_inline')
        kwargs['template'] = params.get('template_inline')

    required_tags, _ = auth_context.check_perm('template', 'add', None)
    template = Template(owner=auth_context.owner, **kwargs)
    try:
        template = methods.analyze_template(template)
    except Exception as e:
        raise TemplateParseError(str(e).split('}')[-1].strip())

    # Set ownership.
    template.assign_to(auth_context.user)

    # Attempt to save.
    try:
        template.save()
    except me.ValidationError as err:
        log.error('Error saving %s: %s', template, err.to_dict())
        raise BadRequestError({'msg': str(err),
                               'errors': err.to_dict()})
    except me.NotUniqueError as err:
        log.error('%s is not unique: %s', template, err)
        raise ConflictError('Template "%s" already exists' % template.name)

    # SEC
    auth_context.org.mapper.update(template)

    # FIXME: This is in an if/else statement, since required_tags may be None.
    # Also, add_tags_to_resource may unnecessarily update the RBAC Mappings
    # even with an empty tags dict. A trigger_session_update needs to be called
    # explicitly, if not invoked from within add_tags_to_resource. WTF!
    if required_tags:
        add_tags_to_resource(auth_context.owner,
                             [{'resource_type': 'template',
                               'resource_id': template.id}],
                             list(required_tags.items()))
    else:
        trigger_session_update(auth_context.owner, ['templates'])

    return template.as_dict()


@view_config(route_name='api_v1_template', request_method='DELETE',
             renderer='json')
def delete_template(request):
    """
    Tags: orchestration
    ---
    Delete template given REMOVE permission has been granted
       Users may delete a template
    ---
    template_id:
      type: string
    """
    auth_context = auth_context_from_request(request)
    template_id = request.matchdict['template_id']

    # SEC require REMOVE permission on script
    auth_context.check_perm('template', 'remove', template_id)
    # /SEC

    try:
        template = Template.objects.get(owner=auth_context.owner,
                                        id=template_id, deleted=None)
        template.update(set__deleted=datetime.datetime.utcnow())
        trigger_session_update(auth_context.owner, ['templates'])
    except Template.DoesNotExist:
        raise NotFoundError("Template not found")
    return OK


@view_config(route_name='api_v1_template', request_method='PUT',
             renderer='json')
def edit_template(request):
    """
    Tags: orchestration
    ---
    Edit template given EDIT permission has been granted
    Users may edit a template's name and description
    ---
    template_id:
      type: string
    name:
      type: string
    description:
      type: string
    """
    auth_context = auth_context_from_request(request)
    template_id = request.matchdict['template_id']
    params = params_from_request(request)
    template_name = params.get('name')
    template_description = params.get('description')

    if not template_name:
        raise RequiredParameterMissingError('name')

    # SEC require EDIT permission on script
    auth_context.check_perm('template', 'edit', template_id)
    # /SEC

    try:
        template = Template.objects.get(owner=auth_context.owner,
                                        id=template_id, deleted=None)
        template.update(set__name=template_name, set__description=template_description)
        trigger_session_update(auth_context.owner, ['templates'])
    except Template.DoesNotExist:
        raise NotFoundError("Template not found")
    return OK


# SEC TODO add required permissions to docstring
@view_config(route_name='api_v1_templates', request_method='GET', renderer='json')
def list_templates(request):
    """
    Tags: orchestration
    ---
    List user templates
    """

    # SEC
    auth_context = auth_context_from_request(request)
    # /SEC
    auth_context.check_perm('template', 'read', None)
    return methods.filter_list_templates(auth_context)


# SEC TODO add required permissions to docstring
@view_config(route_name='api_v1_stacks', request_method='GET', renderer='json')
def list_stacks(request):
    """
    Tags: orchestration
    ---
    List user stacks
    """
    auth_context = auth_context_from_request(request)
    # SEC
    auth_context.check_perm('stack', 'read', None)
    return methods.filter_list_stacks(auth_context)


# SEC TODO add required permissions to docstring
@view_config(route_name='api_v1_template', request_method='GET', renderer='json')
def show_template(request):
    """
    Tags: orchestration
    ---
    Show template details and job history
    """
    auth_context = auth_context_from_request(request)

    template_id = request.matchdict['template_id']

    # SEC
    auth_context.check_perm('template', 'read', template_id)

    try:
        template = Template.objects.get(owner=auth_context.owner,
                                        id=template_id, deleted=None)
    except:
        raise NotFoundError("Template not found")
    return template.as_dict()


# SEC FIXME document permissions in docstring
@view_config(route_name='api_v1_stacks', request_method='POST', renderer='json')
def create_stack(request):
    """
    Tags: orchestration
    ---
    Start a template job to run the template
    """
    auth_context = auth_context_from_request(request)

    # SEC
    stack_tags, _ = auth_context.check_perm('stack', 'create', None)

    params = request.json_body
    template_id = params.get('template_id')
    stack_name = params.get('name')
    stack_description = params.get('description')
    deploy = params.get("deploy")
    if not stack_name:
        raise RequiredParameterMissingError("name")
    if not template_id:
        raise RequiredParameterMissingError("template_id")
    try:
        template = Template.objects.get(owner=auth_context.owner,
                                        id=template_id, deleted=None)
    except:
        raise NotFoundError("Template not found")

    # SEC
    auth_context.check_perm("template", "apply", template_id)
    stack = Stack(owner=auth_context.owner, template=template,
                  name=stack_name, description=stack_description)
    # /SEC

    ret = {}
    inputs = params.get("inputs")
    template_inputs = [i.get('name') for i in template.inputs]

    # Process tags. Propagate the Template's tags, if appropriate.
    if 'mist_tags' in inputs:
        tags = inputs.get('mist_tags', {})
        if not isinstance(tags, dict):
            if not isinstance(tags, list):
                raise BadRequestError('Expecting a dictionary or list of tags')
            if not all(isinstance(t, dict) and len(t) is 1 for t in tags):
                raise BadRequestError('The list of tags should consist of '
                                      'single-item dictionaries')
            tags = {key: value for t in tags for key, value in t.items()}

        tags.update({t.key: t.value for t in Tag.objects(
            resource_type='template', resource_id=template.id)})
        inputs['mist_tags'] = tags

        for i in inputs:
            if i.startswith('mist_machine') and tags:
                inputs[i]['tags'] = tags

    if 'mist_uri' in template_inputs:
        inputs['mist_uri'] = config.PORTAL_URI

    stack.deploy = deploy

    # Set ownership.
    stack.assign_to(auth_context.user)

    ret = stack.as_dict()

    if stack_tags:
        add_tags_to_resource(auth_context.owner,
                             [{'resource_type': 'stack',
                               'resource_id': stack.id}],
                             stack_tags)
        stack.save()

    job_id = methods.run_workflow(auth_context, stack,
                                  "install", inputs)
    if job_id:
        ret['job_id'] = job_id

    # SEC
    auth_context.org.mapper.update(stack)

    trigger_session_update(auth_context.owner, ['stacks'])
    return ret


# SEC FIXME implement & document permission checks
@view_config(route_name='api_v1_stack', request_method='POST', renderer='json')
def run_workflow(request):
    """
    Tags: orchestration
    ---
    Start a template job to run the template
    """
    auth_context = auth_context_from_request(request)
    params = request.json_body
    stack_id = request.matchdict["stack_id"]
    try:
        stack = Stack.objects.get(owner=auth_context.owner,
                                  id=stack_id, deleted=None)
    except:
        raise NotFoundError("Stack not found")
    inputs = params.get("inputs", None)
    workflow = params.get("workflow")
    if not workflow:
        raise RequiredParameterMissingError("workflow")
    if workflow == "install":
        stack.deploy = True
    ret = {}
    ret["job_id"] = methods.run_workflow(auth_context, stack,
                                         workflow, inputs)

    trigger_session_update(auth_context.owner, ['stacks'])

    return ret


# SEC FIXME document permission checks
@view_config(route_name='api_v1_stack', request_method='DELETE', renderer='json')
def delete_stack(request):
    """
    Tags: orchestration
    ---
    Start a template job to run the template
    """
    auth_context = auth_context_from_request(request)
    params = params_from_request(request)
    stack_id = request.matchdict["stack_id"]

    # SEC require REMOVE permission on script
    auth_context.check_perm('stack', 'remove', stack_id)

    try:
        stack = Stack.objects.get(owner=auth_context.owner,
                                  id=stack_id, deleted=None)
    except:
        raise NotFoundError("Stack not found")
    inputs = params.get("inputs", {})
    ret = {}
    ret["job_id"] = methods.run_workflow(auth_context, stack,
                                         "uninstall", inputs)
    trigger_session_update(auth_context.owner, ['stacks'])

    return ret


# SEC TODO add required permissions to docstring
@view_config(route_name='api_v1_stack', request_method='GET', renderer='json')
def show_stack(request):
    """
    Tags: orchestration
    ---
    Start a template job to run the template
    """
    auth_context = auth_context_from_request(request)
    params = params_from_request(request)
    stack_id = request.matchdict["stack_id"]

    # SEC
    auth_context.check_perm('stack', 'read', stack_id)
    try:
        stack = Stack.objects.get(owner=auth_context.owner,
                                  id=stack_id, deleted=None)
    except:
        raise NotFoundError("Stack not found")
    inputs = params.get("inputs", {})

    return stack.as_dict()
