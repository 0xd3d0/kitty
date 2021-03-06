# Copyright (C) 2016 Cisco Systems, Inc. and/or its affiliates. All rights reserved.
#
# This file is part of Kitty.
#
# Kitty is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.
#
# Kitty is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Kitty.  If not, see <http://www.gnu.org/licenses/>.
'''
Containers are fields that group multiple fields into a single logical unit,
they all inherit from ``Container``, which inherits from
:class:`~kitty.model.low_levele.field.BaseField`.
'''
from bitstring import Bits, BitArray
import random
from kitty.model.low_level.field import BaseField, empty_bits, Dynamic
from kitty.model.low_level.encoder import BitsEncoder, ENC_BITS_DEFAULT, ENC_BITS_BYTE_ALIGNED
from kitty.core import kassert, KittyException, khash
from kitty.model.low_level.ll_utils import RenderContext


class Container(BaseField):
    '''
    A logical unit to group multiple fields together
    '''
    _encoder_type_ = BitsEncoder

    def __init__(self, fields=[], encoder=ENC_BITS_DEFAULT, fuzzable=True, name=None):
        '''
        :type fields: field or iterable of fields
        :param fields: enclosed field(s) (default: [])
        :type encoder: BitsEncoder
        :param encoder: encoder for the container (default: ENC_BITS_DEFAULT)
        :param fuzzable: is container fuzzable (default: True)
        :param name: (unique) name of the container (default: None)

        :example:

            ::

                Container([
                    String('header_name'),
                    Delimiter('='),
                    String('header_value')
                ])
        '''
        super(Container, self).__init__(value=empty_bits, encoder=encoder, fuzzable=fuzzable, name=name)
        if isinstance(fields, BaseField):
            fields = [fields]
        self._fields = []
        self._fields_dict = {}
        self._field_idx = 0
        self._containers = []
        self._ready = False
        self.replace_fields(fields)

    # BaseField overriden API methods
    def copy(self):
        '''
        :return: a copy of the container
        '''
        dup = super(Container, self).copy()
        dup._fields = [field.copy() for field in self._fields]
        dup._fields_dict = {field.get_name(): field for field in dup._fields if field.get_name() is not None}
        dup._containers = []
        for container in self._containers:
            idx = self._fields.index(container)
            dup._containers.append(dup._fields[idx])
        for field in dup._fields:
            field._set_enclosing(dup)
        return dup

    def hash(self):
        '''
        :rtype: int
        :return: hash of the container
        '''
        hashed = super(Container, self).hash()
        for f in self._fields:
            f_hashed = f.hash()
            hashed = khash(hashed + f_hashed)
        return hashed

    def num_mutations(self):
        '''
        :return: number of mutations in the container
        '''
        self._initialize()
        res = super(Container, self).num_mutations()
        return res

    def render(self, ctx=None):
        '''
        :param ctx: rendering context in which the method was called
        :rtype: `Bits`
        :return: rendered value of the container
        '''
        self._initialize()
        render_count = 1
        if ctx is None:
            ctx = RenderContext()
            if self._need_second_pass:
                render_count = 2
        ctx.push(self)
        if self.is_default():
            self._current_rendered = self._default_rendered
        else:
            if self.offset is None:
                self.offset = 0
            for i in range(render_count):
                offset = self.offset
                rendered = BitArray()
                for field in self._fields:
                    field.set_offset(offset)
                    frendered = field.render(ctx)
                    if not isinstance(frendered, Bits):
                        raise KittyException('the field %s:%s was rendered to type %s, you should probably wrap it with appropriate encoder' % (
                            field.get_name(), type(field), type(frendered)))
                    rendered.append(frendered)
                    offset += len(frendered)
                self.set_current_value(rendered)
        ctx.pop()
        return self._current_rendered

    def set_offset(self, offset):
        '''
        Set the absolute offset of current field,
        if the field should have default value,
        set the offset of the sub fields as well.

        :param offset: absolute offset of this field (in bits)
        '''
        super(Container, self).set_offset(offset)
        if self.is_default():
            for field in self._fields:
                field.set_offset(offset)
                offset += len(field._current_rendered)

    def reset(self):
        '''
        Reset the state of the container and its internal fields
        '''
        super(Container, self).reset()
        for field in self._fields:
            field.reset()
        self._field_idx = 0

    def scan_for_field(self, field_key):
        '''
        Scan for a field in the container and its enclosed fields

        :param field_key: name of field to look for
        :return: field with name that matches field_key, None if not found
        '''
        if field_key == self.get_name():
            return self
        if field_key in self._fields_dict:
            return self._fields_dict[field_key]
        for field in self._fields:
            if isinstance(field, Container):
                resolved = field.scan_for_field(field_key)
                if resolved:
                    return resolved
        return None

    def set_session_data(self, session_data):
        '''
        Set session data in the container enclosed fields

        :param session_data: dictionary of session data
        '''
        if session_data:
            for field in self._fields:
                if isinstance(field, (Container, Dynamic)):
                    field.set_session_data(session_data)

    def is_default(self):
        '''
        Checks if the field is in its default form

        :return: True if field is in default form
        '''
        for field in self._fields:
            if not field.is_default():
                return False
        return True

    def _init(self):
        '''
        Prepare to run (if not ready)
        '''
        num = 0
        self._need_second_pass = False
        for field in self._fields:
            field._initialize()
            self._need_second_pass |= field._need_second_pass
        for field in self._fields:
            num += field.num_mutations()
        self._calculate_mutations(num)
        self._initialize_default_buffer()

    def _initialize_default_buffer(self):
        if self.is_default():
            rendered = Bits()
            for field in self._fields:
                rendered += field._initialize_default_buffer()
            self._default_rendered = rendered
        return self._default_rendered

    def _mutate(self):
        '''
        Mutate enclosed fields
        '''
        for i in range(self._field_idx, len(self._fields)):
            self._field_idx = i
            if self._current_field().mutate():
                return True
            self._current_field().reset()
        return False

    def get_field_by_name(self, name):
        '''
        :param name: name of field to get
        :return: direct sub-field with the given name
        :raises: :class:`~kitty.core.KittyException` if no direct subfield with this name
        '''
        if name in self._fields_dict:
            return self._fields_dict[name]
        raise KittyException('field named (%s) was not found in (%s)' % (self, name))

    # Container's API methods
    def append_fields(self, new_fields):
        '''
        Add fields to the container

        :param new_fields: fields to append
        '''
        for field in new_fields:
            self.push(field)
            if isinstance(field, Container):
                self.pop()

    def get_rendered_fields(self, ctx=None):
        '''
        :param ctx: rendering context in which the method was called
        :return: ordered list of the fields that will be rendered
        '''
        if ctx is None:
            ctx = RenderContext()
        ctx.push(self)
        result = []
        for f in self._fields:
            if len(f.render(ctx)):
                result.append(f)
        ctx.pop()
        return result

    def get_structure(self):
        mine = super(Container, self).get_info()
        fields = []
        for field in self._fields:
            fields.append(field.get_structure())
        mine['fields'] = fields
        return mine

    def get_info(self):
        '''
        Get info regarding the current fuzzed enclosed node

        :return: info dictionary
        '''
        field = self._current_field()
        if field:
            info = field.get_info()
            info['path'] = '%s/%s' % (self.name if self.name else '<no name>', info['path'])
        else:
            info = super(Container, self).get_info()
        return info

    def get_tree(self, depth=0):
        '''
        Get a string representation of the field tree

        :param depth: current depth in the tree (default:0)
        :return: string representing the field tree
        '''
        s = ''
        s += '%(pad)s%(desc)s\n' % {
                'pad': '  ' * depth,
                'desc': self
                }
        for field in self._fields:
            if isinstance(field, Container):
                s += field.get_tree(depth + 1)
            else:
                s += '%(pad)s%(desc)s\n' % {
                    'pad': '  ' * (depth + 1),
                    'desc': field
                    }
        return s

    def pop(self):
        '''
        Remove a the top container from the container stack
        '''
        if not self._containers:
            raise KittyException('no container to pop')
        self._containers.pop()
        if self._container():
            self._container().pop()

    def push(self, field):
        '''
        Add a field to the container, if the field is a Container itself, it should be poped() when done pushing into it

        :param field: BaseField to push
        '''
        kassert.is_of_types(field, BaseField)
        container = self._container()
        field._set_enclosing(self)
        if isinstance(field, Container):
            self._containers.append(field)
        if container:
            container.push(field)
        else:
            name = field.get_name()
            if name in self._fields_dict:
                raise KittyException('field with the name (%s) already exists in this container' % (name))
            if name:
                self._fields_dict[name] = field
            self._fields.append(field)
        return True

    def replace_fields(self, new_fields):
        '''
        Remove all fields from the container and add new fields

        :param new_fields: fields to add to the container
        '''
        self._clean_info()
        self.append_fields(new_fields)

    # Internal methods
    def _clean_info(self):
        self._fields = []
        self._fields_dict = {}
        self._field_idx = 0
        self._containers = []
        self._ready = False

    def _current_field(self):
        return self._fields[self._field_idx]

    def _container(self):
        if self._containers:
            return self._containers[-1]
        else:
            return None

    def _calculate_mutations(self, num):
        self._num_mutations = num


