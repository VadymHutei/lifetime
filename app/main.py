from datetime import date, datetime
import math
from functools import wraps

from flask import (
    Flask,
    render_template,
    request,
    abort,
    redirect,
    url_for
)
from dateutil.relativedelta import relativedelta

import config
import data
import lt_lib

def foo():
    return 'bar'


app = Flask(__name__)

languages, default_language = lt_lib.getLanguages()
translations = lt_lib.getTranlations()
world, regions, countries = lt_lib.getLifeExp()
genders = lt_lib.getGenders()


def lang_redirect(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        language = kwargs.get('language', False)
        if language:
            if language not in languages:
                return redirect(url_for(f.__name__))
            if language == default_language:
                return redirect(url_for(f.__name__))
        return f(*args, **kwargs)
    return decorated_function


@app.route('/', methods=['GET'])
@app.route('/<language>/', methods=['GET'])
@lang_redirect
def main(language=default_language):
    params = {
        'translate': lt_lib.getTranslator(translations, language),
        'language': language,
        'translations': {t: v[language] for t, v in translations.items()},
        'countries': countries,
        'regions': regions,
        'world': world,
        'genders': genders
    }
    return render_template('main.html', **params)


@app.route('/result', methods=['GET'])
@app.route('/<language>/result', methods=['GET'])
@lang_redirect
def result(language=default_language):
    birth_date = request.args.get('birth_date')
    if not birth_date:
        abort(400)
    birth_date = datetime.strptime(birth_date, '%Y-%m-%d').date()

    sex = request.args.get('sex', 'o')
    if not sex:
        sex = 'o'
    if sex not in data.sex:
        abort(400)

    country = request.args.get('country', 'World')
    if not country:
        country = 'World'
    if country == 'World':
        life_length_data = data.world
    elif country in data.countries:
        life_length_data = data.countries[country]
    elif country in data.regions:
        life_length_data = data.regions[country]
    else:
        abort(400)

    data_number = data.sex[sex][1]
    life_length_years = math.trunc(life_length_data[data_number])
    life_length_months = round(12 * math.modf(life_length_data[data_number])[0])
    life_length = relativedelta(
        years=life_length_years,
        months=life_length_months
    )

    today_date = date.today()

    death_date = birth_date + life_length

    lived = relativedelta(birth_date, today_date)

    life_left = relativedelta(death_date, today_date)

    params = {
        'life_left': life_left,
        'today_date': today_date.strftime('%d %b %Y'),
        'birth_date': birth_date.strftime('%d %b %Y'),
        'life_length': {
            'years': life_length_years,
            'months': life_length_months
        },
        'death_date': death_date.strftime('%d %b %Y'),
        'life_left': {
            'years': life_left.years,
            'months': life_left.months,
            'days': life_left.days
        },
        'sex': data.sex[sex][0],
        'country': country,
        'lived': {
            'years': abs(lived.years),
            'months': abs(lived.months)
        }
    }

    return render_template('result.html', **params)

@app.route('/<path:url>')
@app.route('/<string:url>')
def other(url=''):
    lt_lib.log(
        request.remote_addr,
        url,
        request.method,
        datetime.now()
    )
    abort(400)
