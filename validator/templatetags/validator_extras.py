from django import template

register = template.Library()


@register.filter
def get_item(mapping, key):
    """Look up `mapping[key]` in a template (Django has no variable-key access)."""
    if not mapping:
        return None
    return mapping.get(key)