class ForEach(Container):
    '''
    Perform all mutations of enclosed fields for each mutation of mutated_field
    '''

    def __init__(self, mutated_field, fields=[], encoder=ENC_BITS_DEFAULT, fuzzable=True, name=None):
        '''
        :param mutated_field: (name of) field to perform mutations for each of its mutations
        :param fields: enclosed field(s) (default: [])
        :type encoder: BitsEncoder
        :param encoder: encoder for the container (default: ENC_BITS_DEFAULT)
        :param fuzzable: is container fuzzable (default: True)
        :param name: (unique) name of the container (default: None)

        :example:

            ::

                Template([
                    Group(['a', 'b', 'c'], name='letters'),
                    ForEach('letters', [
                        Group(['1', '2', '3'])
                    ])
                ])
                # results in the mutations: a1, a2, a3, b1, b2, b3, c1, c2, c3
        '''
        super(ForEach, self).__init__(fields=fields, encoder=encoder, fuzzable=fuzzable, name=name)
        kassert.not_none(mutated_field)
        self._mutated_field = mutated_field

    def hash(self):
        '''
        :rtype: int
        :return: hash of the container
        '''
        hashed = super(ForEach, self).hash()
        return khash(hashed + self._mutated_field.hash())

    def _calculate_mutations(self, num):
        self._mutated_field = self.resolve_field(self._mutated_field)
        mutated_mul = self._mutated_field.num_mutations()
        if not mutated_mul:
            mutated_mul = 1
        self._num_mutations = num * mutated_mul

    def _mutate(self):
        if self._current_index == 0:
            self._mutated_field.mutate()
        if not super(ForEach, self)._mutate():
            idx = self._current_index
            self.reset(False)
            self._current_index = idx
            # if done internal mutation, mutate the "for-each" field and than start mutating the fields again
            self._mutated_field.mutate()
            self._mutate()

    def reset(self, reset_mutated=True):
        '''
        Reset the state of the container and its internal fields

        :param reset_mutated: should reset the mutated field too (default: True)
        '''
        super(ForEach, self).reset()
        if reset_mutated:
            self._mutated_field.reset()


