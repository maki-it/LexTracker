from django.db.models import QuerySet
from django.http.response import HttpResponse
from django.shortcuts import render
from pydantic import UUID4

from asgiref.sync import sync_to_async
from django.contrib.auth.decorators import login_required

from .models import Category


@login_required
async def get_categories(request):
  """
  Get all categories
  :param request:
  :return:
  """

  project_id: UUID4 = request.GET.get('project')
  categories = await sync_to_async(Category.objects.filter)(projects=project_id)
  return await sync_to_async(render)(request, 'projects/select_form.html', {'items': categories})
