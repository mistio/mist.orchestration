"""Script entity model."""
from datetime import datetime
from uuid import uuid4

import json

import mongoengine as me

from mist.api.tag.models import Tag
from mist.api.users.models import Owner
from mist.api.machines.models import Machine
from mist.api.clouds.models import Cloud
from mist.api.ownership.mixins import OwnershipMixin


class CloudifyContext(me.EmbeddedDocument):
    inputs = me.DictField()


class Template(OwnershipMixin, me.Document):
    id = me.StringField(primary_key=True,
                        default=lambda: uuid4().hex)

    name = me.StringField()
    description = me.StringField()

    owner = me.ReferenceField(Owner)

    # exec_type must be in ('executable', 'ansible', 'collectd_python_plugin')
    exec_type = me.StringField()
    location_type = me.StringField()  # must be in ('url', 'github', 'inline')
    # (url, repo, source code, depending on location_type)
    template = me.StringField()
    entrypoint = me.StringField()  # used for url (if archive) and repos
    created_at = me.DateTimeField(default=datetime.utcnow)
    last_used_at = me.DateTimeField()
    versions = me.ListField(me.StringField) # git sha's
    workflows = me.ListField()
    inputs = me.ListField()
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
        return s


class Stack(OwnershipMixin, me.Document):
    """The basic Script Model."""
    id = me.StringField(primary_key=True,
                        default=lambda: uuid4().hex)
    created_at = me.DateTimeField(default=datetime.utcnow)
    owner = me.ReferenceField(Owner, required=True)
    name = me.StringField(required=True)
    description = me.StringField()
    status = me.StringField()
    inputs = me.DictField()
    outputs = me.DictField(default={})
    node_instances = me.ListField()
    machines = me.ListField(me.ReferenceField(Machine))
    container_id = me.StringField()
    workflows = me.ListField(me.DictField())
    template = me.ReferenceField(Template)
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

    def clean(self):
        if self.node_instances:
            for instance in self.node_instances:
                cloud_id = instance["runtime_properties"].get("cloud_id")
                machine_id = instance["runtime_properties"].get("machine_id")
                if cloud_id and machine_id:
                    cloud = Cloud.objects.get(owner=self.owner, id=cloud_id,
                                              deleted=None)
                    machine = Machine.objects(cloud=cloud, machine_id=machine_id).first()
                    if not machine:
                        machine = Machine(cloud=cloud, machine_id=machine_id)
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