class Conditional(Container):
    '''
    Container that its rendering is dependant on a condition
    '''
    def __init__(self, condition, fields=[], encoder=ENC_BITS_DEFAULT, fuzzable=True, name=None):
        '''
        :type condition: an object that has a function applies(self, Container) -> Boolean
        :param condition: condition to evaluate
        :param fields: enclosed field(s) (default: [])
        :type encoder: BitsEncoder
        :param encoder: encoder for the container (default: ENC_BITS_DEFAULT)
        :param fuzzable: is container fuzzable (default: True)
        :param name: (unique) name of the container (default: None)

        :example:

            ::

                Template([
                    Group(['a', 'b', 'c'], name='letters'),
                    If(ConditionCompare('letters', '==', 'a'), [
                        Static('dvil')
                    ])
                ])
                # results in the mutations: advil, b, c
        '''
        super(Conditional, self).__init__(fields=fields, encoder=encoder, fuzzable=fuzzable, name=name)
        self._condition = condition
        self._in_render = False

    def _in_render_value(self):
        return empty_bits

    def get_rendered_fields(self, ctx=None):
        '''
        :param ctx: rendering context in which the method was called
        :return: ordered list of the fields that will be rendered
        '''
        res = []
        if ctx is None:
            ctx = RenderContext()
        if self._evaluate_condition(ctx):
            ctx.push(self)
            res = super(Conditional, self).get_rendered_fields(ctx)
            ctx.pop()
        return res

    def _evaluate_condition(self, ctx):
        raise NotImplementedError('should be implemented by a subclass')

    def copy(self):
        '''
        Copy the container, put an invalidated copy of the condition in the new container
        '''
        dup = super(Conditional, self).copy()
        condition = self._condition.copy()
        condition.invalidate()
        dup._condition = condition
        return dup

    def hash(self):
        '''
        :rtype: int
        :return: hash of the container
        '''
        hashed = super(Conditional, self).hash()
        return khash(hashed, self._condition.hash())

    def is_default(self):
        '''
        Checks if the field is in its default form

        :return: True if field is in default form
        '''
        return False

    def render(self, ctx=None):
        '''
        Only render if condition applies

        :param ctx: rendering context in which the method was called
        :rtype: `Bits`
        :return: rendered value of the container
        '''
        if ctx is None:
            ctx = RenderContext()
        self._initialize()
        if self in ctx:
            self._current_rendered = self._in_render_value()
        else:
            ctx.push(self)
            if self._evaluate_condition(ctx):
                super(Conditional, self).render(ctx)
            else:
                self.set_current_value(empty_bits)
            ctx.pop()
        return self._current_rendered


