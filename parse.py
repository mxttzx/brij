import typing
import types 

from collections.abc import Iterable, Mapping as _Mapping

from dataclasses import dataclass
from typing import get_args, get_origin, Protocol, Any as DEFAULT


class TypeNode(Protocol): 
    def delegate(self, ctx) -> callable: 
        ...

@dataclass
class TypePrimitive[T](TypeNode): 
    _type: type[T]

    def delegate(self, ctx) -> callable:
        return lambda val: val 

@dataclass
class TypeContainer[T](TypeNode): 
    _type: type[T]
    node: TypeNode

    def delegate(self, ctx) -> callable:
        itm = self.node.delegate(ctx)

        if self._type is list:
            return lambda val: [itm(i) for i in val]
        elif self._type is set:
            return lambda val: {itm(i) for i in val}

        return lambda val: self._type(itm(i) for i in val)

@dataclass
class TypeDict(TypeNode):
    tkey: TypeNode
    tval: TypeNode 

    def delegate(self, ctx) -> callable:
        nkey = self.tkey.delegate(ctx)
        nval = self.tval.delegate(ctx)
        return lambda val: {nkey(k): nval(v) for k, v in val.items()}

@dataclass
class TypeMap[T](TypeNode): 
    """
    This is a registered mapping type node. 
    These types should be delegated to an existing mapper instance.
    Their target should exist in the mapper registry.
    """
    _type: type[T]

    def delegate(self, ctx) -> callable:
        return lambda val: ctx[self._type].map(val)

class TypeParser[T]: 
    @staticmethod 
    def _oftype(annotation: type[T], tup: tuple[type, ...]) -> bool:
        return isinstance(annotation, type) and issubclass(annotation, tup)

    @classmethod 
    def parse(cls, annotation: type[T]) -> TypeNode:
        parent = get_origin(annotation)
        children = get_args(annotation)
       
        if not children:
            if cls._oftype(annotation, (DEFAULT, str, int, bool, bytes, float)):
                return TypePrimitive(annotation)

            return TypeMap(annotation)
        
        # Users should not be using typing.Union
        if parent in (types.UnionType, typing.Union):
            args = [arg for arg in children is not type(None)]
            if args:
                return cls.parse(args[0]) 
             
            return TypePrimitive() # TODO: This is likely wrong

        if cls._oftype(parent, (_Mapping,)):
            tkey = cls.parse(args[0])
            tval = cls.parse(args[1])

            return TypeDict(tkey, tval)
        
        if cls._oftype(parent, (Iterable,)):
            node = cls.parse(args[0])
            # TODO: might need to change this
            # I dont want another inspect call here so we will see if it breaks eventually 
            # container = list if inspect.isabstract(parent) else parent
            return TypeContainer(parent, node)

        return TypeMap(annotation)

            


