from __future__ import annotations

import inspect 
import operator

from contextvars import ContextVar
from typing import get_origin, get_args, Any as DEFAULT

from util import get_signature, get_annotations, Fallback
from parse import TypeParser 

from error import (MappingNotFoundError, 
                   MappingTaskNotFoundError, 
                   MappingInvalidError, 
                   CircularReferenceError)


type RegistryKey[U, T] = tuple[U, T]
type RegistryTask[str, callable] = dict[str, callable]


class Field: 
    def __init__(self, to: str | None = None, *, fn: callable) -> None:  
        self.to = to
        self.fn = self._bind_resolver(to, fn) 
    
    # TODO: Fix this by adding additional user added context
    @staticmethod
    def _bind_resolver(to: str, fn: callable):
        sig = get_signature(fn)
        n = len(sig.parameters)

        if n == 0: 
            return lambda _inst, _src: fn() 
        elif n == 1:
            return lambda _inst, src: fn(src)
        elif n == 2:
            return fn 

        raise ValueError(f"Field resolver expected 0, 1 or 2 arguments, got {n}.")


class Mapping[U, T]:  
    _source_type: type[U]
    _target_type: type[T] 

    mapper: Mapper 
    sig: inspect.Signature

    def __init_subclass__(cls, **kwargs): 
        super().__init_subclass__(**kwargs)

        cls._field_mappings: dict[str, Field] = {} 
        cls._ignore = {}
         
        # Bind types
        for base in getattr(cls, "__orig_bases__", []):       
            if get_origin(base) is super().__thisclass__:
                cls._source_type, cls._target_type = get_args(base)
                break 
        else:
            raise MappingInvalidError(
                f"{cls.__name__} must inherit from Mapping[Source, Target].")
        
        # Bind resolvers 
        for k, val in vars(cls).items(): 
            if isinstance(val, Field):
                val.to = val.to or k
                cls._field_mappings[k] = val
         
        cls.sig = get_signature(cls._target_type.__init__)

class MapperSubject[T]: 
    _ref_stack: ContextVar[set[int] | None] = ContextVar("stack", default=None) 

    def __init__(self, target_type: T, instance: Mapper) -> None: 
        self._target_type = target_type
        self._instance = instance 
    
    @property 
    def mapper_instance(self) -> Mapper:
        return self._instance 

    @property 
    def target_type(self) -> type[T]:
        return self._target_type 
    
    def _ensure_no_circular_reference(func): 
        def wrapper(self, arg, task, *args, **kwargs):  
            visited = self._ref_stack.get() 
            is_root = visited is None 

            if is_root:
                visited = set()
                stack = self._ref_stack.set(visited)
            
            _id = id(arg)

            if _id in visited: 
                raise CircularReferenceError(
                    f"""Circular mapping detected while mapping 
                    {type(arg).__name__} to {self.target_type.__name__}""")  

            visited.add(_id)
            
            res = func(self, arg, task, *args, **kwargs)
            
            if is_root: 
                self._ref_stack.reset(stack) 
            else: 
                visited.remove(_id) 

            return res

        return wrapper 

    @_ensure_no_circular_reference
    def _do_map[U](self, arg: U, task: RegistryTask) -> T:  
        kwargs = {
            name: do_exec(arg) for name, do_exec in task.items() 
        }
        
        return self._target_type(**kwargs)

    def map[U](self, arg: U) -> T:
        source_type = type(arg) 
         
        mapping = (source_type, self.target_type)
        
        profile = self._instance._registry.get(mapping, Fallback.MISSING)
        
        if profile is Fallback.MISSING:
            raise MappingNotFoundError(
                f"""No mapping found for {source_type.__name__} to {self.target_type.__name__}.
                Please register the mapping to an existing mapper instance.""")

        task = self._instance._exec.get(profile, Fallback.MISSING)
        
        if task is Fallback.MISSING:
            raise MappingTaskNotFoundError(
                f"""No mapping task found for {source_type.__name__} to {self.target_type.__name__}.
                Something happened internally.""")
        
        return self._do_map(arg, task)

      

class Mapper:
    # TODO: Fix this by adding additional user added context
    def __init__(self, ctx, mode: Fallback.DEFAULT | Fallback.STRICT = Fallback.DEFAULT) -> None:
        self._registry: dict[RegistryKey, Mapping] = {} 
        self._exec: dict[Mapping, RegistryTask] = {} 

        self._mode = mode
    
    @property
    def registry(self) -> dict:
        return self._registry
    
    def add(self, profile: Mapping) -> None:   
        profile.mapper = self 

        task = {}

        key = (profile._source_type, profile._target_type)
        self._registry[key] = profile
        
        hints = get_annotations(profile._target_type.__init__)
    
        for name in profile.sig.parameters:
            if name == "self":
                continue
            
            field = next((f for f in profile._field_mappings.values() if f.to == name), None)
             
            if field: 
                task[name] = field.fn
            else:
                # If the annotation is not specified 
                # then the annotation will default to its set fallback value set by the user
                # The fallback value is an indicator to how the annotation SHOULD be handled
                annotation = hints.get(name, self._mode) # Is this politically correct? 
                annotation = self._fallback_maybe(annotation)

                builder = TypeParser.parse(annotation).delegate(self)

                task[name] = self._create_exec_task(name, builder)

        self._exec[profile] = task 
    
    def _fallback_maybe[T](self, annotation: dict[str, T]) -> dict[str, T]: 
        if not isinstance(annotation, Fallback):
            return annotation
        
        # TODO: Further finetuning needed here
        if annotation is Fallback.DEFAULT:
            return DEFAULT  

        elif annotation is Fallback.STRICT:
            raise Exception

    def _create_exec_task(self, name: str, builder: callable) -> callable: 
        getter = operator.attrgetter(name) 

        def run(obj):
            val = getter(obj) 

            if val is None:
                return None 

            return builder(val) 

        return run 

    def __getitem__[T](self, target_type: type[T]) -> MapperSubject[T]:
        return MapperSubject(target_type, instance=self)   


class User:
    def __init__(self, name: str, age: int, addr: str): 
        self.name = name 
        self.age = age 
        self.addr = addr

class PublicUser:
    def __init__(self, name, age: int):
        self.name = name 
        self.age = age 
    
    def func(self, x: int) -> int: 
        return x ** 2 

class UserMapping(Mapping[User, PublicUser]): ...


if __name__ == "__main__": 
    user = User("Matt", 24, "some_dummy_addr")

    mapper = Mapper()
    mapper.add(UserMapping())
    
    public_user_mapper = mapper[PublicUser]

    res = public_user_mapper.map(user) 
    
    print(getattr(res, "addr", "Nothing here..."))
    print(getattr(res, "age", "So empty, looks like something went wrong...")) 