class If(Conditional):
    '''
    Render only if condition evalutes to True
    '''

    def _evaluate_condition(self, ctx):
        return self._condition.applies(self, ctx)


class IfNot(Conditional):
    '''
    Render only if condition evalutes to False
    '''

    def _evaluate_condition(self, ctx):
        return not self._condition.applies(self, ctx)


class Meta(Container):
    '''
    Don't render enclosed fields

    :example:

        ::

            Container([
                Static('no sp'),
                Meta([Static(' ')]),
                Static('ace')
            ])
            # will render to: 'no space'
    '''

    def render(self, ctx=None):
        '''
        :param ctx: rendering context in which the method was called
        :rtype: `Bits`
        :return: empty bits
        '''
        self._current_rendered = empty_bits
        return self._current_rendered

    def get_rendered_fields(self, ctx=None):
        '''
        :param ctx: rendering context in which the method was called
        :return: ordered list of the fields that will be rendered
        '''
        return []


class Pad(Container):
    '''
    Pad the rendered value of the enclosed fields
    '''
    def __init__(self, pad_length, pad_data='\x00', fields=[], fuzzable=True, name=None):
        '''
        :param pad_length: length to pad up to (in bits)
        :param pad_data: data to pad with (default: '\x00')
        :param fields: enclosed field(s) (default: [])
        :param fuzzable: is fuzzable (default: True)
        :param name: (unique) name of the template (default: None)
        '''
        super(Pad, self).__init__(fields=fields, encoder=ENC_BITS_DEFAULT, fuzzable=fuzzable, name=name)
        self._pad_length = pad_length
        self._pad_data = Bits(bytes=pad_data)

    def render(self, ctx=None):
        '''
        :param ctx: rendering context in which the method was called
        :rtype: `Bits`
        :return: rendered value of the container, padded if needed
        '''
        super(Pad, self).render(ctx)
        to_pad = self._pad_length - len(self._current_rendered)
        if to_pad > 0:
            padding_data = self._pad_data * (to_pad / len(self._pad_data) + 1)
            self.set_current_value(self._current_rendered + padding_data[:to_pad])
        return self._current_rendered

    def hash(self):
        '''
        :rtype: int
        :return: hash of the container
        '''
        hashed = super(Pad, self).hash()
        return khash(hashed, self._pad_length, self._pad_data)


