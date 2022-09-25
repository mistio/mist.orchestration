import os
import uuid
import tempfile
import logging

import requests

from functools import cmp_to_key

import mongoengine as me

import dsl_parser.parser as parser

from mist.api import helpers as io_helpers

from mist.api.helpers import docker_run

from mist.api.mongoengine_extras import sanitize_dict

from mist.api.auth.models import ApiToken

from mist.api.tag.methods import add_tags_to_resource, get_tags_for_resource

from mist.orchestration.config import CLOUDIFY_MIST_PLUGIN_IMAGE
from mist.orchestration.helpers import download, unpack, find_path
from mist.orchestration.models import Template, Stack

from mist.api.exceptions import BadRequestError
from mist.api.exceptions import ConflictError
from mist.api.exceptions import RequiredParameterMissingError

from mist.api.logs.methods import log_event

from mist.api import config

if config.HAS_RBAC:
    from mist.rbac.tokens import SuperToken

log = logging.getLogger(__name__)

# SEC
def filter_list_templates(auth_context):
    query = {'owner': auth_context.owner, 'deleted': None}
    if not auth_context.is_owner():
        query['id__in'] = auth_context.get_allowed_resources(rtype='templates')

    templates = []
    for template in Template.objects(**query):
        tdict = template.as_dict()
        tdict['tags'] = get_tags_for_resource(auth_context.owner, template)
        templates.append(tdict)
    return templates


# SEC
def filter_list_stacks(auth_context):
    query = {'owner': auth_context.owner, 'deleted': None}
    if not auth_context.is_owner():
        query['id__in'] = auth_context.get_allowed_resources(rtype='stacks')

    stacks = []
    for stack in Stack.objects(**query):
        sdict = stack.as_dict()
        sdict['tags'] = get_tags_for_resource(auth_context.owner, stack)
        stacks.append(sdict)
    return stacks


def run_workflow(auth_context, stack, workflow, inputs=None):

    if inputs:
        stack.inputs.update({workflow: inputs})

    stack.job_id = job_id = uuid.uuid4().hex

    if stack.deploy or workflow == 'uninstall':

        auth_context.check_perm('stack', 'run_workflow', stack.id)

        # Create API Token. Generate SuperToken, if appropriate.
        token_cls = ApiToken
        if not auth_context.is_owner() and stack.template.setuid:
            if not config.HAS_RBAC:
                raise NotImplementedError()
            token_cls = SuperToken
            log.warning('A SuperToken will be generated for User %s of %s '
                        'in order to execute workflow "%s" on Stack %s',
                        auth_context.user.email, auth_context.org, workflow,
                        stack.id)

        new_api_token = token_cls()
        new_api_token.name = "stack_{0}_{1}".format(stack.name, uuid.uuid4().hex)
        new_api_token.ttl = 3600
        new_api_token.set_user(auth_context.user)
        new_api_token.orgs = [auth_context.org]
        new_api_token.save()

        inputs = inputs or stack.inputs.get(workflow)
        if workflow == 'install':
            stack.status = "start_creation"
        else:
            stack.status = 'workflow_started'

        try:
            wparams = [stack.id]
            wparams.append("-v")
            if workflow:
                wparams.append("-w")
                wparams.append(workflow)
            wparams.append("-t")
            wparams.append(new_api_token.token)
            wparams.append("-u")
            wparams.append(config.PORTAL_URI)
        except Exception as exc:
            log.error(str(exc))
            return False

        try:
            stack.save()
        except me.ValidationError as err:
            log.error('Error saving %s: %s', stack, err.to_dict())
            raise BadRequestError({'msg': str(err),
                                'errors': err.to_dict()})
        except me.NotUniqueError as err:
            log.error('%s is not unique: %s', stack, err)
            raise ConflictError('Stack "%s" already exists' % stack.name)

        log.info("docker run %s %s" % (job_id, " ".join(wparams)))

        # Set the list of ENVs to pass to the container.
        # 1. MIST_GIT_CLONE_COMMAND is the git-clone command that will be used
        #    by the container to clone the Git repo. Since the Git URL may
        #    include Basic Auth, we do not want to have it returned by the API.
        # 2. TODO
        env = ['MIST_GIT_CLONE_COMMAND=%s' % stack.template.git_clone_command]

        container = docker_run(name='orchestration-workflow-%s' % job_id,
                               image_id=CLOUDIFY_MIST_PLUGIN_IMAGE,
                               env=env, command=' '.join(wparams))

        stack.container_id = container.id
        # TODO deprecate container_id, store it in model
        log_entry = {
            'job_id': job_id,
            'stack_id': stack.id,
            'container_id': container.id,
            'user_email': auth_context.user.email,
            'owner_id': auth_context.owner.id,
            'template_id': stack.template.id,
            'workflow': workflow,
            'inputs': inputs,
            'setuid': config.HAS_RBAC and token_cls is SuperToken,
        }
        event = log_event(event_type='job', action='workflow_started', **log_entry)
        stack.workflows.append({'name': workflow,
                                'job_id': job_id,
                                'timestamp': event['time'],
                                'error': False})

    try:
        stack.save()
    except me.ValidationError as err:
        log.error('Error saving %s: %s', stack, err.to_dict())
        raise BadRequestError({'msg': str(err),
                               'errors': err.to_dict()})
    except me.NotUniqueError as err:
        log.error('%s is not unique: %s', stack, err)
        raise ConflictError('Stack "%s" already exists' % stack.name)

    return job_id


