from datetime import date, timedelta, datetime

from asgiref.sync import sync_to_async
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, F
from django.http import HttpResponse
from django.shortcuts import render
from django.templatetags.tz import timezone
from django.views.decorators.http import require_POST, require_GET
import httpx
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt

from lexoffice.config import get_config
from .forms import TrackActivityForm, ProjectForm, CategoryForm, UnbilledActivitySelectionForm
from .models import Category, Activity, Settings, Project, Invoice


def split_activities(activities):
  split_activities = []
  daily_durations = {}
  for activity in activities:
    start = activity.started_at
    end = activity.ended_at
    while start.date() < end.date():
      next_day = datetime.combine(
        start.date(),
        datetime.max.time(),
        tzinfo=timezone.get_current_timezone()
      )
      split_activities.append({
        'id': activity.id,
        'started_at': start,
        'ended_at': next_day,
        'project': activity.project,
        'category': activity.category,
        'is_chargeable': activity.is_chargeable,
        'notes': activity.notes,
      })
      daily_durations[start.date()] = daily_durations.get(start.date(), timedelta()) + (next_day - start)
      start = next_day + timedelta(seconds=1)
    split_activities.append({
      'id': activity.id,
      'started_at': start,
      'ended_at': end,
      'project': activity.project,
      'category': activity.category,
      'is_chargeable': activity.is_chargeable,
      'notes': activity.notes,
    })
    daily_durations[start.date()] = daily_durations.get(start.date(), timedelta()) + (end - start)
  return sorted(split_activities, key=lambda x: x['started_at'], reverse=True), daily_durations


def duration_sum(activities):
  total_duration = timedelta()
  for activity in activities:
    total_duration += activity.ended_at - activity.started_at
  return total_duration


@login_required
async def get_activities(request):
  today = date.today()
  current_year_week = f"{today.year}-W{today.isocalendar()[1]:02}"
  d = request.GET.get('week') or current_year_week
  year = int(d.split('-')[0])
  week = int(d.split('-W')[1])

  activities = await sync_to_async(Activity.objects.filter)(
    user=request.user,
    started_at__year=year,
    started_at__week=week,
  )
  activities = await sync_to_async(activities.order_by)('-started_at')
  split_activities_list, daily_durations = await sync_to_async(split_activities)(activities)
  total_duration = await sync_to_async(duration_sum)(activities)

  start_date = datetime.strptime(f'{year}-W{week - 1}-1', "%Y-W%W-%w").date()
  weekdays = [start_date + timedelta(days=i) for i in range(7)]

  settings, created = await Settings.objects.aget_or_create(user=request.user)

  return await sync_to_async(render)(
    request,
    'frontend/activities_table.html', {
      'activities': split_activities_list,
      'total_duration': total_duration,
      'week_input_val': d,
      'week_input_max': current_year_week,
      'daily_durations': daily_durations,
      'weekdays': sorted(weekdays, reverse=True),
      'settings': settings,
    })


@login_required
@require_POST
@sync_to_async
def create_activity(request):
  form = TrackActivityForm(request.POST)
  form.instance.user = request.user
  try:
    if form.is_valid():
      form.save()
  except Exception as e:
    return render(request, 'frontend/error.html', {'error': str(e)}, status=400)

  if form.errors:
    return render(request, 'frontend/error.html', {'error': form.errors.as_text()}, status=400)
  else:
    return HttpResponse(
      status=204,
      headers={
        'HX-Trigger': 'refresh-table',
      },
    )


@login_required
@require_GET
async def get_activity(request, activity_id):
  activity = await Activity.objects.aget(id=activity_id)
  return await sync_to_async(render)(request, 'projects/activity.html', {'activity': activity})


@login_required
@require_POST
@sync_to_async
def update_activity(request, activity_id):
  activity = Activity.objects.get(id=activity_id)
  form = TrackActivityForm(request.POST, instance=activity)
  try:
    if form.is_valid():
      form.save()
    else:
      return render(request, 'frontend/error.html', {'error': form.errors.as_text()}, status=400)
  except Exception as e:
    return render(request, 'frontend/error.html', {'error': str(e)}, status=400)

  return HttpResponse(
    status=204,
    headers={
      'HX-Trigger': 'refresh-table',
    },
  )


@login_required
@require_POST
async def delete_activity(request, activity_id):
  activity = await Activity.objects.aget(id=activity_id)
  await activity.adelete()

  return HttpResponse(
    status=204,
    headers={
      'HX-Trigger': 'refresh-table',
    },
  )


