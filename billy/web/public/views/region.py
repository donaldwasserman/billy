"""
    views that are specific to a state/region
"""
from collections import defaultdict

from django.shortcuts import redirect, render
from django.http import Http404
from django.conf import settings

from billy.models import db, Metadata, DoesNotExist, Bill
from ..forms import get_state_select_form
from .utils import templatename
from .search import search_by_bill_id


def state_selection(request):
    '''Handle submission of the state selection form
    in the base template.
    '''
    form = get_state_select_form(request.GET)
    abbr = form.data.get('abbr')
    if not abbr or len(abbr) != 2:
        raise Http404
    return redirect('state', abbr=abbr)


def state(request, abbr):
    report = db.reports.find_one({'_id': abbr})
    try:
        meta = Metadata.get_object(abbr)
    except DoesNotExist:
        raise Http404

    # count legislators
    legislators = meta.legislators({'active': True}, {'party': True,
                                                      'chamber': True})
    # Maybe later, mapreduce instead?
    party_counts = defaultdict(lambda: defaultdict(int))
    for leg in legislators:
        if 'chamber' in leg: # if statement to exclude lt. governors
            party_counts[leg['chamber']][leg['party']] += 1

    chambers = []

    for chamber in ('upper', 'lower'):
        res = {}

        # chamber metadata
        res['type'] = chamber
        res['title'] = meta[chamber + '_chamber_title']
        res['name'] = meta[chamber + '_chamber_name']

        # legislators
        res['legislators'] = {
            'count': sum(party_counts[chamber].values()),
            'party_counts': dict(party_counts[chamber]),
        }

        # committees
        res['committees_count'] = meta.committees({'chamber': chamber}).count()

        res['latest_bills'] = meta.bills({'chamber': chamber}).sort([('action_dates.first', -1)]).limit(2)
        res['passed_bills'] = meta.bills({'chamber': chamber}).sort([('action_dates.passed_' + chamber, -1)]).limit(2)

        chambers.append(res)

    joint_committee_count = meta.committees({'chamber': 'joint'}).count()

    # add bill counts to session listing
    sessions = meta.sessions()
    for s in sessions:
        try:
            s['bill_count'] = (
                report['bills']['sessions'][s['id']]['upper_count']
                + report['bills']['sessions'][s['id']]['lower_count'])
        except KeyError:
            # there's a chance that the session had no bills
            s['bill_count'] = 0

    return render(request, templatename('state'),
                  dict(abbr=abbr, metadata=meta, sessions=sessions,
                       chambers=chambers,
                       joint_committee_count=joint_committee_count,
                       statenav_active='home'))


def not_active_yet(request, args, kwargs):
    try:
        metadata = Metadata.get_object(kwargs['abbr'])
    except DoesNotExist:
        raise Http404

    return render(request, templatename('state_not_active_yet'),
                  dict(metadata=metadata, statenav_active=None))


def search(request, abbr):

    search_text = request.GET['q']

    # First try to get by bill_id.
    found_by_bill_id = search_by_bill_id(abbr, search_text)
    if found_by_bill_id:
        bill_results = found_by_bill_id
        more_bills_available = False
        legislator_results = []
        more_legislators_available = False
        found_by_id = True

    # Search bills.
    else:
        found_by_id = False
        if settings.ENABLE_ELASTICSEARCH:
            kwargs = {}
            if abbr != 'all':
                kwargs['state'] = abbr
                bill_results = Bill.search(search_text, **kwargs)
        else:
            spec = {'title': {'$regex': search_text, '$options': 'i'}}
            if abbr != 'all':
                spec.update(state=abbr)
            bill_results = db.bills.find(spec)

        # Limit the bills if it's a search.
        bill_results = list(bill_results.limit(5))
        more_bills_available = (5 < len(bill_results))

        # See if any legislator names match.
        spec = {'full_name': {'$regex': search_text, '$options': 'i'}}
        if abbr != 'all':
            spec.update(state=abbr)
        legislator_results = db.legislators.find(spec)
        more_legislators_available = (5 < legislator_results.count())
        legislator_results = legislator_results.limit(5)

    return render(request, templatename('search_results_bills_legislators'),
        dict(search_text=search_text,
             abbr=abbr,
             metadata=Metadata.get_object(abbr),
             found_by_id=found_by_id,
             bill_results=bill_results,
             more_bills_available=more_bills_available,
             legislators_list=legislator_results,
             more_legislators_available=more_legislators_available,
             bill_column_headers=('State', 'Title', 'Session', 'Introduced',
                                  'Recent Action',),
             rowtemplate_name=templatename('bills_list_row_with'
                                           '_state_and_session'),
             show_chamber_column=True,
             statenav_active=None))