def finish_workflow(stack, job_id, workflow, exit_code, cmdout, error,
                    node_instances=None, outputs={}):
    prev_stack_status = stack.status

    if error:
        stack.status = 'error'
    else:
        stack.status = 'ok'

    # Update node instances.
    if node_instances is not None:
        node_instances = sanitize_dict(node_instances)
        stack.node_instances = node_instances

    if outputs:
        if not stack.outputs:
            stack.outputs = {}
        stack.outputs.update(outputs)

    log_entry = {
        'job_id': job_id,
        'stack_id': stack.id,
        'owner_id': stack.owner.id,
        'template_id': stack.template.id,
        'workflow': workflow,
        'exit_code': exit_code,
        'cmdout': cmdout,
        'error': error
    }
    log_event(event_type='job', action='workflow_finished', **log_entry)
    if error:
        for wkfl in stack.workflows:
            if workflow in wkfl and wkfl[workflow] == job_id:
                wkfl['error'] = True
    try:
        stack.save()
    except me.ValidationError as err:
        log.error('Error saving %s: %s', stack, err.to_dict())
        raise BadRequestError({'msg': str(err),
                               'errors': err.to_dict()})
    except me.NotUniqueError as err:
        log.error('%s is not unique: %s', stack, err)
        raise ConflictError('Stack "%s" already exists' % stack.name)

    io_helpers.trigger_session_update(stack.owner.id, ['stacks'])

    return


def get_workflows(parsed):
    workflows = []
    for workflow_name in parsed["workflows"]:
        workflows.append({"name": workflow_name,
            "params": form_inputs(parsed["workflows"][workflow_name]["parameters"])
        })
    return workflows


def analyze_template(template):
    if template.exec_type == 'cloudify':
        if template.location_type == 'github':
            with io_helpers.get_cloned_git_path(template.git_repo,
                                                template.git_branch) as tmpdir:
                path = find_path(tmpdir, template.entrypoint)
                parsed = parser.parse_from_path(path)
        elif template.location_type == 'url':
            tmpdir = tempfile.mkdtemp()
            os.chdir(tmpdir)
            path = download(template.template)
            try:
                unpack(path, tmpdir)
                path = find_path(tmpdir, template.entrypoint)
            except:
                pass
            parsed = parser.parse_from_path(path)
        elif template.location_type == 'inline':
            parsed = parser.parse(template.template)
        template.workflows = get_workflows(parsed)
        template.inputs = form_inputs(parsed["inputs"])
        return template


def form_inputs(inputs):
    ret = []

    for i in inputs:
        ret.append({
            "name" : i,
            "description": inputs[i].get("description", ""),
            "default": inputs[i].get("default", None),
            "show": i not in ['mist_uri', 'mist_username', 'mist_password', 'mist_token'],
            "required": inputs[i].get("required", False),
            "type": "text" #inputs[i].get("type", "string")
        })

    def input_cmp(a, b):
        def cmp(a, b):
            return (a > b) - (a < b)
        if 'mist_cloud' in a['name']:
            return -1
        if 'mist_cloud' in b['name']:
            return 1
        if 'mist_location' in a['name']:
            return -1
        if 'mist_location' in b['name']:
            return 1
        if 'mist_size' in a['name']:
            return -1
        if 'mist_size' in b['name']:
            return 1
        if 'mist_image' in a['name']:
            return -1
        if 'mist_image' in b['name']:
            return 1
        if a['name'].startswith('mist') and not b['name'].startswith('mist'):
            return -1
        if b['name'].startswith('mist') and not a['name'].startswith('mist'):
            return 1
        if b['name'].startswith('mist') and b['name'].startswith('mist'):
            if 'cloud' in a['name'] and 'cloud' not in b['name']:
                return -1
            if 'cloud' in b['name']:
                return 1
            if 'location' in a['name'] and 'location' not in b['name']:
                return -1
            if 'size' in a['name'] and 'size' not in b['name']:
                return -1
        return cmp(a['name'], b['name'])
    return sorted(ret, key=cmp_to_key(input_cmp))
