import re

from django import template
from django.urls import reverse, NoReverseMatch

register = template.Library()


@register.simple_tag(takes_context=True)
def active_tab(context, url, css_class='active') -> str:
  try:
    pattern = '^%s$' % reverse(url)
  except NoReverseMatch:
    pattern = url

  path = context['request'].path
  return css_class if re.search(pattern, path) else ''