@login_required
@require_GET
async def get_projects(request):
  projects = await sync_to_async(Project.objects.filter)(is_archived=False)
  projects = await sync_to_async(projects.order_by)('customer__number', 'title')

  return await sync_to_async(render)(request, 'projects/project_select.html', {'items': projects})


@login_required
@require_GET
async def get_project(request, project_id):
  project = await Project.objects.aget(id=project_id)
  return await sync_to_async(render)(request, 'projects/project.html', {'project': project})


@login_required
@require_POST
@sync_to_async
def create_project(request):
  form = ProjectForm(request.POST)
  try:
    if form.is_valid():
      form.save()
  except Exception as e:
    return render(request, 'frontend/error.html', {'error': str(e)}, status=400)

  if form.errors:
    return render(request, 'frontend/error.html', {'error': form.errors.as_text()}, status=400)
  else:
    return HttpResponse(
      status=204,
      headers={
        'HX-Trigger': 'refresh-table',
      },
    )


@login_required
@require_POST
@sync_to_async
def update_project(request, project_id):
  project = Project.objects.get(id=project_id)
  form = ProjectForm(request.POST, instance=project)
  try:
    if form.is_valid():
      form.save()
    else:
      return render(request, 'frontend/error.html', {'error': form.errors.as_text()}, status=400)
  except Exception as e:
    return render(request, 'frontend/error.html', {'error': str(e)}, status=400)

  return HttpResponse(
    status=204,
    headers={
      'HX-Trigger': 'refresh-table',
    },
  )


@login_required
@require_POST
async def delete_project(request, project_id):
  project = await Project.objects.aget(id=project_id)
  await project.adelete()

  return HttpResponse(
    status=204,
    headers={
      'HX-Trigger': 'refresh-table',
    },
  )


@login_required
@require_GET
async def get_categories(request, category_id=None):
  selected_category = None
  if category_id:
    selected_category = await Category.objects.aget(id=category_id)

  project_id = request.GET.get('project')
  categories = await sync_to_async(Category.objects.filter)(projects=project_id)

  return await sync_to_async(render)(
    request, 'projects/category_select.html', {'categories': categories, 'selected_category': selected_category})


@login_required
@require_GET
async def get_category(request, category_id):
  category = await Category.objects.aget(id=category_id)
  return await sync_to_async(render)(request, 'projects/category.html', {'category': category})


@login_required
@require_POST
@sync_to_async
def create_category(request):
  form = CategoryForm(request.POST)
  try:
    if form.is_valid():
      form.save()
  except Exception as e:
    return render(request, 'frontend/error.html', {'error': str(e)}, status=400)

  if form.errors:
    return render(request, 'frontend/error.html', {'error': form.errors.as_text()}, status=400)
  else:
    return HttpResponse(
      status=204,
      headers={
        'HX-Trigger': 'refresh-table',
      },
    )


@login_required
@require_POST
@sync_to_async
def update_category(request, category_id):
  category = Category.objects.get(id=category_id)
  form = CategoryForm(request.POST, instance=category)
  try:
    if form.is_valid():
      form.save()
    else:
      return render(request, 'frontend/error.html', {'error': form.errors.as_text()}, status=400)
  except Exception as e:
    return render(request, 'frontend/error.html', {'error': str(e)}, status=400)

  return HttpResponse(
    status=204,
    headers={
      'HX-Trigger': 'refresh-table',
    },
  )


@login_required
@require_POST
async def delete_category(request, category_id):
  category = await Category.objects.aget(id=category_id)
  await category.adelete()

  return HttpResponse(
    status=204,
    headers={
      'HX-Trigger': 'refresh-table',
    },
  )


# Statistics

