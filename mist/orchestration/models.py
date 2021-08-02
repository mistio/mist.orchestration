"""Script entity model."""
from datetime import datetime
from uuid import uuid4

import json
import urllib.parse
import mongoengine as me

from mist.api.tag.models import Tag
from mist.api.users.models import Owner
from mist.api.machines.models import Machine
from mist.api.clouds.models import Cloud
from mist.api.ownership.mixins import OwnershipMixin
from mist.api.mongoengine_extras import MistDictField, MistListField


class CloudifyContext(me.EmbeddedDocument):
    inputs = me.DictField()


class Template(OwnershipMixin, me.Document):
    id = me.StringField(primary_key=True,
                        default=lambda: uuid4().hex)

    name = me.StringField()
    description = me.StringField()

    owner = me.ReferenceField(Owner, reverse_delete_rule=me.CASCADE)

    # exec_type must be in ('executable', 'ansible', 'collectd_python_plugin')
    exec_type = me.StringField()
    location_type = me.StringField()  # must be in ('url', 'github', 'inline')
    # (url, repo, source code, depending on location_type)
    template = me.StringField()
    entrypoint = me.StringField()  # used for url (if archive) and repos
    created_at = me.DateTimeField(default=datetime.utcnow)
    last_used_at = me.DateTimeField()
    versions = me.ListField(me.StringField) # git sha's
    workflows = MistListField()
    inputs = MistListField()
    deleted = me.DateTimeField()

    setuid = me.BooleanField(default=False)

    meta = {
        'indexes': [
            {
                'fields': ['owner', 'name', 'deleted'],
                'sparse': False,
                'unique': True,
                'cls': False,
            },
        ],
    }

    @property
    def git_repo(self):
        """Return the URL to the Git repository, if applicable.

        The output of this property SHOULD NOT be exposed publicly, since the
        Git URL may include the user's password in the form of Basic Auth.

        """
        if self.location_type == "github":
            return self.template.split("/tree/")[0]
        return ""

    @property
    def git_branch(self):
        """Return the branch of the Git repository, if applicable."""
        if self.location_type == "github":
            repo_n_branch = self.template.split("/tree/")
            return "master" if len(repo_n_branch) is 1 else repo_n_branch[1]
        return ""

    @property
    def git_clone_command(self):
        """Return the git-clone command used to clone self.

        This property will return an empty string if `self.location_type` is
        not `github`. Note that git-clone can be used to clone the Template's
        repository from any Git server, not just Github.

        If `self.location_type` is `github`, then the expected URL stored in
        the `template` field should be:

        https://[user:pass@]<git-server-url>/<owner>/<repo>[/tree/<branch>]

        By default, the HEAD of the master branch is cloned, unless a specific
        branch has been requested.

        """
        if self.location_type == "github":
            return "git clone --branch %s --depth 1 %s" % (self.git_branch,
                                                           self.git_repo)
        return ""

    def touch(self):
        self.last_used_at = datetime.utcnow()

    def delete(self):
        super(Template, self).delete()
        Tag.objects(resource=self).delete()
        self.owner.mapper.remove(self)
        if self.owned_by:
            self.owned_by.get_ownership_mapper(self.owner).remove(self)

    def as_dict(self):
        s = json.loads(self.to_json())
        s["id"] = self.id
        s["created_at"] = str(self.created_at)
        s["owned_by"] = self.owned_by.id if self.owned_by else ""
        s["created_by"] = self.created_by.id if self.created_by else ""

        # Hide basic auth password.
        if self.location_type == "github":
            password = urllib.parse.urlparse(self.template).password
            if password:
                s["template"] = self.template.replace(password, "*password*")

        return s


class Stack(OwnershipMixin, me.Document):
    """The basic Stack Model."""
    id = me.StringField(primary_key=True,
                        default=lambda: uuid4().hex)
    created_at = me.DateTimeField(default=datetime.utcnow)
    owner = me.ReferenceField(Owner, required=True,
                              reverse_delete_rule=me.CASCADE)
    name = me.StringField(required=True)
    description = me.StringField()
    status = me.StringField()
    inputs = MistDictField()
    outputs = MistDictField(default={})
    node_instances = MistListField()
    machines = me.ListField(
        me.ReferenceField(Machine, reverse_delete_rule=me.PULL))
    container_id = me.StringField()
    workflows = MistListField(me.DictField())
    template = me.ReferenceField(Template, reverse_delete_rule=me.NULLIFY)
    deploy = me.BooleanField(default=False)
    # TODO: This field should be deprecated eventually
    # keeping here for backwards compatibility.
    job_id = me.StringField()
    deleted = me.DateTimeField()

    meta = {
        'strict': False,
        'allow_inheritance': True,
        'indexes': [
            {
                'fields': ['owner', 'name', 'deleted'],
                'sparse': False,
                'unique': True,
                'cls': False,
            },
        ],
    }

    @property
    def is_uninstalled(self):
        """Return True if self has been uninstalled"""
        if self.workflows:
            return (self.workflows[-1].get('name') == 'uninstall' and not
                    self.workflows[-1].get('error') and self.status == 'ok')
        return False

    def clean(self):
        # If the Stack is not installed, make sure `self.node_instances` are
        # re-set to []. This prevents left-over node instances from showing
        # up in the UI, when the Stack has been uninstalled. It also ensures
        # that we start off with a clean slate when re-installing the Stack.
        # The `outputs` and `machines` fields are also reset, since commands
        # will no longer yield any results and references to Machine objects
        # may be `DBRefs`.
        if self.is_uninstalled:
            self.outputs, self.machines, self.node_instances = {}, [], []

        if self.node_instances:
            for instance in self.node_instances:
                cloud_id = instance["runtime_properties"].get("cloud_id")
                machine_id = instance["runtime_properties"].get("machine_id")
                if cloud_id and machine_id:
                    cloud = Cloud.objects.get(owner=self.owner, id=cloud_id,
                                              deleted=None)
                    machine = Machine.objects(cloud=cloud, external_id=machine_id).first()
                    if not machine:
                        machine = Machine(cloud=cloud, external_id=machine_id)
                        machine.save()
                    if not (machine in self.machines):
                        self.machines.append(machine)

    def delete(self):
        super(Stack, self).delete()
        Tag.objects(resource=self).delete()
        self.owner.mapper.remove(self)
        if self.owned_by:
            self.owned_by.get_ownership_mapper(self.owner).remove(self)

    def as_dict(self):
        s = json.loads(self.to_json())
        s.pop('container_id', None)
        s["id"] = self.id
        s["created_at"] = str(self.created_at)
        s["owned_by"] = self.owned_by.id if self.owned_by else ""
        s["created_by"] = self.created_by.id if self.created_by else ""
        return s

    def __str__(self):
        return '%s "%s"' % (self.__class__.__name__, self.name)
