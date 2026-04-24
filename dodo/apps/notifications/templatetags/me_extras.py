from django import template

register = template.Library()


@register.filter
def get_item(d, key):
    """Access dict value by key in template: {{ mydict|get_item:mykey }}"""
    if d is None:
        return None
    try:
        return d.get(key)
    except AttributeError:
        try:
            return d[key]
        except (KeyError, IndexError, TypeError):
            return None


@register.filter
def split(value, delimiter):
    """Split a string by delimiter"""
    if value:
        return value.split(delimiter)
    return []


@register.filter
def abs_val(value):
    return abs(value) if value is not None else 0
