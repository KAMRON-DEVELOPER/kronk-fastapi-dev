import inspect
from typing import Union, get_args, get_origin

from fastapi import File, Form, UploadFile


def as_form(cls):
    new_parameters = []

    for field_name, model_field in cls.__fields__.items():
        field_type = model_field.annotation
        type_args = get_args(field_type)
        is_optional = get_origin(field_type) is Union and type(None) in type_args

        if is_optional or model_field.default is not None:
            param = Form(model_field.default if model_field.default is not None else None)
        elif model_field.is_required:
            param = Form(...)
        else:
            param = Form(None)

        if UploadFile in type_args:
            if is_optional:
                param = File(None)
            else:
                param = File(...)

        new_parameters.append(inspect.Parameter(field_name, inspect.Parameter.KEYWORD_ONLY, default=param, annotation=field_type))

    async def as_form_func(**kwargs):
        return cls(**kwargs)

    sig = inspect.signature(as_form_func)
    sig = sig.replace(parameters=new_parameters)
    as_form_func.__signature__ = sig  # type: ignore
    setattr(cls, "as_form", as_form_func)
    return cls