@login_required
@require_GET
@sync_to_async
def count_activities_per_unit(request, unit: str):
  labels = []
  data = []

  days = request.GET.get('days', 1)
  chart_type = request.GET.get('chart_type', 'pie')
  customer_id = request.GET.get('customer_id', 'all')
  chargeable = request.GET.get('chargeable', 'all')

  activities = Activity.objects.filter(
    user=request.user,
    started_at__gte=date.today() - timedelta(days=float(days))
  )

  if customer_id != 'all':
    activities = activities.filter(project__customer_id=customer_id)

  if chargeable != 'all':
    activities = activities.filter(is_chargeable=(chargeable=='true'))

  match unit:
    case 'project':
      target = 'project__title'
    case 'category':
      target = 'category__title'
    case 'customer':
      target = 'project__customer__name'
      activities = activities.filter(project__customer__isnull=False)
    case _:
      return HttpResponse(status=400)

  queryset = activities.values(target).annotate(total_duration=Sum(F('ended_at') - F('started_at')))

  queryset = [{'unit': item[target], 'total_duration': item['total_duration']} for item in queryset]

  for item in queryset:
    labels.append(item['unit'])
    data.append(item['total_duration'].total_seconds() / 3600)  # Convert duration to hours

  match chart_type:
    case 'bar':
      template = 'projects/charts/bar_chart.html'
    case 'pie':
      template = 'projects/charts/pie_chart.html'
    case _:
      return HttpResponse(status=400)

  return render(request, template,
                                     {'labels': labels, 'data': data, 'unit': unit})


@login_required
@require_GET
@sync_to_async
def chargeable_activities(request):
  labels = []
  data = []

  days = request.GET.get('days', 1)
  chart_type = request.GET.get('chart_type', 'pie')
  customer_id = request.GET.get('customer_id', 'all')

  activities = Activity.objects.filter(
    user=request.user,
    started_at__gte=date.today() - timedelta(days=float(days))
  )

  if customer_id != 'all':
    activities = activities.filter(project__customer_id=customer_id)

  queryset = activities.values('is_chargeable').annotate(total_duration=Sum(F('ended_at') - F('started_at')))
  queryset = [{'is_chargeable': item['is_chargeable'], 'total_duration': item['total_duration']} for item in queryset]

  for item in queryset:
    labels.append('Chargeable' if item['is_chargeable'] else 'Non-chargeable')
    data.append(item['total_duration'].total_seconds() / 3600)  # Convert duration to hours

  match chart_type:
    case 'bar':
      template = 'projects/charts/bar_chart.html'
    case 'pie':
      template = 'projects/charts/pie_chart.html'
    case _:
      return HttpResponse(status=400)

  return render(request, template, {'labels': labels, 'data': data, 'unit': 'chargeable'})


@login_required
@require_GET
async def invoice_list(request):
    invoices = await sync_to_async(lambda: list(Invoice.objects.select_related('customer').prefetch_related('activities').order_by('-created_at')))()
    return await sync_to_async(render)(request, 'frontend/invoices.html', {'invoices': invoices})

@login_required
@require_GET
@sync_to_async
def invoice_form(request):
    # If htmx GET, pass request.GET as data to bind the form and preserve selection
    form = UnbilledActivitySelectionForm(data=request.GET if request.GET else None)
    return render(request, 'projects/invoice_form.html', {'form': form})