class Repeat(Container):
    '''
    Repeat the enclosed fields. When not mutated, the repeat count is min_times
    '''

    def __init__(self, fields=[], min_times=1, max_times=1, step=1, encoder=ENC_BITS_DEFAULT, fuzzable=True, name=None):
        '''
        :param fields: enclosed field(s) (default: [])
        :param min_times: minimum number of repetitions (default: 1)
        :param max_times: maximum number of repetitions (default: 1)
        :param step: how many repetitions to add each mutation (default: 1)
        :type encoder: BitsEncoder
        :param encoder: encoder for the container (default: ENC_BITS_DEFAULT)
        :param fuzzable: is container fuzzable (default: True)
        :param name: (unique) name of the container (default: None)

        :examples:

            ::

                Repeat([Static('a')], min_times=5, fuzzable=False)
                # will render to: 'aaaaa'
                Repeat([Static('a')], min_times=5, max_times=10, step=5)
                # will render to: 'aaaaa', 'aaaaaaaaaa'
        '''
        super(Repeat, self).__init__(fields=fields, encoder=encoder, fuzzable=fuzzable, name=name)
        self._check_times(min_times, max_times, step)
        self._min_times = min_times
        self._max_times = max_times
        self._step = step
        self._repeats = (self._max_times - self._min_times) / self._step

    def _check_times(self, min_times, max_times, step):
        '''
        Make sure that the arguments are valid

        :raises: KittyException if not valid
        '''
        kassert.is_int(min_times)
        kassert.is_int(max_times)
        kassert.is_int(step)
        if not((min_times >= 0) and (max_times > 0) and (max_times >= min_times) and (step > 0)):
            raise KittyException('one of the checks failed: min_times(%d)>=0, max_times(%d)>0, max_times>=min_times, step > 0' % (min_times, max_times))

    def _in_repeat_stage(self):
        return self._current_index < self._repeats

    def _calculate_mutations(self, num):
        self._num_mutations = num + self._repeats

    def _mutate(self):
        if not self._in_repeat_stage():
            super(Repeat, self)._mutate()

    def render(self, ctx=None):
        '''
        :param ctx: rendering context in which the method was called
        :rtype: `Bits`
        :return: rendered value of the container, repeated
        '''
        self._initialize()
        times = self._min_times
        if self._mutating() and self._in_repeat_stage():
            times += (self._current_index) * self._step
        rendered = super(Repeat, self).render(ctx)
        self.set_current_value(rendered * times)
        return self._current_rendered

    def get_rendered_fields(self, ctx=None):
        '''
        :param ctx: rendering context in which the method was called
        :return: ordered list of the fields that will be rendered
        '''
        times = self._min_times
        if self._mutating() and self._in_repeat_stage():
            times += (self._current_index) * self._step
        return super(Repeat, self).get_rendered_fields(ctx) * times

    def _current_field(self):
        if self._in_repeat_stage():
            return None
        return super(Repeat, self)._current_field()

    def hash(self):
        '''
        :rtype: int
        :return: hash of the container
        '''
        hashed = super(Repeat, self).hash()
        return khash(hashed, self._min_times, self._max_times, self._step, self._repeats)


class OneOf(Container):
    '''
    Render a single field from the fields (also mutates only one field each time)
    '''

    def render(self, ctx=None):
        '''
        Render only the mutated field (or the first one if not in mutation)

        :param ctx: rendering context in which the method was called
        :rtype: `Bits`
        :return: rendered value of the container
        '''
        if ctx is None:
            ctx = RenderContext()
        ctx.push(self)
        self._initialize()
        offset = self.offset if self.offset else 0
        self._fields[self._field_idx].set_offset(offset)
        rendered = self._fields[self._field_idx].render(ctx)
        self.set_current_value(rendered)
        ctx.pop()
        return self._current_rendered

    def get_rendered_fields(self, ctx=None):
        '''
        :param ctx: rendering context in which the method was called
        :return: ordered list of the fields that will be rendered
        '''
        if ctx is None:
            ctx = RenderContext()
        ctx.push(self)
        current = self._fields[self._field_idx]
        res = current.get_rendered_fields(ctx)
        ctx.pop()
        return res

    def _initialize_default_buffer(self):
        self._default_rendered = self._fields[self._field_idx]._initialize_default_buffer()
        return self._default_rendered

    def _calculate_mutations(self, num):
        '''
        Each element, with its original value, is a mutation by itself.
        '''
        self._num_mutations = num + len(self._fields)

    def _mutate(self):
        if self._current_index < len(self._fields):
            self._field_idx = self._current_index
            return True
        elif self._current_index == len(self._fields):
            self._field_idx = 0
        return super(OneOf, self)._mutate()


