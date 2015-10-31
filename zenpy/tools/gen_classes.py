import glob
import json
from optparse import OptionParser
import os
import re
import sys

__author__ = 'facetoe'
from jinja2 import Template


class TemplateObject(object):
    def render(self):
        return Template(self.OBJECT_TEMPLATE).render(object=self)


class Class(TemplateObject):
    OBJECT_TEMPLATE = """
import dateutil.parser
from zenpy.lib.objects.base_object import BaseObject

class {{object.name}}(BaseObject):
        {{-object.init.render()-}}
        {{-object.properties.render()-}}
"""

    def __init__(self, name, _json):
        self.name = name
        attributes = [Attribute(attr_name=a, attr_value=v) for a, v in _json.iteritems()]
        self.init = Init(attributes)
        self.properties = Properties(attributes)


class Init(TemplateObject):
    OBJECT_TEMPLATE = """
    def __init__(self, api=None):
        self.api = api
        {% for attr in object.attributes -%}
        {% if attr.attr_name -%}
        self.{{attr.attr_name}} = None
        {% endif -%}
        {% endfor %}
    """

    def __init__(self, attributes):
        self.attributes = attributes


class Properties(TemplateObject):
    OBJECT_TEMPLATE = """
    {%- for prop in object.properties -%}
    {{- prop.render() -}}
    {% endfor %}
    """

    def __init__(self, attributes):
        self.properties = [Property(a) for a in attributes]


class Property(TemplateObject):
    OBJECT_TEMPLATE = """
    {%- if object.attribute.is_property -%}
    @property
    def {{object.attribute.object_name}}(self):
        {{- object.prop_body -}}

    @{{object.attribute.object_name}}.setter
    def {{object.attribute.object_name}}(self, {{object.attribute.object_name}}):
        {{- object.prop_setter_body -}}
    {%- endif -%}

    """

    DATE_TEMPLATE = """
        if self.{{object.attribute.key}}:
            return dateutil.parser.parse(self.{{object.attribute.key}})
    """

    PROPERTY_TEMPLATE = """
        if self.api and self.{{object.attribute.attr_name}}:
            return self.api.get_{{object.attribute.object_type}}(self.{{object.attribute.attr_name}})
    """

    SETTER_TEMPLATE_ASSIGN = """
            self.{{object.attribute.key}} = {{object.attribute.attr_assignment}}
    """

    SETTER_TEMPLATE_DEFAULT = """
            self.{{object.attribute.attr_name}} = {{object.attribute.key}}
    """

    def __init__(self, attribute):
        self.attribute = attribute
        self.prop_name = attribute.object_name
        self.prop_body = self.get_prop_body(attribute)
        self.prop_setter_body = self.get_prop_setter_body(attribute)

    def get_prop_body(self, attribute):
        if attribute.object_type == 'date':
            template = self.DATE_TEMPLATE
        else:
            template = self.PROPERTY_TEMPLATE

        return Template(template).render(object=self, trim_blocks=True)

    def get_prop_setter_body(self, attribute):
        if attribute.attr_assignment:
            template = self.SETTER_TEMPLATE_ASSIGN
        else:
            template = self.SETTER_TEMPLATE_DEFAULT
        return Template(template).render(object=self, trim_blocks=True)


class Attribute(object):
    def __init__(self, attr_name, attr_value):
        if attr_name == 'from':
            attr_name = 'from_'

        self.key = attr_name
        self.object_type = self.get_object_type(attr_name)
        self.object_name = self.get_object_name(attr_name, attr_value)
        self.attr_name = self.get_attr_name(attr_name, attr_value)
        self.attr_assignment = self.get_attr_assignment(self.object_name, self.object_type, attr_name)
        self.is_property = self.get_is_property(attr_name, attr_value)

    def get_object_type(self, attr_name):
        if attr_name in ('assignee_id', 'submitter_id', 'requester_id', 'author_id', 'updater_id'):
            object_type = 'user'
        elif attr_name in ('recipients', 'collaborator_ids'):
            object_type = 'users'
        elif attr_name in ('forum_topic_id',):
            object_type = 'topic'
        elif attr_name.endswith('_at'):
            object_type = 'date'
        elif attr_name == 'id':
            object_type = 'id'
        else:
            object_type = attr_name.replace('_id', '')
        return object_type

    def get_attr_name(self, attr_name, attr_value):
        if isinstance(attr_value, bool):
            return attr_name
        elif isinstance(attr_value, dict):
            return "_%s" % attr_name
        elif attr_name == 'id' or attr_name.endswith('_ids') or attr_name in ('tags',):
            return attr_name
        elif attr_name.endswith('_id') or attr_name.endswith('_at'):
            return attr_name
        elif attr_name.endswith('_at'):
            return "_%s" % attr_name.replace('_at', '')
        else:
            return attr_name

    def get_attr_assignment(self, object_name, object_type, key):
        if object_type != key and object_type != 'date' and key.endswith('_id'):
            return '%s.id' % object_name
        elif key.endswith('_ids'):
            return '[o.id for o in %(object_name)s]' % locals()

    def get_object_name(self, attr_name, attr_value):
        for replacement in ('_at', '_id'):
            if attr_name.endswith(replacement):
                return attr_name.replace(replacement, '')
            elif attr_name.endswith('_ids'):
                return "%ss" % attr_name.replace('_ids', '')
        return attr_name

    def get_is_property(self, attr_name, attr_value):
        if any([isinstance(attr_value, t)
                or attr_name.endswith('_at')
                or attr_name == 'id'
                or (not attr_name.endswith('ids') and isinstance(attr_value, list))
                for t in (basestring, bool)]):
            return False
        else:
            return True

    def __str__(self):
        return "[is_prop=%(is_property)s, " \
               "key=%(key)s, " \
               "obj_type=%(object_type)s, " \
               "obj_name=%(object_name)s, " \
               "attr_name=%(attr_name)s, " \
               "assn=%(attr_assignment)s]" % self.__dict__

    def __repr__(self):
        return self.__str__()


def to_snake_case(name):
    s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()


parser = OptionParser()

parser.add_option("--spec-path", "-s", dest="spec_path",
                  help="Location of .json spec", metavar="SPEC_PATH")
parser.add_option("--out-path", "-o", dest="out_path",
                  help="Where to put generated classes",
                  metavar="OUT_PATH",
                  default=os.getcwd())

(options, args) = parser.parse_args()

if not options.spec_path:
    print "--spec-path is required!"
    sys.exit()
elif not os.path.isdir(options.spec_path):
    print "--spec-path must be a directory!"
    sys.exit()

for file_path in glob.glob(os.path.join(options.spec_path, '*.json')):
    class_name = os.path.basename(os.path.splitext(file_path)[0]).capitalize()
    class_name = "".join([w.capitalize() for w in class_name.split('_')])
    class_code = Class(class_name, json.load(open(file_path))).render()
    with open(os.path.join(options.out_path, "%s.py" % to_snake_case(class_name)), 'w+') as out_file:
        out_file.write(class_code)