from asgiref.sync import sync_to_async
from django.shortcuts import render

# Render in a worker thread. Needed when a template evaluates querysets lazily,
# e.g. a form's ModelChoiceField, which may not query the database from async code.
arender = sync_to_async(render)