class TakeFrom(OneOf):
    '''
    Render to only part of the enclosed fields, performing all mutations on them
    '''
    def __init__(self, fields=[], min_elements=1, max_elements=None, encoder=ENC_BITS_DEFAULT, fuzzable=True, name=None):
        '''
        :type fields: field or iterable of fields
        :param fields: enclosed field(s) (default: [])
        :param min_elements: minimum number of elements in the sub set
        :param max_elements: maximum number of elements in the sub set
        :type encoder: BitsEncoder
        :param encoder: encoder for the container (default: ENC_BITS_DEFAULT)
        :param fuzzable: is container fuzzable (default: True)
        :param name: (unique) name of the container (default: None)
        '''
        super(TakeFrom, self).__init__(fields, ENC_BITS_DEFAULT, fuzzable, name)
        self.subcontainer_encoder = encoder
        self.min_elements = min_elements
        self.max_elements = max_elements
        self.seed = 0x1234
        self.random = random.Random()

    def _init(self):
        if self.min_elements is None:
            self.min_elements = 0
        if self.max_elements is None:
            self.max_elements = len(self._fields)
        self.max_elements = min(self.max_elements, len(self._fields))
        self.random.seed(self.seed * self.max_elements + self.min_elements)
        self._rebuild_fields()
        super(TakeFrom, self)._init()

    def _rebuild_fields(self):
        '''
        We take the original fields and create subsets of them, each subset will be set into a container.
        all the resulted containers will then replace the original _fields, since we inherit from OneOf each time only one of them will be mutated and used.
        This is super ugly and dangerous, any idea how to implement it in a better way is welcome.
        '''
        # generate new lists
        new_field_lists = []
        field_list_len = self.min_elements
        while not field_list_len > self.max_elements:
            how_many = self.max_elements + 1 - field_list_len
            i = 0
            while i < how_many:
                current = self.random.sample(self._fields, field_list_len)
                if current not in new_field_lists:
                    new_field_lists.append(current)
                    i += 1
            field_list_len += 1
        # put each list in a container
        new_containers = []
        for i, fields in enumerate(new_field_lists):
            # self.logger.info(fields)
            dup_fields = [field.copy() for field in fields]
            if self.get_name():
                name = '%s_sublist_%d' % (self.get_name(), i)
            else:
                name = 'sublist_%d' % (i)
            new_containers.append(Container(fields=dup_fields, encoder=self.subcontainer_encoder, name=name))
        self.replace_fields(new_containers)

    def reset(self):
        '''
        Reset the state of the container and its internal fields
        '''
        super(TakeFrom, self).reset()
        self.random.seed(self.seed * self.max_elements + self.min_elements)

    def hash(self):
        '''
        :rtype: int
        :return: hash of the container
        '''
        hashed = super(TakeFrom, self).hash()
        return khash(hashed, self.min_elements, self.max_elements, self.seed)

    def get_field_by_name(self, name):
        '''
        Since TakeFrom constructs sub-containers and excercises OneOf,
        It needs to skip this sub-container when looking for field by name.

        :param name: name of field to get
        '''
        return self._fields[self._field_idx].get_field_by_name(name)


class Template(Container):
    '''
    Top most container of a message, serves a the only interface to the high level model
    '''

    def __init__(self, fields=[], encoder=ENC_BITS_BYTE_ALIGNED, fuzzable=True, name=None):
        '''
        :param fields: enclosed field(s) (default: [])
        :type encoder: BitsEncoder
        :param encoder: encoder for the container (default: ENC_BITS_BYTE_ALIGNED)
        :param fuzzable: is fuzzable (default: True)
        :param name: (unique) name of the template (default: None)

        :example:

            ::

                Template([
                    Group(['a', 'b', 'c']),
                    Group(['1', '2', '3'])
                ])

                # the mutations are: a1, b1, c1, a1, a2, a3
        '''
        if name is None:
            name = 'Template'
        super(Template, self).__init__(fields=fields, encoder=encoder, fuzzable=fuzzable, name=name)

    def get_info(self):
        '''
        Get info regarding the current template state

        :return: info dictionary
        '''
        self.render()
        info = super(Template, self).get_info()
        res = {'field/%s' % k: v for (k, v) in info.items()}
        res['name'] = self.get_name()
        res['mutation/current index'] = self._current_index
        res['mutation/total number'] = self._last_index()
        res['value/rendered/hex'] = self._current_rendered.tobytes().encode('hex')
        res['value/rendered/base64'] = self._current_rendered.tobytes().encode('base64')
        res['value/rendered/len'] = len(self._current_rendered.tobytes())
        res['tree'] = self.get_tree().encode('base64')
        res['hash'] = self.hash()
        return res

    def copy(self):
        '''
        We might want to change it in the future, but for now...
        '''
        raise KittyException('Template should NOT be copied')


class Trunc(Container):
    '''
    Truncate the size of the enclosed fields
    '''
    def __init__(self, max_size, fields=[], fuzzable=True, name=None):
        '''
        :param max_size: maximum size of the container (in bits)
        :param fields: enclosed field(s) (default: [])
        :param fuzzable: is fuzzable (default: True)
        :param name: (unique) name of the template (default: None)
        '''
        super(Trunc, self).__init__(fields=fields, encoder=ENC_BITS_DEFAULT, fuzzable=fuzzable, name=name)
        self._max_size = max_size

    def render(self, ctx=None):
        '''
        :param ctx: rendering context in which the method was called
        :rtype: `Bits`
        :return: rendered value of the container
        '''
        super(Trunc, self).render(ctx)
        self._current_value = self._current_rendered
        self._current_rendered = self._current_rendered[:self._max_size]
        return self._current_rendered

    def hash(self):
        '''
        :rtype: int
        :return: hash of the container
        '''
        hashed = super(Trunc, self).hash()
        return khash(hashed, self._max_size)
