import typing 
import inspect

from enum import Enum, auto


class Fallback(Enum):   
    # Handle missing configs
    MISSING = 0
    # Mapper modes for handling missing type annotations
    DEFAULT = auto() 
    RETURN = auto()
    STRICT = auto()


def get_annotations[T](fn: callable) -> dict[str, T]:  
    return typing.get_type_hints(fn)

def get_signature(fn: callable):
    return inspect.signature(fn)