@login_required
@require_POST
@sync_to_async
def process_invoice_form(request):
    form = UnbilledActivitySelectionForm(request.POST)
    if form.is_valid():
        customer = form.cleaned_data['customer']
        activities = form.cleaned_data['activities']
        # Fetch customer contact data from Lexware API
        api_token = get_config().token
        contact_url = f"https://api.lexware.io/v1/contacts/{customer.id}"
        headers = {
            "Authorization": f"Bearer {api_token}",
            "Accept": "application/json"
        }
        try:
            response = httpx.get(contact_url, headers=headers, timeout=30)
            response.raise_for_status()
            contact_data = response.json()
        except Exception as e:
            return render(request, 'projects/invoice_form.html', {'form': form, 'error': f'Failed to fetch customer data: {e}'})

        # Extract address and company info
        billing_address = (contact_data.get('addresses', {}).get('billing') or [{}])[0]
        company = contact_data.get('company', {})
        org_name = company.get('name', customer.name)
        zip_code = billing_address.get('zip', '-')
        city = billing_address.get('city', '-')
        country_code = billing_address.get('countryCode', 'DE')
        street = billing_address.get('street', '-')
        supplement = billing_address.get('supplement', '')

        # Prepare line items for Lexware
        line_items = []
        total_net = 0

        for activity in activities:
            duration = (activity.ended_at - activity.started_at).total_seconds() / 3600
            price_per_hour = 80 # TODO: Set hourly rate in database (e.g., per project, customer, or globally (in Settings))
            rounded_duration = round(duration, 2)
            total_net += round(rounded_duration * price_per_hour, 2)
            line_items.append({
                "type": "custom",
                "name": f"{activity.category.title} ({activity.project.title})",
                "description": f"{activity.notes}",
                "quantity": rounded_duration,
                "unitName": "Stunde",
                "unitPrice": {
                    "currency": "EUR",
                    "netAmount": price_per_hour,
                    "taxRatePercentage": 0 # 19 % VAT can be added if needed
                },
                "discountPercentage": 0
            })
        payment_duration = 14  # days
        invoice_payload = {
            "voucherDate": to_iso8601(datetime.now(timezone.get_current_timezone())),
            "address": {
                "contactId": str(customer.id),  # Ensure UUID is a string
                "name": org_name,
                "supplement": supplement,
                "street": street,
                "zip": zip_code,
                "city": city,
                "countryCode": country_code,
            },
            "lineItems": line_items,
            "totalPrice": {"currency": "EUR"},
            "taxConditions": {"taxType": "vatfree"},
            "paymentConditions": {
              "paymentTermLabel": f"Bitte überweisen Sie den Betrag bis zum {(datetime.now() + timedelta(days=payment_duration)).strftime('%d.%m.%Y')} auf das unten angegebene Bankkonto.",
              "paymentTermDuration": payment_duration
            },
            "shippingConditions": {
              "shippingType": "serviceperiod",
              "shippingDate": to_iso8601(min(activity.started_at for activity in activities)),
              "shippingEndDate": to_iso8601(max(activity.ended_at for activity in activities))

            },
            "title": "Rechnung",
            "introduction": "Vielen Dank für Ihren Auftrag.\nMeine Produkte und Leistungen stelle ich Ihnen wie folgt in Rechnung.",
            "remark": "Sind Sie mit meinen Leistungen zufrieden? Ich freue mich über Ihr Feedback und eine Weiterempfehlung."
        }
        api_url = f"https://api.lexware.io/v1/invoices"
        headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        try:
            response = httpx.post(api_url, json=invoice_payload, headers=headers, timeout=30)
            response.raise_for_status()
            data = response.json()
            invoice_id = data.get("id")
            invoice_url = data.get("resourceUri")
            invoice = Invoice.objects.create(
                customer=customer,
                lexware_id=invoice_id,
                lexware_url=invoice_url,
                total_amount=total_net,
                finalized=False
            )
            for activity in activities:
                activity.billed = True
                activity.lexware_id = invoice_id
                activity.lexware_url = invoice_url
                activity.invoice = invoice
                activity.save()
            invoices = Invoice.objects.select_related('customer').prefetch_related('activities').order_by('-created_at')
            if request.headers.get('HX-Request'):
                return render(request, 'frontend/invoices.html', {'invoices': invoices})
            else:
                return render(request, 'projects/invoice_table.html', {'invoices': invoices})
        except Exception as e:
            return render(request, 'projects/invoice_form.html', {'form': form, 'error': f'API error: {e}, Response: {response.text}'})
    return render(request, 'projects/invoice_form.html', {'form': form, 'error': 'Invalid selection'})

@login_required
@require_POST
async def delete_invoice(request, invoice_id):
    invoice = await Invoice.objects.aget(id=invoice_id)
    # Delete from Lexware API if possible
    if invoice.lexware_id:
        api_token = get_config().token
        api_url = f"https://api.lexware.io/v1/invoices/{invoice.lexware_id}"
        headers = {
            "Authorization": f"Bearer {api_token}",
            "Accept": "application/json"
        }
        async with httpx.AsyncClient() as client:
            response = await client.delete(api_url, headers=headers, timeout=30)
            print(response.status_code, response.text)
    # Set related activities back to billable and clear invoice fields and invoice FK
    await invoice.activities.aupdate(
      billed=False,
      invoice=None
    )
    await invoice.adelete()
    return HttpResponse(status=204)

@login_required
@require_GET
@sync_to_async
def customer_select(request):
    from lexoffice.models import Customer
    customers = Customer.objects.filter(
        projects__activities__billed=False,
        projects__activities__ended_at__isnull=False,
        projects__activities__category__is_chargeable=True
    ).distinct().order_by('name')
    return render(request, 'projects/customer_select.html', {'customers': customers})

@login_required
@require_GET
@sync_to_async
def invoice_table(request):
    invoices = Invoice.objects.select_related('customer').prefetch_related('activities').order_by('-created_at')
    return render(request, 'projects/invoice_table.html', {'invoices': invoices})

def to_iso8601(dt: datetime) -> str:
    """Convert datetime to ISO 8601 format with milliseconds and timezone."""
    return dt.astimezone().isoformat(timespec='milliseconds')
